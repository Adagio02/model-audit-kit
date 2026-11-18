"""Azure Function: audits a batch as soon as its submit.json lands in Blob Storage.

Flow (event-driven, serverless):
    client uploads prices.csv, positions.csv, gates.json, then submit.json
      -> Event Grid sees the new submit.json blob and calls this function
      -> process_batch() runs the unchanged audit engine
      -> report.html / results.json / explanations.json go to the audit-reports container
      -> rows go to Azure SQL (audit.runs, audit.check_results, audit.explanations)
      -> logs and failures go to Application Insights

The modelaudit package is copied next to this file by azure/scripts/deploy.ps1 before publishing.
"""

import logging

import azure.functions as func

from modelaudit.cloud.pipeline import process_batch
from modelaudit.cloud.settings import azure_components
from modelaudit.cloud.store import parse_submit_path

app = func.FunctionApp()
_components = None


def _get_components():
    # Built once per worker and reused across invocations (SDK clients are expensive to create).
    global _components
    if _components is None:
        _components = azure_components()
    return _components


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
