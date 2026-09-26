"""Load the YAML rule base and select the rules that apply to a site."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Rule
from .signals import evaluate

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"


def load_rules(jurisdiction_dir: str = "canada") -> list[Rule]:
    rules: list[Rule] = []
    for path in sorted((RULES_DIR / jurisdiction_dir).glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        for item in data:
            rules.append(Rule(**item))
    ids = [r.id for r in rules]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate rule ids: {sorted(dupes)}")
    return rules


def applicable_rules(rules: list[Rule], signals: dict[str, Any], provinces: list[str]) -> list[Rule]:
    """Federal rules always apply; provincial rules apply when the site targets that province.

    `applies_when` lists signal names that must be truthy (all of them) for the rule to be in scope.
    """
    selected: list[Rule] = []
    targeted = {p.upper() for p in provinces}
    if signals.get("targets_quebec"):
        targeted.add("QC")
    if signals.get("targets_ontario"):
        targeted.add("ON")
    for rule in rules:
        if rule.jurisdiction != "federal" and rule.jurisdiction.upper() not in targeted:
            continue
        if rule.applies_when and not all(evaluate(cond, signals) for cond in rule.applies_when):
            continue
        selected.append(rule)
    return selected


def rules_for_prompt(rules: list[Rule]) -> list[dict[str, Any]]:
    """Compact representation sent to the model (no penalties/fix hints - the model should judge facts)."""
    return [
        {
            "id": r.id,
            "law": r.law,
            "title": r.title,
            "requirement": r.requirement,
            "check": r.check,
        }
        for r in rules
    ]
