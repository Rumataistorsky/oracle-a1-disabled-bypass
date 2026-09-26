"""End-to-end run on the fixture site: mechanical mode and a fake model."""

from pathlib import Path

from cacomply.audit import run_audit
from cacomply.crawl import crawl_local
from cacomply.models import Finding, PageAudit
from cacomply.report import render_markdown
from cacomply.rules import load_rules

FIXTURE = Path(__file__).parent / "fixtures" / "site"


class FakeAuditor:
    """Marks every rule 'pass' on the terms page except CASL-03, which it fails with evidence."""

    calls = 0

    def audit_page(self, page, rules, signals):
        FakeAuditor.calls += 1
        findings = []
        for r in rules:
            if r.id == "CASL-03" and page.kind == "terms":
                findings.append(Finding(rule_id=r.id, status="fail", evidence="You may not opt out of promotional emails", explanation="Contradicts the unsubscribe requirement.", risk="high", fix="Remove the clause.", page_url=page.url))
            elif page.kind == "terms":
                findings.append(Finding(rule_id=r.id, status="pass", page_url=page.url))
            else:
                findings.append(Finding(rule_id=r.id, status="unclear", page_url=page.url))
        findings.append(Finding(rule_id="BOGUS-99", status="fail", page_url=page.url))  # must be dropped
        return PageAudit(findings=findings)


def test_mechanical_mode_finds_expected_failures():
    rules = load_rules()
    report = run_audit("fixture", crawl_local(FIXTURE), ["ON", "QC"], auditor=None, rules=rules)
    status = {f.rule_id: f.status for f in report.findings}
    for rid in ["CASL-01", "CASL-02", "PIPEDA-01", "QC25-01", "QC25-02", "QC25-03", "FR-01", "AODA-01", "AODA-02", "AODA-03", "CA-01", "CP-QC-01"]:
        assert status[rid] == "fail", rid
    assert status["CASL-03"] == "unclear"  # needs the model
    assert set(report.rules_evaluated) == set(status)
    md = render_markdown(report, rules)
    assert "## Statutory exposure" in md
    assert "CASL-01" in md and "$10,000,000 CAD" in md
    assert "not legal advice" in md


def test_fake_model_merges_worst_status_and_drops_unknown_ids():
    rules = load_rules()
    report = run_audit("fixture", crawl_local(FIXTURE), ["ON"], auditor=FakeAuditor(), rules=rules)
    by_id = {f.rule_id: f for f in report.findings}
    assert "BOGUS-99" not in by_id
    assert by_id["CASL-03"].status == "fail"
    assert by_id["CASL-03"].source == "llm"
    assert by_id["CASL-01"].source == "auto"  # auto fail is not re-asked to the model
    assert by_id["PIPEDA-02"].status == "pass"  # fake model passed it on the terms page, unclear elsewhere
    assert FakeAuditor.calls == 4
