# Copilot Studio agent: "Audit Desk"

An agent that answers questions such as *"What failed validation yesterday?"* in plain English,
using the audit results in Azure SQL. Copilot Studio has a 30-day trial at aka.ms/TryCopilotStudio;
it needs a work or school account.

There are two ways to give the agent the data. **Route A (the API) is recommended**: the numbers come
from fixed, tested queries, so the agent can't miscount or invent them. Route B (SQL knowledge) is
quicker to set up but answers depend on how well the model writes queries.

| | Route A: Audit Desk API (tool) | Route B: Azure SQL knowledge |
|---|---|---|
| How | 4 read-only HTTP endpoints in the Function App, described by `openapi.yaml` | Copilot Studio reads the `audit.v_*` views |
| Answers | Exact: counts and lists come from tested code (`src/modelaudit/cloud/reader.py`) | Generated: the model chooses what to read |
| Security | Function key in a header; parameters validated; at most 200 rows per call | Read-only SQL user on the four views |
| Works offline in tests | Yes (`tests/test_cloud.py::test_agent_http_endpoints`) | No |

## Route A: the Audit Desk API (recommended)

### 1. Deploy and get the connection details

Run `azure\scripts\deploy.ps1` (it's safe to re-run). At the end it prints the API address and writes
`azure\copilot-studio\openapi.generated.yaml`, which is the spec with your Function App's host name
filled in. The file is git-ignored. Get the function key with:

    az functionapp keys list -g rg-model-audit -n <function-app> --query functionKeys.default -o tsv

Test the API before you build the agent (PowerShell):

    $h = @{ "x-functions-key" = "<key>" }
    Invoke-RestMethod "https://<host>/api/summary?days=31" -Headers $h
    Invoke-RestMethod "https://<host>/api/findings?check=lookahead&days=31" -Headers $h

| Endpoint | Answers |
|---|---|
| `GET /api/summary?days=7[&client=]` | Runs by verdict, pass rate, most common findings |
| `GET /api/runs?days=7[&client=&verdict=&limit=]` | Which batches were audited, newest first |
| `GET /api/findings?days=7[&client=&check=&status=&limit=]` | Flagged checks with explanation and suggested action |
| `GET /api/runs/{client}/{batch}` | One run with all its findings (404 if there's no such run) |

### 2. Create the agent

At copilotstudio.microsoft.com go to *Create > New agent*, name it **Audit Desk**, and paste the text of
[agent-instructions.md](agent-instructions.md) into *Instructions*. Turn off *Use general knowledge* so it
answers only from the tool.

### 3. Add the API as a tool

*Tools > Add a tool > New tool > REST API*, then upload `openapi.generated.yaml`. Choose **API key**
authentication, with the key sent in the **header** `x-functions-key`, and paste the function key when you
create the connection. Copilot Studio lists the four operations (GetAuditSummary, ListAuditRuns,
ListAuditFindings, GetAuditRun). Keep all four. Their descriptions in the spec already tell the agent when to
use each one.

If your tenant doesn't offer the REST API tool, create a **custom connector** from the same file in
Power Apps (*Custom connectors > Import an OpenAPI file*), then add it under *Tools > Connector*.
Menu names in Copilot Studio change often; the file and the key are what matter.

### 4. Optional: let the agent re-run a batch

Add an *Agent flow* tool that calls `POST https://<host>/api/audits` with the header `x-functions-key`
and the body `{"client": "...", "batch": "..."}` (the `RunAudit` function). Make the flow ask for
confirmation first, because a re-run replaces that batch's results.

## Route B: Azure SQL knowledge

1. Give the agent's account read-only access to the four views:

       powershell -ExecutionPolicy Bypass -File .\azure\scripts\deploy.ps1 -ResourceGroup rg-model-audit -ReaderLogin you@yourtenant.onmicrosoft.com

   (This runs `azure/sql/grant_agent_reader.sql`. You can also paste it into the portal's Query editor,
   replacing `$(READER_LOGIN)`.)
2. Create the agent as in step 2 above, then *Knowledge > Add > Azure SQL*: server
   `<server>.database.windows.net`, database `auditdb`, sign in with Microsoft Entra, and select
   `audit.v_runs`, `audit.v_findings`, `audit.v_check_daily` and `audit.v_run_metrics`.
3. Add a description to each column, for example *verdict: PASS, CONDITIONAL, FAIL or ERROR*. Descriptions
   noticeably improve answers.

**Fabric alternative (needs F2):** create a *Fabric data agent* on the Lakehouse tables with the same
instructions, publish it, and add it in Copilot Studio under *Tools/Agents > Microsoft Fabric*.

## Test it

[evaluation.csv](evaluation.csv) has 10 test questions. For each one it lists the tool and parameters the
agent should use and the SQL that gives the right answer. It includes two questions the agent must
**refuse or answer with "no results"** (investment advice, an unknown client). Run all 10 after every
change to the instructions or the tool, and write down what changed.

## Security notes

- The API is read-only except `RunAudit`, and every endpoint needs the function key. Rotate it in the
  portal (*Function App > App keys*) if it's ever shared.
- Parameters are validated and bound, never pasted into SQL; a call returns at most 200 rows.
- The agent sees audit summaries and explanations only, never the client's price or position files.
