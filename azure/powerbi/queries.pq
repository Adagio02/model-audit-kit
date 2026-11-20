// Power Query (M) for the audit dashboard. In Power BI Desktop: Home > Transform data >
// New Source > Blank Query > Advanced Editor, paste ONE query, and name it as shown.
// Create the two text parameters first (Home > Manage Parameters):
//   SqlServer   = <server>.database.windows.net
//   SqlDatabase = auditdb
// For the local CSV route, use the "CSV" versions at the bottom instead and set the CsvFolder parameter
// to the full path of local-cloud\powerbi (created by azure\scripts\run_local_pipeline.ps1).

// ---------------------------------------------------------------- Azure SQL route
// Query name: runs
let
    Source = Sql.Database(SqlServer, SqlDatabase),
    Runs = Source{[Schema = "audit", Item = "v_runs"]}[Data],
    Typed = Table.TransformColumnTypes(Runs, {{"audit_date", type date}})
in
    Typed

// Query name: findings
let
    Source = Sql.Database(SqlServer, SqlDatabase),
    Findings = Source{[Schema = "audit", Item = "v_findings"]}[Data],
    Typed = Table.TransformColumnTypes(Findings, {{"audit_date", type date}})
in
    Typed

// Query name: check_daily
let
    Source = Sql.Database(SqlServer, SqlDatabase),
    Daily = Source{[Schema = "audit", Item = "v_check_daily"]}[Data],
    Typed = Table.TransformColumnTypes(Daily, {{"audit_date", type date}})
in
    Typed

// Query name: run_metrics
let
    Source = Sql.Database(SqlServer, SqlDatabase),
    Metrics = Source{[Schema = "audit", Item = "v_run_metrics"]}[Data],
    Typed = Table.TransformColumnTypes(Metrics, {{"audit_date", type date}})
in
    Typed

// ---------------------------------------------------------------- local CSV route (no Azure)
// Same query names and columns, so the report works unchanged when you switch to Azure SQL later.
// Query name: runs   (repeat with v_findings.csv -> findings, v_check_daily.csv -> check_daily,
//                     v_run_metrics.csv -> run_metrics)
let
    Source = Csv.Document(File.Contents(CsvFolder & "\v_runs.csv"), [Delimiter = ",", Encoding = 65001,
        QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {{"audit_date", type date}, {"net_sharpe", type number},
        {"gross_sharpe", type number}, {"max_drawdown", type number}, {"n_fail", Int64.Type},
        {"n_warn", Int64.Type}, {"is_pass", Int64.Type}}, "en-US")
in
    Typed
