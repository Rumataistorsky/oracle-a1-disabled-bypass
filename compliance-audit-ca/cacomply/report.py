"""Render an AuditReport as Markdown."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .models import AuditReport, Rule

SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
STATUS_ICON = {"fail": "FAIL", "unclear": "REVIEW", "pass": "PASS", "not_applicable": "N/A"}

DISCLAIMER = (
    "This report is an automated pre-check generated from the public pages of the website. "
    "It is not legal advice and does not create a solicitor-client relationship. Statutory penalty "
    "figures are maximums under the cited provisions and are shown to prioritise work, not to predict "
    "an outcome. Have a lawyer licensed in the relevant province review anything marked FAIL or REVIEW."
)


def _money(n: int | None) -> str:
    return f"${n:,} CAD" if n else "n/a"


def render_markdown(report: AuditReport, rules: list[Rule]) -> str:
    by_id = {r.id: r for r in rules}
    findings = report.findings
    counts = defaultdict(int)
    for f in findings:
        counts[f.status] += 1

    lines: list[str] = []
    lines.append(f"# Compliance pre-check: {report.site}")
    lines.append("")
    lines.append(f"Date: {date.today().isoformat()}  ")
    lines.append(f"Jurisdictions: federal + {', '.join(report.provinces) or 'none'}  ")
    lines.append(f"Pages reviewed: {len(report.pages)}  ")
    lines.append(f"Rules in scope: {len(report.rules_evaluated)}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|---|---|")
    for st in ("fail", "unclear", "pass", "not_applicable"):
        lines.append(f"| {STATUS_ICON[st]} | {counts.get(st, 0)} |")
    lines.append("")

    # Exposure: per law, the highest statutory maximum among failing rules.
    exposure: dict[str, tuple[int, list[str]]] = {}
    for f in findings:
        if f.status != "fail":
            continue
        r = by_id[f.rule_id]
        cap, ids = exposure.get(r.law, (0, []))
        exposure[r.law] = (max(cap, r.penalty_max_cad or 0), ids + [r.id])
    if exposure:
        lines.append("## Statutory exposure (maximums, by law)")
        lines.append("")
        lines.append("| Law | Failing rules | Max penalty per violation |")
        lines.append("|---|---|---|")
        for law, (cap, ids) in sorted(exposure.items(), key=lambda kv: -kv[1][0]):
            lines.append(f"| {law} | {', '.join(ids)} | {_money(cap)} |")
        lines.append("")

    def section(title: str, status: str) -> None:
        items = [f for f in findings if f.status == status]
        if not items:
            return
        items.sort(key=lambda f: (SEV_ORDER[by_id[f.rule_id].severity], f.rule_id))
        lines.append(f"## {title} ({len(items)})")
        lines.append("")
        for f in items:
            r = by_id[f.rule_id]
            lines.append(f"### {r.id} - {r.title}")
            lines.append("")
            lines.append(f"- Law: {r.law} ({r.jurisdiction})")
            lines.append(f"- Severity: {r.severity} / risk seen: {f.risk} / source: {f.source}")
            lines.append(f"- Where: {f.page_url}")
            if f.evidence:
                lines.append(f"- Evidence: \"{f.evidence.strip()}\"")
            if f.explanation:
                lines.append(f"- Why: {f.explanation.strip()}")
            if status != "pass":
                lines.append(f"- Penalty: {r.penalty}")
                lines.append(f"- Fix: {(f.fix or r.fix_hint).strip()}")
            lines.append(f"- Source: {r.source}")
            lines.append("")

    section("Failing", "fail")
    section("Needs review", "unclear")
    section("Passing", "pass")

    lines.append("## Site signals (mechanical)")
    lines.append("")
    lines.append("```json")
    import json

    lines.append(json.dumps(report.signals, indent=1, sort_keys=True))
    lines.append("```")
    lines.append("")
    lines.append("## Disclaimer")
    lines.append("")
    lines.append(DISCLAIMER)
    lines.append("")
    return "\n".join(lines)
