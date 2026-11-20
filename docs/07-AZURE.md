# Running the audit on Azure: hands-on plan

This plan puts the Model Audit Kit on Azure in three phases. The audit engine (`src/modelaudit/checks.py`)
doesn't change. Everything around it moves to Azure one piece at a time, and each phase ends with
something that works on its own and can be demonstrated.

```
 client / you                    Azure (one resource group)                          reporting
 ------------   upload    +---------------------------+   Event Grid   +------------------------+
 prices.csv  ----------->  | Storage (Data Lake Gen2)  | ------------> | Function App (Flex)    |
 positions.csv            | audit-inputs/<c>/<b>/...  |  submit.json   | process_batch():       |
 gates.json               |                           | <------------ |  audit -> report ->    |
 submit.json (last)       | audit-reports/<c>/<b>/... |  report.html   |  explain -> store      |
                          +---------------------------+                +-----------+------------+
                                                         managed identity |  Key Vault ref |
                          +---------------------------+   +-----------------+   +-----v---------+
                          | Azure SQL (free offer)    | <-+                     | Foundry model |
                          | audit.runs / check_results|                         | (explanations)|
                          | audit.v_findings ...      | ---> Power BI / Fabric / Copilot Studio
                          +---------------------------+
             Application Insights + Log Analytics: logs, failures, alert email; budget alert
```

## Before you start (30 minutes)

1. **Account.** Azure for Students gives you $100 of credit with no card. Otherwise use the
   standard free account. If this is for an employer, use their tenant, never yours, for client data.
2. **Tools** (PowerShell):
   `winget install Microsoft.AzureCLI`, `winget install Microsoft.Azure.FunctionsCoreTools`,
   then `az login` and `az bicep install`.
3. **Python environment with the Azure extras:**
   `powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Azure`
4. **Try the whole pipeline locally first, with no Azure involved:**
   `powershell -ExecutionPolicy Bypass -File .\azure\scripts\run_local_pipeline.ps1`.
   It runs the same `process_batch()` code the Function will run. A folder stands in for Blob
   Storage and SQLite stands in for Azure SQL.

## Phase 1: storage and execution on Azure (week 1-2)

| Step | Command / place | What you learn |
|---|---|---|
| Deploy everything | `.\azure\scripts\deploy.ps1 -ResourceGroup rg-model-audit -AlertEmail you@x.com` | Bicep (infrastructure as code), resource groups, RBAC |
| Submit a batch | `.\azure\scripts\submit_batch.ps1 -StorageAccount <name> -Client demo -Batch leaky_momentum -Prices demo\data\prices.csv -Positions demo\data\positions_leaky_momentum.csv -Gates demo\gates.json -Wait` | Blob Storage, Event Grid, serverless triggers |
| Watch it run | Portal > Function App > *Monitor*, or Application Insights > *Logs*: `traces \| where message startswith "AUDIT_"` | Application Insights, KQL |
| Query results | Portal > SQL database > *Query editor*: `SELECT * FROM audit.v_findings` | Azure SQL, Entra-only auth |
| Call the agent API | `Invoke-RestMethod "https://<host>/api/summary?days=7" -Headers @{"x-functions-key"="<key>"}` (deploy.ps1 prints the address) | HTTP-triggered Functions, function keys |
| Break it on purpose | Upload a positions.csv with a wrong column name | The run is stored as `ERROR` and the alert email arrives within about 15 minutes |
| See the secret flow | Portal > Function App > *Environment variables* > `AZURE_OPENAI_API_KEY` shows a green "Key vault Reference" tick | Key Vault references, managed identity |

**How the security is set up:** the storage account has
shared-key access turned off, and the SQL server allows Microsoft Entra sign-in only. The Function
uses its **managed identity** for Blob Storage and SQL, so there's no connection-string password.
The Foundry API key is written into **Key Vault** by Bicep and read by the app through a Key
Vault reference, so no person ever handles it. Client inputs are deleted after 30 days by a
lifecycle rule, which matches `templates/CLIENT-DATA-SPEC.md`.

## Phase 2: orchestrate and report (week 3-4)

- **Fabric (recommended)** or **Azure Data Factory**: follow `azure/fabric/README.md`. Fabric
  uses `azure/fabric/audit_notebook.py`, which calls the same pipeline with a `MemorySink` and Delta
  tables. ADF calls the `RunAudit` HTTP function.
- **Power BI**: follow `azure/powerbi/README.md` (pass/fail rates, top failing checks, run metrics, trends).
  The queries (`queries.pq`), measures (`measures.dax`) and theme (`theme.json`) are in that folder. Build it
  first from the local CSVs, then switch the queries to Azure SQL: the tables and columns are the same.

## Phase 3: Copilot and AI (week 5-6)

| Tool | Where | Exercise |
|---|---|---|
| GitHub Copilot | VS Code, this repo | Move `azure/copilot-instructions.md` to `.github/copilot-instructions.md` (GitHub Copilot reads it automatically) so it knows the project rules. Ask it to *"add a check that flags strategies whose gross exposure exceeds 2x"* and review its change against the rules |
| Microsoft Foundry | Deployed by Bicep | 1) The Function explains every WARN/FAIL in plain English (`cloud/explain.py`), and you can see the text in `explanations.json` and `audit.v_findings`. 2) Gate suggestions: `modelaudit suggest-gates --prices ... --positions ... --openai-endpoint https://<res>.openai.azure.com` |
| Copilot in Fabric | Pipelines, Dataflows, Power BI (needs paid F2) | Prompts in `azure/fabric/README.md` and `azure/powerbi/README.md` |
| Copilot Studio | copilotstudio.microsoft.com (30-day trial) | The "Audit Desk" agent in `azure/copilot-studio/README.md` answers *"what failed validation yesterday?"*. It calls the Function App's read-only Audit Desk API (`/api/summary`, `/api/runs`, `/api/findings`, `/api/runs/{client}/{batch}`), described by `azure/copilot-studio/openapi.yaml`, and is tested against the 10 questions in `azure/copilot-studio/evaluation.csv` |

How the AI is kept safe here: the model sees only the audit's summary numbers, never the client's
files. Its output must explain exactly the flagged checks, or it's replaced by rule-based text. An
outage never breaks an audit, because it falls back to the rules. Gate suggestions are bounded,
can't loosen the look-ahead tests, and a human approves them.

## Costs and how to keep them near zero

| Service | Expected cost for this project |
|---|---|
| Functions Flex Consumption | Usually $0: there's a monthly free grant and audits run for seconds |
| Blob Storage, Event Grid, Key Vault | A few cents a month |
| Azure SQL free offer | $0. It pauses when the monthly free amount runs out (`AutoPause`), and it's never billed |
| Log Analytics / App Insights | $0-1, with a 1 GB/day cap set in Bicep |
| Failure alert rule | About $1-2 a month while it exists (log alerts are billed per rule) |
| Foundry model | Cents: each explanation is about 2k tokens |
| Fabric F2 (Phase 3 Copilot only) | Billed per hour while running, so **pause it** in the portal after each session |

- The budget alert from Bicep emails you at 50% and 90% of `-MonthlyBudget`, and when spend is forecast to reach 100%.
- When you're finished: `.\azure\scripts\teardown.ps1 -ResourceGroup rg-model-audit`.
- Check *Cost Management > Cost analysis* weekly while you're learning.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `AuthorizationPermissionMismatch` on upload | New role assignments take up to 10 minutes. Wait and retry |
| Nothing happens after upload | Check that the Event Grid subscription exists (*Storage account > Events*), that submit.json was uploaded **last** and under `audit-inputs/<client>/<batch>/` |
| `blobs_extension` key missing in deploy | The function host hasn't started yet. Re-run `deploy.ps1` (it's idempotent) |
| SQL login timeout on the first run of the day | The free database was paused and is resuming. The code retries for about 2 minutes |
| Bicep: model not available | Pass `-FoundryLocation swedencentral` (or another region listed for the model), or `-SkipFoundry` |
| Key Vault reference shows an error | Restart the Function App once the role assignment has propagated |
