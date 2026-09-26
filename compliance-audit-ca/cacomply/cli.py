"""Command line: python -m cacomply audit <url> [options]."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .audit import ClaudeAuditor, run_audit
from .crawl import crawl, crawl_local
from .fixes import generate_fixes
from .report import render_markdown
from .rules import load_rules


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cacomply", description="Website compliance pre-check for Canadian law (prototype).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audit", help="crawl a site (or local folder) and audit it")
    a.add_argument("target", help="https://example.ca or a folder of HTML files with --local")
    a.add_argument("--local", action="store_true", help="treat target as a local folder")
    a.add_argument("--provinces", default="ON", help="comma-separated province codes the business serves, e.g. ON,QC,BC")
    a.add_argument("--max-pages", type=int, default=8)
    a.add_argument("--no-llm", action="store_true", help="mechanical checks only (no API key needed)")
    a.add_argument("--model", default="claude-opus-5")
    a.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    a.add_argument("--out", default="report.md", help="Markdown report path")
    a.add_argument("--json", dest="json_out", default=None, help="also write findings as JSON")
    a.add_argument("--fixes", default=None, help="also generate a fix pack (Markdown) to this path; needs the model")
    a.add_argument("-v", "--verbose", action="store_true")

    r = sub.add_parser("rules", help="list the rule base")
    r.add_argument("--law", default=None)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING, format="%(levelname)s %(message)s")

    rules = load_rules()
    if args.cmd == "rules":
        for rule in rules:
            if args.law and args.law.lower() not in rule.law.lower():
                continue
            print(f"{rule.id:10} {rule.jurisdiction:8} {rule.severity:6} {rule.title}")
        return 0

    provinces = [p.strip().upper() for p in args.provinces.split(",") if p.strip()]
    pages = crawl_local(args.target) if args.local else crawl(args.target, max_pages=args.max_pages)
    if not pages:
        print("no pages fetched", file=sys.stderr)
        return 2
    print(f"fetched {len(pages)} pages: " + ", ".join(f"{p.kind}" for p in pages), file=sys.stderr)

    auditor = None if args.no_llm else ClaudeAuditor(model=args.model, effort=args.effort)
    report = run_audit(args.target, pages, provinces, auditor=auditor, rules=rules)

    Path(args.out).write_text(render_markdown(report, rules), encoding="utf-8")
    print(f"report written to {args.out}", file=sys.stderr)
    if args.json_out:
        Path(args.json_out).write_text(report.model_dump_json(indent=1), encoding="utf-8")
    if args.fixes:
        if auditor is None:
            print("--fixes needs the model; drop --no-llm", file=sys.stderr)
            return 2
        Path(args.fixes).write_text(generate_fixes(report, rules, model=args.model, client=auditor.client), encoding="utf-8")
        print(f"fix pack written to {args.fixes}", file=sys.stderr)

    fails = sum(1 for f in report.findings if f.status == "fail")
    unclear = sum(1 for f in report.findings if f.status == "unclear")
    print(f"{fails} failing, {unclear} need review, {len(report.findings)} rules evaluated", file=sys.stderr)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
