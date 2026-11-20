"""Azure Function: audits a batch as soon as its submit.json lands in Blob Storage.

Flow (event-driven, serverless):
    client uploads prices.csv, positions.csv, gates.json, then submit.json
      -> Event Grid sees the new submit.json blob and calls this function
      -> process_batch() runs the unchanged audit engine
      -> report.html / results.json / explanations.json go to the audit-reports container
      -> rows go to Azure SQL (audit.runs, audit.check_results, audit.explanations)
      -> logs and failures go to Application Insights

Read API for the Copilot Studio "Audit Desk" agent (azure/copilot-studio/openapi.yaml), all GET and
protected by a function key:
    /api/summary?days=7[&client=]                         counts by verdict and the most common findings
    /api/runs?days=7[&client=&verdict=&limit=]            recent runs
    /api/findings?days=7[&client=&check=&status=&limit=]  WARN/FAIL checks with explanations
    /api/runs/{client}/{batch}                            one run and all its findings

The modelaudit package is copied next to this file by azure/scripts/deploy.ps1 before publishing.
"""

import logging

import azure.functions as func

from modelaudit.cloud.pipeline import process_batch
from modelaudit.cloud.settings import azure_components
from modelaudit.cloud.store import parse_submit_path

app = func.FunctionApp()
_components = None
_reader = None


def _get_components():
    # Built once per worker and reused across invocations (SDK clients are expensive to create).
    global _components
    if _components is None:
        _components = azure_components()
    return _components


def _get_reader():
    global _reader
    if _reader is None:
        from modelaudit.cloud.settings import azure_reader

        _reader = azure_reader()
    return _reader


@app.function_name(name="AuditOnSubmit")
@app.blob_trigger(arg_name="blob", path="audit-inputs/{name}", connection="AuditStorage", source="EventGrid")
def audit_on_submit(blob: func.InputStream) -> None:
    parsed = parse_submit_path(blob.name)
    if parsed is None:  # the Event Grid filter only sends submit.json, but be safe
        logging.info("Ignoring %s (not a submit.json)", blob.name)
        return
    client, batch = parsed
    store, sink, explainer = _get_components()
    # Unexpected exceptions propagate: the run is marked failed in Application Insights, the alert
    # fires, and the platform retries. Bad client input does not raise; it is stored as verdict ERROR.
    outcome = process_batch(store, sink, explainer, client, batch)
    logging.info("Batch %s/%s finished with verdict %s", client, batch, outcome.verdict)


@app.function_name(name="RunAudit")
@app.route(route="audits", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def run_audit_http(req: func.HttpRequest) -> func.HttpResponse:
    """Same pipeline, called on demand: for Azure Data Factory / Fabric pipelines (Azure Function or Web
    activity) or for re-running a batch.  POST /api/audits?code=<function key>  {"client": "...", "batch": "..."}"""
    import json

    try:
        body = req.get_json()
        client, batch = str(body["client"]), str(body["batch"])
    except (ValueError, KeyError, TypeError):
        return func.HttpResponse('{"error": "send JSON {\\"client\\": ..., \\"batch\\": ...}"}',
                                 status_code=400, mimetype="application/json")
    store, sink, explainer = _get_components()
    try:
        outcome = process_batch(store, sink, explainer, client, batch)
    except ValueError as exc:  # invalid client/batch name
        return func.HttpResponse(json.dumps({"error": str(exc)}), status_code=400, mimetype="application/json")
    payload = {"run_id": outcome.run_id, "client": client, "batch": batch, "verdict": outcome.verdict,
               "report_uri": outcome.report_uri, "error": outcome.error}
    return func.HttpResponse(json.dumps(payload), status_code=200, mimetype="application/json")


# ---------------------------------------------------------------- read API for the Copilot Studio agent
def _json(payload, status: int = 200):
    import json

    return func.HttpResponse(json.dumps(payload, default=str), status_code=status, mimetype="application/json")


def _read(req, action):
    """Runs one read query; bad parameters become 400s with a message the agent can relay."""
    from modelaudit.cloud.reader import QueryError
    from modelaudit.cloud.store import check_name

    params = dict(req.params or {})
    try:
        for key in ("client",):
            if params.get(key):
                check_name(params[key], key)
        if params.get("check") and not params["check"].replace("_", "").isalnum():
            raise QueryError("check must be a check key such as lookahead or costs")
        for key in ("days", "limit"):
            if key in params:
                try:
                    params[key] = int(params[key])
                except ValueError as exc:
                    raise QueryError(f"{key} must be a whole number") from exc
        return _json(action(_get_reader(), params))
    except (QueryError, ValueError) as exc:
        return _json({"error": str(exc)}, 400)


@app.function_name(name="AgentSummary")
@app.route(route="summary", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def agent_summary(req: func.HttpRequest) -> func.HttpResponse:
    return _read(req, lambda r, p: r.summary(days=p.get("days", 7), client=p.get("client")))


@app.function_name(name="AgentRuns")
@app.route(route="runs", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def agent_runs(req: func.HttpRequest) -> func.HttpResponse:
    return _read(req, lambda r, p: {"runs": r.runs(days=p.get("days", 7), client=p.get("client"),
                                                   verdict=p.get("verdict"), limit=p.get("limit", 50))})


@app.function_name(name="AgentFindings")
@app.route(route="findings", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def agent_findings(req: func.HttpRequest) -> func.HttpResponse:
    return _read(req, lambda r, p: {"findings": r.findings(
        days=p.get("days", 7), client=p.get("client"), check=p.get("check"), status=p.get("status"),
        limit=p.get("limit", 50))})


@app.function_name(name="AgentRunDetail")
@app.route(route="runs/{client}/{batch}", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def agent_run_detail(req: func.HttpRequest) -> func.HttpResponse:
    from modelaudit.cloud.store import check_name

    route = dict(req.route_params or {})
    try:
        client, batch = check_name(route.get("client", ""), "client"), check_name(route.get("batch", ""), "batch")
    except ValueError as exc:
        return _json({"error": str(exc)}, 400)
    found = _get_reader().run(client, batch)
    return _json(found) if found else _json({"error": f"No audit found for {client}/{batch}"}, 404)
