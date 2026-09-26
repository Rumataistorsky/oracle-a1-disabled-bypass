"""Exercise ClaudeAuditor and generate_fixes against a stub client (no network, no key)."""

from types import SimpleNamespace

from cacomply.audit import ClaudeAuditor
from cacomply.fixes import generate_fixes
from cacomply.models import AuditReport, Finding, Page, PageAudit
from cacomply.rules import load_rules


class StubMessages:
    def __init__(self):
        self.parse_kwargs = None
        self.stream_kwargs = None

    def parse(self, **kwargs):
        self.parse_kwargs = kwargs
        rules = kwargs["output_format"]
        assert rules is PageAudit
        return SimpleNamespace(
            stop_reason="end_turn",
            parsed_output=PageAudit(findings=[Finding(rule_id="CASL-03", status="fail", evidence="no opt out", risk="high", fix="add unsubscribe")]),
        )

    def stream(self, **kwargs):
        self.stream_kwargs = kwargs
        msg = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="# Fix pack\n\n## CASL-03\n...")])

        class Ctx:
            def __enter__(self_inner):
                return SimpleNamespace(get_final_message=lambda: msg)

            def __exit__(self_inner, *a):
                return False

        return Ctx()


def test_claude_auditor_request_shape():
    stub = SimpleNamespace(messages=StubMessages())
    auditor = ClaudeAuditor(model="claude-opus-5", effort="medium", client=stub)
    rules = [r for r in load_rules() if r.id == "CASL-03"]
    page = Page(url="https://x.example/terms", title="Terms", html="<html></html>", markdown="You may not opt out.", kind="terms")
    audit = auditor.audit_page(page, rules, {"email_signup_form": True})
    assert audit.findings[0].page_url == page.url and audit.findings[0].source == "llm"
    kw = stub.messages.parse_kwargs
    assert kw["model"] == "claude-opus-5"
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "CASL-03" in kw["messages"][0]["content"] and "You may not opt out." in kw["messages"][0]["content"]


def test_generate_fixes_uses_streaming():
    stub = SimpleNamespace(messages=StubMessages())
    rules = load_rules()
    report = AuditReport(site="x", provinces=["ON"], pages=[], signals={}, rules_evaluated=["CASL-03"], findings=[Finding(rule_id="CASL-03", status="fail")])
    md = generate_fixes(report, rules, client=stub)
    assert md.startswith("# Fix pack")
    assert stub.messages.stream_kwargs["max_tokens"] == 64000
