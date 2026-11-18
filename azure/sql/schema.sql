-- Azure SQL schema for audit results. Safe to run more than once.
-- deploy.ps1 runs this with sqlcmd; you can also paste it into the portal's Query editor.

IF SCHEMA_ID('audit') IS NULL EXEC('CREATE SCHEMA audit');
GO

IF OBJECT_ID('audit.runs') IS NULL
CREATE TABLE audit.runs (
    run_id            CHAR(36)       NOT NULL PRIMARY KEY,
    client            NVARCHAR(64)   NOT NULL,
    batch             NVARCHAR(64)   NOT NULL,
    strategy          NVARCHAR(200)  NULL,
    verdict           VARCHAR(12)    NOT NULL,   -- PASS, CONDITIONAL, FAIL, ERROR
    gross_sharpe      FLOAT          NULL,
    net_sharpe        FLOAT          NULL,
    net_total_return  FLOAT          NULL,
    max_drawdown      FLOAT          NULL,
    n_checks          INT            NULL,
    n_fail            INT            NULL,
    n_warn            INT            NULL,
    cost_bps          FLOAT          NULL,
    n_trials          INT            NULL,
    tool_version      NVARCHAR(50)   NULL,
    inputs_sha256     NVARCHAR(MAX)  NULL,
    report_uri        NVARCHAR(500)  NULL,
    error_message     NVARCHAR(1000) NULL,
    audited_utc       DATETIMEOFFSET NOT NULL
);
GO

IF OBJECT_ID('audit.check_results') IS NULL
CREATE TABLE audit.check_results (
    run_id       CHAR(36)      NOT NULL REFERENCES audit.runs(run_id),
    check_key    VARCHAR(40)   NOT NULL,
    title        NVARCHAR(200) NULL,
    status       VARCHAR(8)    NOT NULL,          -- PASS, WARN, FAIL
    summary      NVARCHAR(MAX) NULL,
    metrics_json NVARCHAR(MAX) NULL CHECK (metrics_json IS NULL OR ISJSON(metrics_json) = 1),
    PRIMARY KEY (run_id, check_key)
);
GO

IF OBJECT_ID('audit.explanations') IS NULL
CREATE TABLE audit.explanations (
    run_id           CHAR(36)       NOT NULL REFERENCES audit.runs(run_id),
    check_key        VARCHAR(40)    NOT NULL,
    explanation      NVARCHAR(MAX)  NULL,
    suggested_action NVARCHAR(MAX)  NULL,
    model            NVARCHAR(100)  NULL,
    PRIMARY KEY (run_id, check_key)
);
GO

-- ---------- Views for Power BI and the Copilot Studio agent ----------

-- One row per run, with a date column for trend charts.
CREATE OR ALTER VIEW audit.v_runs AS
SELECT run_id, client, batch, strategy, verdict,
       CAST(audited_utc AS DATE) AS audit_date, audited_utc,
       gross_sharpe, net_sharpe, net_total_return, max_drawdown,
       n_checks, n_fail, n_warn, cost_bps, n_trials, report_uri, error_message,
       CASE WHEN verdict = 'PASS' THEN 1 ELSE 0 END AS is_pass
FROM audit.runs;
GO

-- Every WARN/FAIL with its explanation: "what failed and why".
CREATE OR ALTER VIEW audit.v_findings AS
SELECT r.client, r.batch, r.strategy, r.verdict, CAST(r.audited_utc AS DATE) AS audit_date,
       c.check_key, c.title, c.status, c.summary,
       e.explanation, e.suggested_action, e.model, r.report_uri
FROM audit.check_results c
JOIN audit.runs r ON r.run_id = c.run_id
LEFT JOIN audit.explanations e ON e.run_id = c.run_id AND e.check_key = c.check_key
WHERE c.status IN ('WARN', 'FAIL');
GO

-- Pass/warn/fail counts per check and day: "top failing rules" and trends.
CREATE OR ALTER VIEW audit.v_check_daily AS
SELECT CAST(r.audited_utc AS DATE) AS audit_date, c.check_key, c.title,
       SUM(CASE WHEN c.status = 'PASS' THEN 1 ELSE 0 END) AS n_pass,
       SUM(CASE WHEN c.status = 'WARN' THEN 1 ELSE 0 END) AS n_warn,
       SUM(CASE WHEN c.status = 'FAIL' THEN 1 ELSE 0 END) AS n_fail,
       COUNT(*) AS n_runs
FROM audit.check_results c
JOIN audit.runs r ON r.run_id = c.run_id
GROUP BY CAST(r.audited_utc AS DATE), c.check_key, c.title;
GO
