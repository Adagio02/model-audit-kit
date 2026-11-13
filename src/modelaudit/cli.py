"""Command line: modelaudit run --prices prices.csv --positions positions.csv --out report/"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from modelaudit.audit import run_from_files, write_json
from modelaudit.report import write_html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="modelaudit", description="Independent backtest audit.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Audit a strategy from CSV files.")
    run.add_argument("--prices", required=True, help="CSV with date,ticker,close (adjusted)")
    run.add_argument("--positions", required=True, help="CSV with date,ticker,weight (set at that close)")
    run.add_argument("--gates", help="JSON gate settings (defaults if omitted)")
    run.add_argument("--name", default="Client strategy", help="Strategy name shown in the report")
    run.add_argument("--out", default="audit-report", help="Output folder")
    args = parser.parse_args(argv)

    result = run_from_files(args.prices, args.positions, args.gates, args.name)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_html(result, out / "report.html")
    write_json(result, out / "results.json")
    print(f"{args.name}: {result.verdict}")
    for check in result.checks:
        print(f"  [{check.status:<4}] {check.title}: {check.summary}")
    print(f"Report: {out / 'report.html'}")
    return {"PASS": 0, "CONDITIONAL": 0, "FAIL": 2}[result.verdict]


if __name__ == "__main__":
    sys.exit(main())
