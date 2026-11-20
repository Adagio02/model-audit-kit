# Power BI dashboard: audit results

Everything you type is in this folder, so the dashboard can be rebuilt the same way each time:

| File | What it is |
|---|---|
| `queries.pq` | Power Query (M) for each table, for Azure SQL and for the local CSVs |
| `measures.dax` | All measures, plus the date table |
| `theme.json` | Colours that match the HTML report (PASS green, CONDITIONAL amber, FAIL red, ERROR grey) |

## 1. Data source

Both sources give the same four tables with the same columns, so you can build the report on your PC first
and switch it to Azure later without changing anything else.

| Source | When | How |
|---|---|---|
| Local CSVs | No Azure yet | Run `azure\scripts\run_local_pipeline.ps1`. It writes `local-cloud\powerbi\v_*.csv`. Create a text parameter `CsvFolder` with that folder's full path and use the CSV queries in `queries.pq` |
| Azure SQL | After `deploy.ps1` | Create the parameters `SqlServer` (`<server>.database.windows.net`) and `SqlDatabase` (`auditdb`) and use the SQL queries. Sign in with *Microsoft account* (Entra). For someone else's account, deploy with `-ReaderLogin their@tenant.onmicrosoft.com`; it can read only the four views |
| Fabric Lakehouse | Phase 2 Route A | A Direct Lake semantic model on `audit_runs`, `audit_check_results`, `audit_explanations` |

Tables (name each query like this):

| Query | View | One row per |
|---|---|---|
| `runs` | `v_runs` | audit run (client + batch), with verdict and headline numbers |
| `findings` | `v_findings` | flagged check (WARN/FAIL), with explanation and suggested action |
| `check_daily` | `v_check_daily` | check per day, with pass/warn/fail counts |
| `run_metrics` | `v_run_metrics` | run, with the key number from each check (delay Sharpe, break-even cost, leverage, ...) |

## 2. Model

- Relationships: `runs[run_id]` 1 → * `findings[run_id]`, and `runs[run_id]` 1 → 1 `run_metrics[run_id]`.
  `check_daily` is already aggregated, so it relates to the date table only.
- Date table: the last lines of `measures.dax`. Mark it as a date table and relate `'Date'[Date]` to each
  table's `audit_date`.
- Measures: everything else in `measures.dax`.
- Theme: *View > Themes > Browse for themes*, choose `theme.json`.
- Format `runs[report_uri]` and `findings[report_uri]` as *Web URL* (*Column tools > Data category*) so each
  row links to its HTML report.

## 3. Pages

1. **Overview:** cards for Runs, Pass Rate, Fail Rate and Error Runs. A stacked column chart of Runs by
   `audit_date` and `verdict`. A slicer on `client`. A card for *Pass Rate Change vs Prior 30d*.
2. **Top failing checks:** a bar chart of Failures by `findings[check_key]`, sorted descending, and a matrix
   of `check_key` × `status`.
3. **Findings:** a table of `findings` (client, batch, check, status, explanation, suggested_action,
   report_uri). Use *Verdict Colour* as the background of the verdict column.
4. **Run metrics:** a scatter of `run_metrics[sharpe_delay_1]` (x) against `sharpe_delay_2` (y). Leaky
   strategies sit far below the diagonal, which makes the look-ahead check easy to explain to a client. Add
   a table of break-even cost, maximum gross leverage and the share of P&L from the top 5 names.
5. **Trends:** a line of Check Fail Rate by week for each `check_daily[check_key]`, which shows whether clients
   are fixing look-ahead problems over time.

## 4. Publish and refresh

Publish to a workspace (*Home > Publish*). With Azure SQL, set the dataset's credentials to *OAuth2* in the
service, then schedule a refresh (daily is plenty). The CSV route is for building on your PC only, because
the service can't refresh files on your PC without a gateway.

## Copilot in Power BI (needs F2 capacity, not trial)

Publish to the Fabric workspace, then try: *"Create a page showing which checks fail most often and how that
changed this month"* and *"Summarize the findings for client demo."* Compare the measures it generates with
the ones in `measures.dax`.
