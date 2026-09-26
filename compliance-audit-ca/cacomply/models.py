"""Pydantic models shared across the pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high"]
Status = Literal["pass", "fail", "unclear", "not_applicable"]


class Page(BaseModel):
    url: str
    title: str = ""
    html: str
    markdown: str
    kind: str = "other"  # home | privacy | terms | contact | checkout | fr | other


class Rule(BaseModel):
    id: str
    law: str
    jurisdiction: str  # federal | ON | QC | BC | AB ...
    title: str
    requirement: str
    check: str
    applies_when: list[str] = Field(default_factory=list)  # signal names; empty = always
    severity: Severity = "medium"
    penalty: str = ""
    penalty_max_cad: int | None = None
    source: str = ""
    fix_hint: str = ""
    auto_fail_when: str | None = None  # expression over signals, e.g. "prechecked_checkboxes > 0"
    auto_pass_when: str | None = None


class Finding(BaseModel):
    rule_id: str
    status: Status
    evidence: str = Field(default="", description="Short verbatim quote from the page that supports the verdict, or empty.")
    explanation: str = Field(default="", description="One or two sentences: why this is a pass/fail/unclear.")
    risk: Severity = "medium"
    fix: str = Field(default="", description="Concrete, actionable change for the site owner.")
    page_url: str = ""
    source: Literal["auto", "llm"] = "llm"


class PageAudit(BaseModel):
    """Structured output the model returns for one page."""

    findings: list[Finding]


class AuditReport(BaseModel):
    site: str
    provinces: list[str]
    pages: list[str]
    signals: dict
    rules_evaluated: list[str]
    findings: list[Finding]
