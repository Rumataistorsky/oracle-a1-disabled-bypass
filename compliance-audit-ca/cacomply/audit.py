"""Audit orchestration: deterministic findings + Claude review of each page against the rules."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from .models import AuditReport, Finding, Page, PageAudit, Rule
from .rules import applicable_rules, load_rules, rules_for_prompt
from .signals import collect_signals, evaluate

log = logging.getLogger(__name__)

STATUS_RANK = {"fail": 3, "pass": 2, "unclear": 1, "not_applicable": 0}  # a clear pass on one page beats "unclear" on another
MAX_PAGE_CHARS = 200_000  # ~50k tokens; anything above is split, never silently cut

SYSTEM_PROMPT = """You are a Canadian regulatory compliance reviewer. You receive one page of a website
converted to Markdown, a summary of site-wide signals detected mechanically, and a list of legal rules.

For EVERY rule in the list return exactly one finding with:
- rule_id: copied verbatim from the list
- status: "fail" when the page clearly breaches the requirement, "pass" when the page clearly satisfies it,
  "unclear" when this page does not contain enough information to decide, "not_applicable" when the rule
  cannot apply to this kind of page (for example a privacy-policy rule on a product page).
- evidence: a short verbatim quote (max 200 characters) from the page that supports the verdict, or "".
- explanation: one or two plain-language sentences.
- risk: low, medium or high - how likely a regulator or consumer complaint is, given what you see.
- fix: a concrete change the site owner can make (wording, element, placement). Empty when status is pass.

Rules of judgement:
- Judge only what is on this page plus the site-wide signals. Do not assume content exists elsewhere.
- Prefer "unclear" over guessing. A missing statement is a "fail" only when the rule requires it to be on
  this kind of page.
- Quote evidence exactly; never invent text.
- This is a pre-check for the site owner, not legal advice; be specific and practical."""


class Auditor(Protocol):
    def audit_page(self, page: Page, rules: list[Rule], signals: dict[str, Any]) -> PageAudit: ...


class ClaudeAuditor:
    """Reviews pages with Claude using structured output (PageAudit)."""

    def __init__(self, model: str = "claude-opus-5", effort: str = "high", client=None):
        import anthropic

        self.client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort

    def audit_page(self, page: Page, rules: list[Rule], signals: dict[str, Any]) -> PageAudit:
        chunks = [page.markdown[i : i + MAX_PAGE_CHARS] for i in range(0, max(len(page.markdown), 1), MAX_PAGE_CHARS)]
        if len(chunks) > 1:
            log.warning("%s is %d chars; auditing in %d chunks", page.url, len(page.markdown), len(chunks))
        findings: list[Finding] = []
        for idx, chunk in enumerate(chunks):
            findings.extend(self._audit_chunk(page, chunk, idx, len(chunks), rules, signals).findings)
        return PageAudit(findings=findings)

    def _audit_chunk(self, page: Page, text: str, idx: int, total: int, rules: list[Rule], signals: dict[str, Any]) -> PageAudit:
        part = f" (part {idx + 1} of {total})" if total > 1 else ""
        user_content = (
            f"## Page{part}\nURL: {page.url}\nTitle: {page.title}\nKind: {page.kind}\n\n"
            f"## Site-wide signals (detected mechanically)\n```json\n{json.dumps(signals, indent=1, sort_keys=True)}\n```\n\n"
            f"## Rules to evaluate\n```json\n{json.dumps(rules_for_prompt(rules), indent=1)}\n```\n\n"
            f"## Page content (Markdown)\n{text}"
        )
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": user_content}],
            output_format=PageAudit,
        )
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise RuntimeError(f"model declined to audit {page.url}: {getattr(details, 'explanation', '')}")
        if response.stop_reason == "max_tokens":
            raise RuntimeError(f"audit output for {page.url} was cut off at max_tokens; raise the limit")
        audit = response.parsed_output
        for f in audit.findings:
            f.page_url = page.url
            f.source = "llm"
        return audit


def _signal_evidence(expr: str, signals: dict[str, Any]) -> str:
    """Show the actual signal values behind an auto verdict, e.g. 'prechecked_checkboxes=1'."""
    names = [n for n in re.findall(r"[a-z_]+", expr) if n in signals]
    return "; ".join(f"{n}={signals[n]!r}" for n in dict.fromkeys(names))


def auto_findings(rules: list[Rule], signals: dict[str, Any]) -> list[Finding]:
    """Resolve rules that carry auto_fail_when / auto_pass_when expressions from signals alone."""
    out: list[Finding] = []
    for rule in rules:
        if rule.auto_fail_when and evaluate(rule.auto_fail_when, signals):
            out.append(
                Finding(
                    rule_id=rule.id,
                    status="fail",
                    evidence=_signal_evidence(rule.auto_fail_when, signals),
                    explanation=f"Detected mechanically: {rule.title.lower()} is not met ({rule.auto_fail_when}).",
                    risk=rule.severity,
                    fix=rule.fix_hint,
                    page_url="(site-wide)",
                    source="auto",
                )
            )
        elif rule.auto_pass_when and evaluate(rule.auto_pass_when, signals):
            out.append(Finding(rule_id=rule.id, status="pass", evidence=f"signals: {rule.auto_pass_when}", risk="low", page_url="(site-wide)", source="auto"))
    return out


def merge_findings(all_findings: list[Finding], rule_ids: set[str]) -> list[Finding]:
    """One finding per rule: fail > pass > unclear > not_applicable; auto findings win ties."""
    best: dict[str, Finding] = {}
    for f in all_findings:
        if f.rule_id not in rule_ids:
            log.warning("model returned unknown rule id %s; dropped", f.rule_id)
            continue
        cur = best.get(f.rule_id)
        if cur is None:
            best[f.rule_id] = f
            continue
        r_new, r_cur = STATUS_RANK[f.status], STATUS_RANK[cur.status]
        if r_new > r_cur or (r_new == r_cur and f.source == "auto" and cur.source != "auto"):
            best[f.rule_id] = f
        elif r_new == r_cur and f.status == "fail" and f.page_url not in cur.page_url:
            cur.page_url = f"{cur.page_url}, {f.page_url}"
    return [best[k] for k in sorted(best)]


def run_audit(
    site: str,
    pages: list[Page],
    provinces: list[str],
    auditor: Auditor | None = None,
    rules: list[Rule] | None = None,
) -> AuditReport:
    rules = rules if rules is not None else load_rules()
    signals = collect_signals(pages, provinces)
    scoped = applicable_rules(rules, signals, provinces)
    findings = auto_findings(scoped, signals)
    auto_failed = {f.rule_id for f in findings if f.status == "fail"}

    if auditor is not None:
        remaining = [r for r in scoped if r.id not in auto_failed]
        for page in pages:
            if not remaining:
                break
            log.info("auditing %s against %d rules", page.url, len(remaining))
            findings.extend(auditor.audit_page(page, remaining, signals).findings)
    else:
        # No model: every rule without a mechanical verdict is reported as unclear so nothing is silently skipped.
        decided = {f.rule_id for f in findings}
        for r in scoped:
            if r.id not in decided:
                findings.append(Finding(rule_id=r.id, status="unclear", explanation="Needs model or manual review (run without --no-llm).", risk=r.severity, page_url="(site-wide)", source="auto"))

    merged = merge_findings(findings, {r.id for r in scoped})
    return AuditReport(
        site=site,
        provinces=provinces,
        pages=[p.url for p in pages],
        signals=signals,
        rules_evaluated=[r.id for r in scoped],
        findings=merged,
    )
