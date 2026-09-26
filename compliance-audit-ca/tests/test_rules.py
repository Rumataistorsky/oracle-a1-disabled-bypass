from cacomply.rules import applicable_rules, load_rules


def test_rule_base_loads_and_is_consistent():
    rules = load_rules()
    assert len(rules) >= 30
    for r in rules:
        assert r.jurisdiction in {"federal", "ON", "QC"}
        assert r.source.startswith("http")
        assert r.penalty
        assert r.severity in {"low", "medium", "high"}


def test_provincial_scoping():
    rules = load_rules()
    base = {"collects_personal_info": True, "uses_trackers": True, "ecommerce": True, "email_signup_form": True}
    federal_only = applicable_rules(rules, {**base, "targets_quebec": False, "targets_ontario": False}, [])
    assert all(r.jurisdiction == "federal" for r in federal_only)
    with_qc = applicable_rules(rules, {**base, "targets_quebec": True, "targets_ontario": False}, ["QC"])
    assert any(r.jurisdiction == "QC" for r in with_qc)
    assert not any(r.jurisdiction == "ON" for r in with_qc)


def test_applies_when_filters():
    rules = load_rules()
    no_forms = applicable_rules(rules, {"collects_personal_info": False, "email_signup_form": False, "ecommerce": False}, ["ON"])
    ids = {r.id for r in no_forms}
    assert "CASL-01" not in ids
    assert "PIPEDA-01" not in ids
    assert "AODA-01" in ids  # accessibility always applies in Ontario
