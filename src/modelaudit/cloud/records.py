"""Turns an audit's results.json into flat table rows for SQL and Power BI."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

_NAMESPACE = uuid.UUID("6b1f3c1e-7a51-4d1e-9a3c-2f6f0d3b8a10")


def run_id_for(client: str, batch: str) -> str:
    """Same client + batch always gives the same id, so a retried or resubmitted batch replaces its rows."""
    return str(uuid.uuid5(_NAMESPACE, f"{client}/{batch}"))


def to_records(result: dict, client: str, batch: str, report_uri: str) -> tuple[dict, list[dict]]:
    run_id = run_id_for(client, batch)
    statuses = [c["status"] for c in result["checks"]]
    head = result["headline"]
    run = {
        "run_id": run_id,
        "client": client,
        "batch": batch,
        "strategy": result["strategy"],
        "verdict": result["verdict"],
        "gross_sharpe": head["gross_sharpe"],
        "net_sharpe": head["net_sharpe"],
        "net_total_return": head["net_total_return"],
        "max_drawdown": head["max_drawdown"],
        "n_checks": len(statuses),
        "n_fail": statuses.count("FAIL"),
        "n_warn": statuses.count("WARN"),
        "cost_bps": result["gates"]["cost_bps"],
        "n_trials": result["gates"]["n_trials"],
        "tool_version": result["manifest"]["tool"],
        "inputs_sha256": json.dumps(result["manifest"]["inputs_sha256"], sort_keys=True),
        "report_uri": report_uri,
        "error_message": None,
        "audited_utc": result["manifest"]["generated_utc"],
    }
    checks = [{
        "run_id": run_id,
        "check_key": c["key"],
        "title": c["title"],
        "status": c["status"],
        "summary": c["summary"],
        "metrics_json": json.dumps(c["metrics"], default=str, sort_keys=True),
    } for c in result["checks"]]
    return run, checks


def error_record(client: str, batch: str, message: str) -> dict:
    """A run row for a batch that could not be audited (bad or missing input), so it shows in reporting."""
    return {
        "run_id": run_id_for(client, batch), "client": client, "batch": batch, "strategy": None,
        "verdict": "ERROR", "gross_sharpe": None, "net_sharpe": None, "net_total_return": None,
        "max_drawdown": None, "n_checks": 0, "n_fail": 0, "n_warn": 0, "cost_bps": None, "n_trials": None,
        "tool_version": None, "inputs_sha256": None, "report_uri": None, "error_message": message[:1000],
        "audited_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def explanation_records(run_id: str, explanations: list[dict], model: str) -> list[dict]:
    return [{
        "run_id": run_id,
        "check_key": e["check_key"],
        "explanation": e["explanation"],
        "suggested_action": e["suggested_action"],
        "model": model,
    } for e in explanations]


RUN_COLUMNS = list(error_record("a", "b", "").keys())
CHECK_COLUMNS = ["run_id", "check_key", "title", "status", "summary", "metrics_json"]
EXPLANATION_COLUMNS = ["run_id", "check_key", "explanation", "suggested_action", "model"]
