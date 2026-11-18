"""Command line.

    modelaudit run      --prices prices.csv --positions positions.csv --out report/
    modelaudit stage    --root local-cloud --client acme --batch 2026-11-18 --prices p.csv --positions w.csv
    modelaudit pipeline --root local-cloud --client acme --batch 2026-11-18
    modelaudit export   --db local-cloud/results.db --out powerbi-data/
    modelaudit suggest-gates --prices p.csv --positions w.csv [--openai-endpoint https://<res>.openai.azure.com]

`stage` + `pipeline` run the same code path as the Azure Function, against a local folder and a
SQLite file, so you can develop and test the cloud pipeline without an Azure account.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from modelaudit.audit import run_from_files, write_json
from modelaudit.report import write_html


def _run(args) -> int:
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


def _stage(args) -> int:
    from modelaudit.cloud.store import INPUTS, SUBMIT_FILE, check_name

    folder = Path(args.root) / INPUTS / check_name(args.client, "client") / check_name(args.batch, "batch")
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.prices, folder / "prices.csv")
    shutil.copyfile(args.positions, folder / "positions.csv")
    if args.gates:
        shutil.copyfile(args.gates, folder / "gates.json")
    # submit.json goes last: in Azure its arrival is what triggers the audit.
    (folder / SUBMIT_FILE).write_text(json.dumps({"strategy": args.name or args.client}), encoding="utf-8")
    print(f"Staged {folder}")
    return 0


def _pipeline(args) -> int:
    from modelaudit.cloud.explain import RuleExplainer, make_explainer
    from modelaudit.cloud.pipeline import process_batch
    from modelaudit.cloud.sinks import SqliteSink
    from modelaudit.cloud.store import LocalStore

    if args.azure:  # real Blob Storage, Azure SQL and Foundry, configured by AUDIT_* env vars + az login
        from modelaudit.cloud.settings import azure_components

        store, sink, explainer = azure_components()
    else:
        root = Path(args.root)
        explainer = (make_explainer(args.openai_endpoint, args.openai_deployment, None)
                     if args.openai_endpoint else RuleExplainer())
        store, sink = LocalStore(root), SqliteSink(args.db or root / "results.db")
    outcome = process_batch(store, sink, explainer, args.client, args.batch)
    print(f"{outcome.client}/{outcome.batch}: {outcome.verdict}" + (f" ({outcome.error})" if outcome.error else ""))
    for item in outcome.explanations:
        print(f"  - {item['check_key']}: {item['explanation']}")
    if outcome.report_uri:
        print(f"Report: {outcome.report_uri}")
    return 2 if outcome.verdict in ("FAIL", "ERROR") else 0


def _export(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.db) as conn:
        for table in ("runs", "check_results", "explanations"):
            cur = conn.execute(f"SELECT * FROM {table}")
            with open(out / f"{table}.csv", "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow([d[0] for d in cur.description])
                writer.writerows(cur)
    print(f"Wrote runs.csv, check_results.csv, explanations.csv to {out}")
    return 0


def _suggest(args) -> int:
    from modelaudit.cloud.suggest import profile, suggest_gates
    from modelaudit.data import load_positions, load_prices

    prices, positions = load_prices(args.prices), load_positions(args.positions)
    if not args.openai_endpoint:
        print(json.dumps(profile(prices, positions), indent=2))
        print("Add --openai-endpoint and --openai-deployment to get suggested gates from a Foundry model.")
        return 0
    from modelaudit.cloud.explain import foundry_client

    gates, reasons, _ = suggest_gates(prices, positions, foundry_client(args.openai_endpoint),
                                      args.openai_deployment)
    for key, why in reasons.items():
        print(f"  {key} = {getattr(gates, key)!r}: {why}")
    Path(args.out).write_text(json.dumps(gates.to_dict(), indent=2), encoding="utf-8")
    print(f"Suggested gates written to {args.out}. Review them before the audit: they are part of the report.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="modelaudit", description="Independent backtest audit.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Audit a strategy from CSV files.")
    run.add_argument("--prices", required=True, help="CSV with date,ticker,close (adjusted)")
    run.add_argument("--positions", required=True, help="CSV with date,ticker,weight (set at that close)")
    run.add_argument("--gates", help="JSON gate settings (defaults if omitted)")
    run.add_argument("--name", default="Client strategy", help="Strategy name shown in the report")
    run.add_argument("--out", default="audit-report", help="Output folder")
    run.set_defaults(func=_run)

    stage = sub.add_parser("stage", help="Copy a batch into a local stand-in for Blob Storage.")
    stage.add_argument("--root", default="local-cloud")
    stage.add_argument("--client", required=True)
    stage.add_argument("--batch", required=True)
    stage.add_argument("--prices", required=True)
    stage.add_argument("--positions", required=True)
    stage.add_argument("--gates")
    stage.add_argument("--name", help="Strategy name (defaults to the client name)")
    stage.set_defaults(func=_stage)

    pipe = sub.add_parser("pipeline", help="Run the cloud pipeline locally for one staged batch.")
    pipe.add_argument("--root", default="local-cloud")
    pipe.add_argument("--client", required=True)
    pipe.add_argument("--batch", required=True)
    pipe.add_argument("--db", help="SQLite results file (default <root>/results.db)")
    pipe.add_argument("--openai-endpoint", help="Optional: Foundry/Azure OpenAI endpoint (uses az login)")
    pipe.add_argument("--openai-deployment", help="Model deployment name, with --openai-endpoint")
    pipe.add_argument("--azure", action="store_true",
                      help="Use the real Azure resources from AUDIT_* environment variables (after az login)")
    pipe.set_defaults(func=_pipeline)

    export = sub.add_parser("export", help="Export the SQLite results to CSV for Power BI.")
    export.add_argument("--db", default="local-cloud/results.db")
    export.add_argument("--out", default="powerbi-data")
    export.set_defaults(func=_export)

    sug = sub.add_parser("suggest-gates", help="Profile the data and (optionally) ask a Foundry model for gates.")
    sug.add_argument("--prices", required=True)
    sug.add_argument("--positions", required=True)
    sug.add_argument("--openai-endpoint", help="https://<resource>.openai.azure.com (uses az login)")
    sug.add_argument("--openai-deployment", default="gpt-4.1-mini")
    sug.add_argument("--out", default="gates.suggested.json")
    sug.set_defaults(func=_suggest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
