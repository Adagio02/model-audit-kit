# Power BI dashboard: audit results

## Data source (pick one)

| Source | When | How |
|---|---|---|
| Local CSVs | No Azure yet | Run `azure\scripts\run_local_pipeline.ps1`, then in Power BI Desktop use *Get data > Text/CSV* on `local-cloud\powerbi\*.csv` |
| Azure SQL | Phase 1 deployed | *Get data > Azure SQL database*, server `<server>.database.windows.net`, database `auditdb`, sign in with your *Microsoft account* (Entra). Import the views `audit.v_runs`, `audit.v_findings`, `audit.v_check_daily` |
| Fabric Lakehouse | Phase 2 Route A | Semantic model on `audit_runs`, `audit_check_results`, `audit_explanations` (Direct Lake) |

Relationships: `runs[run_id]` 1 → * `check_results[run_id]`, and `check_results (run_id, check_key)`
→ `explanations`. In Power BI, add a calculated key column `run_id & "|" & check_key` to both tables.
The SQL views already join these, so with Azure SQL you mostly use `v_findings`.

## Measures (DAX)

```DAX
Runs = COUNTROWS ( runs )
Pass Rate = DIVIDE ( CALCULATE ( [Runs], runs[verdict] = "PASS" ), [Runs] )
Fail Rate = DIVIDE ( CALCULATE ( [Runs], runs[verdict] = "FAIL" ), [Runs] )
Error Runs = CALCULATE ( [Runs], runs[verdict] = "ERROR" )
Check Failures = CALCULATE ( COUNTROWS ( check_results ), check_results[status] = "FAIL" )
Check Fail Rate = DIVIDE ( [Check Failures], COUNTROWS ( check_results ) )
Avg Net Sharpe = AVERAGE ( runs[net_sharpe] )
Sharpe Lost To Costs = AVERAGE ( runs[gross_sharpe] ) - AVERAGE ( runs[net_sharpe] )
Pass Rate 30d =
    CALCULATE ( [Pass Rate], DATESINPERIOD ( 'Date'[Date], MAX ( 'Date'[Date] ), -30, DAY ) )
```

Add a date table (`Date = CALENDARAUTO()`, marked as a date table) related to `runs[audit_date]`
(Power Query: `Date.From([audited_utc])`).

## Page layout

1. **Overview:** cards for Runs, Pass Rate, Fail Rate and Error Runs; a stacked column of runs by
   `audit_date` and `verdict` (PASS green, CONDITIONAL amber, FAIL red, ERROR grey); a slicer on `client`.
2. **Top failing rules:** a bar chart of Check Failures by `check_key`, sorted descending, and a matrix
   of `check_key` × `status`.
3. **Findings:** a table from `v_findings` (client, batch, check, status, explanation, suggested_action)
   with `report_uri` as a *Web URL* column so each row links to its HTML report.
4. **Trends:** a line of Check Fail Rate by week per `check_key`, which shows whether clients are fixing
   look-ahead problems over time.

## Copilot in Power BI (needs F2 capacity, not trial)

Publish to the Fabric workspace, then try: *"Create a page showing which checks fail most often
and how that changed this month"* and *"Summarize the findings for client demo."* Then compare
the generated measures with yours.
