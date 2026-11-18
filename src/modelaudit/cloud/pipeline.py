"""One audit batch, end to end: read inputs -> audit -> write reports -> explain -> store results.

Used by the Azure Function (azure/function_app) and by `modelaudit pipeline` on your PC.
"""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from modelaudit.audit import run_from_files
from modelaudit.cloud.explain import Explainer
from modelaudit.cloud.records import error_record, explanation_records, run_id_for, to_records
from modelaudit.cloud.sinks import ResultSink
from modelaudit.cloud.store import INPUTS, REPORTS, SUBMIT_FILE, Store, check_name
from modelaudit.report import render_html

log = logging.getLogger("modelaudit.cloud")


class InputError(ValueError):
    """The client's files are missing or malformed. Retrying will not help; the batch is recorded as ERROR."""


@dataclass
class BatchOutcome:
    run_id: str
    client: str
    batch: str
    verdict: str
    report_uri: str | None = None
    explanations: list[dict] = field(default_factory=list)
    error: str | None = None


def _read_submit(store: Store, prefix: str) -> dict:
    raw = store.read_bytes(INPUTS, f"{prefix}/{SUBMIT_FILE}") or b"{}"
    try:
        submit = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(f"{SUBMIT_FILE} is not valid JSON: {exc}") from exc
    if not isinstance(submit, dict):
        raise InputError(f"{SUBMIT_FILE} must be a JSON object")
    return submit


def process_batch(store: Store, sink: ResultSink, explainer: Explainer, client: str, batch: str) -> BatchOutcome:
    client, batch = check_name(client, "client"), check_name(batch, "batch")
    prefix = f"{client}/{batch}"
    log.info("AUDIT_STARTED client=%s batch=%s", client, batch)
    try:
        submit = _read_submit(store, prefix)
        strategy = str(submit.get("strategy") or client)[:200]
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for name in ("prices.csv", "positions.csv", "gates.json"):
                if not store.exists(INPUTS, f"{prefix}/{name}"):
                    if name == "gates.json":
                        continue
                    raise InputError(f"Missing {name} in {INPUTS}/{prefix}/")
                paths[name] = Path(tmp) / name
                paths[name].write_bytes(store.read_bytes(INPUTS, f"{prefix}/{name}"))
            try:
                result = run_from_files(str(paths["prices.csv"]), str(paths["positions.csv"]),
                                        str(paths["gates.json"]) if "gates.json" in paths else None, strategy)
            except (ValueError, KeyError, TypeError) as exc:  # bad columns, bad gates, unparseable dates
                raise InputError(str(exc)) from exc
    except InputError as exc:
        message = str(exc)
        log.error("AUDIT_INPUT_ERROR client=%s batch=%s error=%s", client, batch, message)
        store.write_bytes(REPORTS, f"{prefix}/error.json",
                          json.dumps({"client": client, "batch": batch, "error": message}, indent=2).encode(),
                          "application/json")
        sink.write(error_record(client, batch, message), [], [])
        return BatchOutcome(run_id_for(client, batch), client, batch, "ERROR", error=message)

    data = result.to_json()
    report_uri = store.write_bytes(REPORTS, f"{prefix}/report.html", render_html(result).encode("utf-8"),
                                   "text/html; charset=utf-8")
    store.write_bytes(REPORTS, f"{prefix}/results.json",
                      json.dumps(data, indent=2, default=str).encode("utf-8"), "application/json")

    explanations = explainer.explain(data)
    store.write_bytes(REPORTS, f"{prefix}/explanations.json",
                      json.dumps({"model": explainer.model, "explanations": explanations}, indent=2).encode("utf-8"),
                      "application/json")

    run, checks = to_records(data, client, batch, report_uri)
    sink.write(run, checks, explanation_records(run["run_id"], explanations, explainer.model))
    log.info("AUDIT_COMPLETED client=%s batch=%s verdict=%s fails=%d warns=%d net_sharpe=%s",
             client, batch, run["verdict"], run["n_fail"], run["n_warn"], run["net_sharpe"])
    return BatchOutcome(run["run_id"], client, batch, run["verdict"], report_uri, explanations)
