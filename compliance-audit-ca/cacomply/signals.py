"""Deterministic, LLM-free checks over the crawled pages.

Signals do two jobs:
1. decide which rules apply (e.g. CASL consent rules only matter if there is an email sign-up form);
2. auto-resolve rules that can be decided mechanically (pre-checked consent boxes, missing alt text...).
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from .models import Page

TRACKER_PATTERNS = {
    "google_analytics": re.compile(r"googletagmanager\.com|google-analytics\.com|gtag\(|ga\('create'", re.I),
    "meta_pixel": re.compile(r"connect\.facebook\.net|fbq\(", re.I),
    "hotjar": re.compile(r"hotjar\.com|hj\(", re.I),
    "tiktok_pixel": re.compile(r"analytics\.tiktok\.com|ttq\.", re.I),
    "linkedin_insight": re.compile(r"snap\.licdn\.com", re.I),
}

PRICE_RE = re.compile(r"(?:\$|CAD|C\$)\s?\d[\d,]*(?:\.\d{2})?", re.I)
DRIP_RE = re.compile(r"plus (?:applicable )?fees|fees? (?:apply|added) at checkout|excluding (?:service|booking|processing) fee|\bconvenience fee\b|\+\s?fees", re.I)
SALE_RE = re.compile(r"\bwas \$|\bregular(?:ly)? \$|\bsave \d+%|\bup to \d+% off|\bcompare at\b|\bMSRP\b", re.I)
GREEN_RE = re.compile(r"\beco-?friendly\b|\bcarbon[- ]neutral\b|\bnet[- ]zero\b|\bsustainable\b|\bgreen\b|\bbiodegradable\b|\brecyclable\b", re.I)
REVIEW_RE = re.compile(r"\btestimonial|\breviews?\b|★|⭐|\d(?:\.\d)?/5\b", re.I)
FREE_RE = re.compile(r"\bfree\b", re.I)
SUBSCRIPTION_RE = re.compile(r"auto-?renew|recurring|subscription|billed (?:monthly|annually|yearly)|per month|/mo\b|/month", re.I)
UNSUB_RE = re.compile(r"unsubscribe|opt[- ]out|se d[ée]sabonner|d[ée]sinscri", re.I)
QUEBEC_RE = re.compile(r"\bQu[ée]bec\b|\bQC\b|\bMontr[ée]al\b|\bLaval\b|\bGatineau\b", re.I)
ONTARIO_RE = re.compile(r"\bOntario\b|\bON\b|\bToronto\b|\bOttawa\b", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
POSTAL_RE = re.compile(r"\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d\b", re.I)
PRIVACY_OFFICER_RE = re.compile(r"privacy officer|chief privacy|data protection officer|responsable de la protection des renseignements personnels|person in charge of (?:the )?protection of personal information", re.I)
COOKIE_BANNER_RE = re.compile(r"cookie", re.I)
CONSENT_BTN_RE = re.compile(r"accept|agree|got it|allow|j'accepte|accepter|ok\b", re.I)
REJECT_BTN_RE = re.compile(r"reject|decline|refuse|deny|only necessary|refuser", re.I)
ACCESSIBILITY_RE = re.compile(r"accessibility|accessibilit[ée]|WCAG|AODA", re.I)
CROSS_BORDER_RE = re.compile(r"outside (?:of )?(?:canada|qu[ée]bec)|united states|\bU\.?S\.?\b|third[- ]part(?:y|ies)|service providers?|transfer", re.I)
ACCESS_RIGHTS_RE = re.compile(r"access (?:to )?(?:your|their) (?:personal )?(?:information|data)|request access|correct(?:ion)? of|right to (?:access|correct|delete|withdraw|portab)", re.I)
COMPLAINT_RE = re.compile(r"complain|Office of the Privacy Commissioner|Commission d'acc[èe]s [àa] l'information", re.I)
PURPOSE_RE = re.compile(r"(?:we|our)\s+(?:use|collect)\s+(?:your|the)\s+(?:personal )?(?:information|data)|purposes? (?:for which|of collection)|why we collect", re.I)


def _text(page: Page) -> str:
    return BeautifulSoup(page.html, "lxml").get_text(" ", strip=True)


def _label_for(inp, soup) -> bool:
    if inp.get("aria-label") or inp.get("aria-labelledby") or inp.get("title"):
        return True
    if inp.get("id") and soup.find("label", attrs={"for": inp["id"]}):
        return True
    return inp.find_parent("label") is not None


def collect_signals(pages: list[Page], provinces: list[str]) -> dict[str, Any]:
    """Return a flat dict of booleans/ints/strings describing the whole site."""
    s: dict[str, Any] = {
        "provinces": provinces,
        "page_count": len(pages),
        "page_kinds": sorted({p.kind for p in pages}),
        "has_privacy_page": any(p.kind == "privacy" for p in pages),
        "has_terms_page": any(p.kind == "terms" for p in pages),
        "has_contact_page": any(p.kind == "contact" for p in pages),
        "has_accessibility_page": any(p.kind == "accessibility" for p in pages),
        "has_french_version": False,
        "html_lang_missing_pages": 0,
        "html_lang_values": [],
        "trackers": [],
        "has_cookie_banner": False,
        "cookie_banner_has_reject": False,
        "email_signup_form": False,
        "collects_personal_info": False,
        "prechecked_checkboxes": 0,
        "images_missing_alt": 0,
        "images_total": 0,
        "inputs_without_label": 0,
        "skip_link": False,
        "mentions_unsubscribe": False,
        "sender_identified": False,
        "privacy_officer_named": False,
        "privacy_policy_mentions_purposes": False,
        "privacy_policy_mentions_access_rights": False,
        "privacy_policy_mentions_complaints": False,
        "privacy_policy_mentions_transfers": False,
        "ecommerce": False,
        "prices_shown": 0,
        "drip_pricing_phrases": [],
        "has_drip_pricing": False,
        "sale_price_claims": 0,
        "green_claims": 0,
        "free_claims": 0,
        "reviews_or_testimonials": False,
        "subscription_or_recurring": False,
        "mentions_quebec": False,
        "mentions_ontario": False,
        "targets_quebec": "QC" in provinces,
        "targets_ontario": "ON" in provinces,
    }
    lang_values: set[str] = set()
    trackers: set[str] = set()
    all_text_parts: list[str] = []
    privacy_text_parts: list[str] = []

    for page in pages:
        soup = BeautifulSoup(page.html, "lxml")
        text = soup.get_text(" ", strip=True)
        all_text_parts.append(text)
        if page.kind in ("privacy", "cookies"):
            privacy_text_parts.append(text)

        html_tag = soup.find("html")
        lang = (html_tag.get("lang") or "").strip().lower() if html_tag else ""
        if lang:
            lang_values.add(lang)
        else:
            s["html_lang_missing_pages"] += 1
        if lang.startswith("fr") or soup.find("link", attrs={"hreflang": re.compile(r"^fr", re.I)}) or soup.find("a", href=re.compile(r"(^|/)fr(/|$)", re.I)):
            s["has_french_version"] = True

        for name, pat in TRACKER_PATTERNS.items():
            if pat.search(page.html):
                trackers.add(name)

        # Cookie banner heuristic: an element mentioning cookies that also has an accept-style button.
        for el in soup.find_all(["div", "section", "aside", "dialog"], limit=400):
            el_text = el.get_text(" ", strip=True)
            if len(el_text) > 600 or not COOKIE_BANNER_RE.search(el_text):
                continue
            buttons = [b.get_text(" ", strip=True) for b in el.find_all(["button", "a"])]
            if any(CONSENT_BTN_RE.search(b) for b in buttons):
                s["has_cookie_banner"] = True
                if any(REJECT_BTN_RE.search(b) for b in buttons):
                    s["cookie_banner_has_reject"] = True
                break

        for form in soup.find_all("form"):
            inputs = form.find_all(["input", "textarea", "select"])
            types = {(i.get("type") or "text").lower() for i in inputs}
            names = " ".join((i.get("name") or "") + " " + (i.get("id") or "") + " " + (i.get("placeholder") or "") for i in inputs).lower()
            if "email" in types or "email" in names:
                s["collects_personal_info"] = True
                form_text = form.get_text(" ", strip=True).lower()
                if re.search(r"newsletter|subscribe|sign ?up|updates|promotions|offers|infolettre|abonn", form_text + " " + names):
                    s["email_signup_form"] = True
            if types & {"tel", "password"} or re.search(r"name|phone|address|postal", names):
                s["collects_personal_info"] = True
            for cb in form.find_all("input", attrs={"type": re.compile("checkbox", re.I)}):
                if cb.has_attr("checked"):
                    s["prechecked_checkboxes"] += 1

        for img in soup.find_all("img"):
            s["images_total"] += 1
            if img.get("role") == "presentation" or img.get("aria-hidden") == "true":
                continue
            if img.get("alt") is None:
                s["images_missing_alt"] += 1

        for inp in soup.find_all(["input", "textarea", "select"]):
            if (inp.get("type") or "text").lower() in ("hidden", "submit", "button", "image", "reset"):
                continue
            if not _label_for(inp, soup):
                s["inputs_without_label"] += 1

        if soup.find("a", href=re.compile(r"^#(main|content|skip)", re.I)):
            s["skip_link"] = True

    text_all = " ".join(all_text_parts)
    privacy_text = " ".join(privacy_text_parts)

    s["html_lang_values"] = sorted(lang_values)
    s["trackers"] = sorted(trackers)
    s["mentions_unsubscribe"] = bool(UNSUB_RE.search(text_all))
    s["sender_identified"] = bool(EMAIL_RE.search(text_all) or PHONE_RE.search(text_all)) and bool(POSTAL_RE.search(text_all))
    s["privacy_officer_named"] = bool(PRIVACY_OFFICER_RE.search(text_all))
    s["privacy_policy_mentions_purposes"] = bool(PURPOSE_RE.search(privacy_text))
    s["privacy_policy_mentions_access_rights"] = bool(ACCESS_RIGHTS_RE.search(privacy_text))
    s["privacy_policy_mentions_complaints"] = bool(COMPLAINT_RE.search(privacy_text))
    s["privacy_policy_mentions_transfers"] = bool(CROSS_BORDER_RE.search(privacy_text))
    s["prices_shown"] = len(PRICE_RE.findall(text_all))
    s["ecommerce"] = s["prices_shown"] > 0 and bool(re.search(r"add to cart|buy now|checkout|panier|acheter|order now|subscribe now|start (?:free )?trial", text_all, re.I))
    s["drip_pricing_phrases"] = sorted({m.group(0) for m in DRIP_RE.finditer(text_all)})
    s["has_drip_pricing"] = bool(s["drip_pricing_phrases"])
    s["sale_price_claims"] = len(SALE_RE.findall(text_all))
    s["green_claims"] = len(GREEN_RE.findall(text_all))
    s["free_claims"] = len(FREE_RE.findall(text_all))
    s["reviews_or_testimonials"] = bool(REVIEW_RE.search(text_all))
    s["subscription_or_recurring"] = bool(SUBSCRIPTION_RE.search(text_all))
    s["mentions_quebec"] = bool(QUEBEC_RE.search(text_all))
    s["mentions_ontario"] = bool(ONTARIO_RE.search(text_all))
    s["targets_quebec"] = s["targets_quebec"] or s["mentions_quebec"]
    s["targets_ontario"] = s["targets_ontario"] or s["mentions_ontario"]
    s["uses_trackers"] = bool(trackers)
    s["has_consent_checkbox"] = bool(re.search(r"i agree|i consent|yes, (?:send|sign) me|je consens|j'accepte", text_all, re.I))
    return s


# --- tiny expression evaluator for rule auto_*_when ---------------------------------------

_CLAUSE_RE = re.compile(r"^\s*(not\s+)?([a-z_]+)\s*(?:(==|!=|>=|<=|>|<)\s*(\S+))?\s*$", re.I)


def _coerce(raw: str) -> Any:
    raw = raw.strip().strip("'\"")
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    try:
        return int(raw)
    except ValueError:
        return raw


def evaluate(expr: str, signals: dict[str, Any]) -> bool:
    """Evaluate 'a and not b and c > 0' style expressions over the signals dict.

    Unknown signals evaluate to False (so a typo in a rule never auto-fails a site).
    """
    for clause in re.split(r"\s+and\s+", expr.strip()):
        m = _CLAUSE_RE.match(clause)
        if not m:
            raise ValueError(f"bad clause in rule expression: {clause!r}")
        negate, name, op, raw = m.groups()
        if name not in signals:
            return False
        value = signals[name]
        if op is None:
            result = bool(value)
        else:
            target = _coerce(raw)
            result = {
                "==": value == target,
                "!=": value != target,
                ">": value > target,
                "<": value < target,
                ">=": value >= target,
                "<=": value <= target,
            }[op]
        if negate:
            result = not result
        if not result:
            return False
    return True
