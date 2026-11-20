"""Where results go: a local SQLite file or Azure SQL Database. Same tables, same inserts.

Tables (T-SQL version in azure/sql/schema.sql):
    audit.runs          one row per audited batch, including batches that errored
    audit.check_results one row per check per run
    audit.explanations  plain-English explanations of WARN/FAIL checks (Azure OpenAI or rules)

Writes are idempotent: a run's rows are deleted and re-inserted in one transaction, so a
Function retry or a resubmitted batch never creates duplicates.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Protocol

from modelaudit.cloud.records import CHECK_COLUMNS, EXPLANATION_COLUMNS, RUN_COLUMNS

log = logging.getLogger("modelaudit.cloud")

_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, client TEXT NOT NULL, batch TEXT NOT NULL, strategy TEXT,
    verdict TEXT NOT NULL, gross_sharpe REAL, net_sharpe REAL, net_total_return REAL, max_drawdown REAL,
    n_checks INTEGER, n_fail INTEGER, n_warn INTEGER, cost_bps REAL, n_trials INTEGER,
    tool_version TEXT, inputs_sha256 TEXT, report_uri TEXT, error_message TEXT, audited_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS check_results (
    run_id TEXT NOT NULL, check_key TEXT NOT NULL, title TEXT, status TEXT NOT NULL, summary TEXT,
    metrics_json TEXT, PRIMARY KEY (run_id, check_key));
CREATE TABLE IF NOT EXISTS explanations (
    run_id TEXT NOT NULL, check_key TEXT NOT NULL, explanation TEXT, suggested_action TEXT, model TEXT,
    PRIMARY KEY (run_id, check_key));

-- Views: the same names and columns as the audit.v_* views in azure/sql/schema.sql.
DROP VIEW IF EXISTS v_runs;
CREATE VIEW v_runs AS
SELECT run_id, client, batch, strategy, verdict, substr(audited_utc, 1, 10) AS audit_date, audited_utc,
       gross_sharpe, net_sharpe, net_total_return, max_drawdown, n_checks, n_fail, n_warn, cost_bps, n_trials,
       report_uri, error_message, CASE WHEN verdict = 'PASS' THEN 1 ELSE 0 END AS is_pass
FROM runs;
DROP VIEW IF EXISTS v_findings;
CREATE VIEW v_findings AS
SELECT r.run_id, r.client, r.batch, r.strategy, r.verdict, substr(r.audited_utc, 1, 10) AS audit_date,
       c.check_key, c.title, c.status, c.summary, e.explanation, e.suggested_action, e.model, r.report_uri
FROM check_results c
JOIN runs r ON r.run_id = c.run_id
LEFT JOIN explanations e ON e.run_id = c.run_id AND e.check_key = c.check_key
WHERE c.status IN ('WARN', 'FAIL');
DROP VIEW IF EXISTS v_check_daily;
CREATE VIEW v_check_daily AS
SELECT substr(r.audited_utc, 1, 10) AS audit_date, c.check_key, c.title,
       SUM(CASE WHEN c.status = 'PASS' THEN 1 ELSE 0 END) AS n_pass,
       SUM(CASE WHEN c.status = 'WARN' THEN 1 ELSE 0 END) AS n_warn,
       SUM(CASE WHEN c.status = 'FAIL' THEN 1 ELSE 0 END) AS n_fail,
       COUNT(*) AS n_runs
FROM check_results c JOIN runs r ON r.run_id = c.run_id
GROUP BY substr(r.audited_utc, 1, 10), c.check_key, c.title;
DROP VIEW IF EXISTS v_run_metrics;
CREATE VIEW v_run_metrics AS
SELECT r.run_id, r.client, r.batch, r.verdict, substr(r.audited_utc, 1, 10) AS audit_date,
    MAX(CASE WHEN c.check_key = 'lookahead' THEN json_extract(c.metrics_json, '$.sharpe_by_delay."1"') END) AS sharpe_delay_1,
    MAX(CASE WHEN c.check_key = 'lookahead' THEN json_extract(c.metrics_json, '$.sharpe_by_delay."2"') END) AS sharpe_delay_2,
    MAX(CASE WHEN c.check_key = 'costs' THEN json_extract(c.metrics_json, '$.breakeven_cost_bps') END) AS breakeven_cost_bps,
    MAX(CASE WHEN c.check_key = 'costs' THEN json_extract(c.metrics_json, '$.annual_turnover') END) AS annual_turnover,
    MAX(CASE WHEN c.check_key = 'walk_forward' THEN json_extract(c.metrics_json, '$.positive_fraction') END) AS positive_window_fraction,
    MAX(CASE WHEN c.check_key = 'deflated_sharpe' THEN json_extract(c.metrics_json, '$.probability_real') END) AS probability_real,
    MAX(CASE WHEN c.check_key = 'deflated_sharpe' THEN json_extract(c.metrics_json, '$.sharpe_ci95_low') END) AS sharpe_ci95_low,
    MAX(CASE WHEN c.check_key = 'deflated_sharpe' THEN json_extract(c.metrics_json, '$.sharpe_ci95_high') END) AS sharpe_ci95_high,
    MAX(CASE WHEN c.check_key = 'exposure' THEN json_extract(c.metrics_json, '$.max_gross_leverage') END) AS max_gross_leverage,
    MAX(CASE WHEN c.check_key = 'exposure' THEN json_extract(c.metrics_json, '$.max_position_weight') END) AS max_position_weight,
    MAX(CASE WHEN c.check_key = 'exposure' THEN json_extract(c.metrics_json, '$.top5_names_pnl_share') END) AS top5_names_pnl_share,
    MAX(CASE WHEN c.check_key = 'data_integrity' THEN json_extract(c.metrics_json, '$.missing_fraction') END) AS missing_fraction,
    MAX(CASE WHEN c.check_key = 'benchmark' THEN json_extract(c.metrics_json, '$.information_ratio') END) AS information_ratio
FROM runs r JOIN check_results c ON c.run_id = r.run_id
GROUP BY r.run_id, r.client, r.batch, r.verdict, r.audited_utc;
"""


class ResultSink(Protocol):
    def write(self, run: dict, checks: list[dict], explanations: list[dict]) -> None: ...


def _insert(table: str, columns: list[str]) -> str:
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})"


class SqlSink:
    """Shared logic for any DB-API driver that uses '?' placeholders (sqlite3, pyodbc)."""

    schema = ""  # "" for SQLite, "audit." for Azure SQL

    def connect(self):
        raise NotImplementedError

    def write(self, run: dict, checks: list[dict], explanations: list[dict]) -> None:
        tables = [f"{self.schema}{t}" for t in ("explanations", "check_results", "runs")]
        conn = self.connect()
        try:
            cur = conn.cursor()
            for table in tables:
                cur.execute(f"DELETE FROM {table} WHERE run_id = ?", (run["run_id"],))
            cur.execute(_insert(tables[2], RUN_COLUMNS), [run[c] for c in RUN_COLUMNS])
            if checks:
                cur.executemany(_insert(tables[1], CHECK_COLUMNS), [[r[c] for c in CHECK_COLUMNS] for r in checks])
            if explanations:
                cur.executemany(_insert(tables[0], EXPLANATION_COLUMNS),
                                [[r[c] for c in EXPLANATION_COLUMNS] for r in explanations])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class SqliteSink(SqlSink):
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(_SQLITE_DDL)

    def connect(self):
        return sqlite3.connect(self.path)


class AzureSqlSink(SqlSink):
    """Azure SQL Database with Microsoft Entra authentication, through Microsoft's mssql-python
    driver (it bundles its own ODBC driver, so nothing extra is needed on the Function host).

    authentication:
        ActiveDirectoryMSI      in Azure: the Function's managed identity (no SQL password anywhere)
        ActiveDirectoryDefault  on your PC: uses `az login`

    The free-offer database is serverless and auto-pauses; the first connection after a pause
    can fail while it resumes (about a minute), so connecting is retried.
    """

    schema = "audit."

    def __init__(self, server: str, database: str, authentication: str = "ActiveDirectoryMSI"):
        self.conn_str = (f"Server=tcp:{server},1433;Database={database};Encrypt=yes;"
                         f"TrustServerCertificate=no;ConnectRetryCount=3;ConnectRetryInterval=10;Authentication={authentication}")

    def connect(self, attempts: int = 4):
        import mssql_python

        for attempt in range(1, attempts + 1):
            try:
                return mssql_python.connect(self.conn_str, timeout=60)
            except mssql_python.Error as exc:
                if attempt == attempts:
                    raise
                log.warning("Azure SQL connect failed (attempt %d, database may be resuming): %s", attempt, exc)
                time.sleep(15 * attempt)


class MemorySink:
    """Keeps rows in memory, keyed by run_id (idempotent like the SQL sinks).
    Used by the Fabric notebook, which then writes them to Lakehouse Delta tables with Spark."""

    def __init__(self):
        self.runs, self.checks, self.explanations = {}, {}, {}

    def write(self, run: dict, checks: list[dict], explanations: list[dict]) -> None:
        self.runs[run["run_id"]] = run
        self.checks[run["run_id"]] = list(checks)
        self.explanations[run["run_id"]] = list(explanations)

    def tables(self) -> dict[str, list[dict]]:
        return {"runs": list(self.runs.values()),
                "check_results": [r for rows in self.checks.values() for r in rows],
                "explanations": [r for rows in self.explanations.values() for r in rows]}
