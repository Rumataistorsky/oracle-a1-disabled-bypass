"""Turn failing findings into ready-to-paste fixes (HTML snippets, policy sections)."""

from __future__ import annotations

import json

from .models import AuditReport, Rule

FIX_SYSTEM = """You are a senior web developer and privacy/compliance consultant for Canadian small
businesses. You receive failing compliance findings for a website and produce a fix pack in Markdown.

For each failing rule produce a section with:
1. the rule id and title;
2. a short explanation of what must change (2-3 sentences, plain English);
3. a ready-to-paste artifact: HTML/JS for UI changes (forms, banners, footers), or policy text for
   privacy/terms sections. Keep HTML accessible (labels, lang, buttons). For Quebec rules provide the
   French text as well as English.
4. how to verify the fix.

Do not invent facts about the business (legal name, address, officer name): use clearly marked
placeholders like [LEGAL_NAME]. Output Markdown only."""


def generate_fixes(report: AuditReport, rules: list[Rule], model: str = "claude-opus-5", client=None) -> str:
    import anthropic

    client = client or anthropic.Anthropic()
    by_id = {r.id: r for r in rules}
    failing = [
        {
            "rule_id": f.rule_id,
            "title": by_id[f.rule_id].title,
            "law": by_id[f.rule_id].law,
            "requirement": by_id[f.rule_id].requirement,
            "where": f.page_url,
            "evidence": f.evidence,
            "why": f.explanation,
            "suggested_fix": f.fix or by_id[f.rule_id].fix_hint,
        }
        for f in report.findings
        if f.status == "fail"
    ]
    if not failing:
        return "# Fix pack\n\nNo failing findings.\n"

    user = (
        f"Site: {report.site}\nJurisdictions: federal + {', '.join(report.provinces)}\n\n"
        f"Site signals:\n```json\n{json.dumps(report.signals, indent=1, sort_keys=True)}\n```\n\n"
        f"Failing findings:\n```json\n{json.dumps(failing, indent=1)}\n```"
    )
    with client.messages.stream(
        model=model,
        max_tokens=64000,
        system=[{"type": "text", "text": FIX_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        messages=[{"role": "user", "content": user}],
    ) as stream:
        message = stream.get_final_message()
    if message.stop_reason == "refusal":
        raise RuntimeError("model declined to generate fixes")
    return "".join(b.text for b in message.content if b.type == "text")
