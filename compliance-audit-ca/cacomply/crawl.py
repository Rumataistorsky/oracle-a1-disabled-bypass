"""Fetch a site (or a local folder) and convert key pages to Markdown."""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from .models import Page

USER_AGENT = "cacomply/0.1 (+compliance pre-check bot; contact site owner before use)"

# Link keywords → page kind. Order matters: first match wins.
KIND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("privacy", re.compile(r"privacy|confidentialit|vie-priv|personal-?data|donn[ée]es", re.I)),
    ("cookies", re.compile(r"cookie", re.I)),
    ("terms", re.compile(r"terms|conditions|legal|tos\b|eula|agreement", re.I)),
    ("accessibility", re.compile(r"accessib", re.I)),
    ("contact", re.compile(r"contact|about|nous-joindre|a-propos", re.I)),
    ("returns", re.compile(r"return|refund|shipping|livraison|remboursement|cancel", re.I)),
    ("pricing", re.compile(r"pricing|plans|tarif|prix|subscribe|abonnement|checkout|cart|panier|shop|store|product|boutique", re.I)),
    ("fr", re.compile(r"(^|/)fr(/|$|-)|francais|français|lang=fr", re.I)),
]


def classify(url: str, text: str = "") -> str:
    """Classify a link/page by URL path and anchor text."""
    hay = f"{urlparse(url).path} {text}"
    for kind, pat in KIND_PATTERNS:
        if pat.search(hay):
            return kind
    return "other"


def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "template"]):
        tag.decompose()
    body = soup.body or soup
    md = markdownify(str(body), heading_style="ATX", strip=["img"])
    # Collapse whitespace so the model gets a compact document.
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = re.sub(r"[ \t]{2,}", " ", md)
    return md.strip()


def page_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    return (soup.title.string or "").strip() if soup.title and soup.title.string else ""


def _same_site(base: str, link: str) -> bool:
    b, l = urlparse(base), urlparse(link)
    return l.scheme in ("http", "https") and l.netloc.lower().removeprefix("www.") == b.netloc.lower().removeprefix("www.")


def crawl(start_url: str, max_pages: int = 8, timeout: float = 15.0) -> list[Page]:
    """BFS from the home page, prioritising legally relevant links (privacy, terms, contact...)."""
    if not start_url.startswith("http"):
        start_url = "https://" + start_url
    seen: set[str] = set()
    pages: list[Page] = []
    queue: deque[tuple[str, str]] = deque([(start_url, "home")])

    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=timeout) as client:
        while queue and len(pages) < max_pages:
            url, kind = queue.popleft()
            norm = url.split("#")[0].rstrip("/")
            if norm in seen:
                continue
            seen.add(norm)
            try:
                resp = client.get(url)
            except httpx.HTTPError:
                continue
            if resp.status_code >= 400 or "html" not in resp.headers.get("content-type", ""):
                continue
            html = resp.text
            pages.append(Page(url=str(resp.url), title=page_title(html), html=html, markdown=html_to_markdown(html), kind=kind))

            # Discover links; legally relevant ones go to the front of the queue.
            soup = BeautifulSoup(html, "lxml")
            relevant: list[tuple[str, str]] = []
            others: list[tuple[str, str]] = []
            for a in soup.find_all("a", href=True):
                link = urljoin(str(resp.url), a["href"])
                if not _same_site(start_url, link) or link.split("#")[0].rstrip("/") in seen:
                    continue
                k = classify(link, a.get_text(" ", strip=True))
                (relevant if k != "other" else others).append((link, k))
            for item in relevant:
                queue.appendleft(item)
            for item in others[:5]:
                queue.append(item)
    return pages


def crawl_local(folder: str | Path) -> list[Page]:
    """Audit a folder of HTML files (offline mode / tests). index.html is treated as home."""
    folder = Path(folder)
    pages: list[Page] = []
    for path in sorted(folder.rglob("*.html")):
        html = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(folder).as_posix()
        kind = "home" if path.name == "index.html" and path.parent == folder else classify("/" + rel)
        pages.append(Page(url=f"file://{rel}", title=page_title(html), html=html, markdown=html_to_markdown(html), kind=kind))
    # Home first, then the rest in discovery order.
    pages.sort(key=lambda p: 0 if p.kind == "home" else 1)
    return pages
