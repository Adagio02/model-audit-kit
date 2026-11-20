"""Read-only queries over audit results, for the Copilot Studio agent's API and for reporting.

The same questions run against the local SQLite file (development, tests) and Azure SQL (in the
Function App). Both expose the same views:

    v_runs         one row per run (with audit_date)
    v_findings     every WARN/FAIL with its explanation and suggested action
    v_check_daily  pass/warn/fail counts per check and day
    v_run_metrics  one row per run with the headline metric of each check (for Power BI)

Every query is parameterised; user text never becomes SQL. Answers are capped in size so an agent
cannot pull the whole database in one call.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

VERDICTS = {"PASS", "CONDITIONAL", "FAIL", "ERROR"}
STATUSES = {"WARN", "FAIL"}
MAX_ROWS = 200

RUN_FIELDS = ["client", "batch", "strategy", "verdict", "audit_date", "gross_sharpe", "net_sharpe",
              "net_total_return", "max_drawdown", "n_fail", "n_warn", "report_uri", "error_message"]
FINDING_FIELDS = ["client", "batch", "strategy", "verdict", "audit_date", "check_key", "title", "status",
                  "summary", "explanation", "suggested_action", "report_uri"]


class QueryError(ValueError):
    """A request parameter is out of range or not allowed (answered with HTTP 400)."""


def since_date(days: int, today: datetime | None = None) -> str:
    """'Last N days' including today, as an ISO date string comparable to audit_date."""
    if not 1 <= int(days) <= 366:
        raise QueryError("days must be between 1 and 366")
    today = today or datetime.now(UTC)
    return (today.date() - timedelta(days=int(days) - 1)).isoformat()


class ResultReader:
    """Shared query logic. Subclasses supply connect(), the schema prefix and the row-limit syntax."""

    schema = ""

    def connect(self):
        raise NotImplementedError

    def _select(self, fields: list[str], view: str, where: list[str], params: list, order: str,
                limit: int) -> str:
        raise NotImplementedError

    def _rows(self, sql: str, params: list) -> list[dict]:
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            names = [d[0] for d in cur.description]
            return [{n: (v.isoformat() if hasattr(v, "isoformat") else v) for n, v in zip(names, row)}
                    for row in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def _limit(limit: int) -> int:
        if not 1 <= int(limit) <= MAX_ROWS:
            raise QueryError(f"limit must be between 1 and {MAX_ROWS}")
        return int(limit)

    def runs(self, days: int = 7, client: str | None = None, verdict: str | None = None,
             limit: int = 50) -> list[dict]:
        where, params = ["audit_date >= ?"], [since_date(days)]
        if client:
            where.append("client = ?")
            params.append(client)
        if verdict:
            if verdict.upper() not in VERDICTS:
                raise QueryError(f"verdict must be one of {sorted(VERDICTS)}")
            where.append("verdict = ?")
            params.append(verdict.upper())
        sql = self._select(RUN_FIELDS, "v_runs", where, params, "audited_utc DESC", self._limit(limit))
        return self._rows(sql, params)

    def findings(self, days: int = 7, client: str | None = None, check: str | None = None,
                 status: str | None = None, limit: int = 50) -> list[dict]:
        where, params = ["audit_date >= ?"], [since_date(days)]
        if client:
            where.append("client = ?")
            params.append(client)
        if check:
            where.append("check_key = ?")
            params.append(check)
        if status:
            if status.upper() not in STATUSES:
                raise QueryError("status must be WARN or FAIL")
            where.append("status = ?")
            params.append(status.upper())
        sql = self._select(FINDING_FIELDS, "v_findings", where, params,
                           "audit_date DESC, client, batch, status, check_key", self._limit(limit))
        return self._rows(sql, params)

    def run(self, client: str, batch: str) -> dict | None:
        params = [client, batch]
        rows = self._rows(self._select(RUN_FIELDS, "v_runs", ["client = ?", "batch = ?"], params,
                                       "audited_utc DESC", 1), params)
        if not rows:
            return None
        found = rows[0]
        found["findings"] = self._rows(
            self._select(FINDING_FIELDS, "v_findings", ["client = ?", "batch = ?"], params,
                         "status, check_key", MAX_ROWS), params)
        return found

    def summary(self, days: int = 7, client: str | None = None) -> dict:
        since = since_date(days)
        where, params = ["audit_date >= ?"], [since]
        if client:
            where.append("client = ?")
            params.append(client)
        clause = " AND ".join(where)
        verdicts = self._rows(f"SELECT verdict, COUNT(*) AS runs FROM {self.schema}v_runs WHERE {clause} "
                              "GROUP BY verdict", list(params))
        failing = self._rows(f"SELECT check_key, status, COUNT(*) AS findings FROM {self.schema}v_findings "
                             f"WHERE {clause} GROUP BY check_key, status", list(params))
        counts = {v: 0 for v in sorted(VERDICTS)}
        counts.update({r["verdict"]: int(r["runs"]) for r in verdicts})
        total = sum(counts.values())
        failing.sort(key=lambda r: (-int(r["findings"]), r["status"] != "FAIL", r["check_key"]))
        return {"since": since, "days": int(days), "client": client, "runs": total, "by_verdict": counts,
                "pass_rate": round(counts["PASS"] / total, 3) if total else None,
                "top_findings": failing[:10]}


class SqliteReader(ResultReader):
    def __init__(self, path):
        import sqlite3

        from modelaudit.cloud.sinks import SqliteSink

        SqliteSink(path)  # creates the tables and views if this is a new file
        self.path = str(path)
        self._sqlite3 = sqlite3

    def connect(self):
        return self._sqlite3.connect(self.path)

    def _select(self, fields, view, where, params, order, limit):
        return (f"SELECT {', '.join(fields)} FROM {view} WHERE {' AND '.join(where)} "
                f"ORDER BY {order} LIMIT {int(limit)}")


class AzureSqlReader(ResultReader):
    """Reads the audit.v_* views with the Function's managed identity (or az login on your PC)."""

    schema = "audit."

    def __init__(self, server: str, database: str, authentication: str = "ActiveDirectoryMSI"):
        from modelaudit.cloud.sinks import AzureSqlSink

        self._sink = AzureSqlSink(server, database, authentication)  # reuses its connect-with-retry

    def connect(self):
        return self._sink.connect()

    def _select(self, fields, view, where, params, order, limit):
        return (f"SELECT TOP ({int(limit)}) {', '.join(fields)} FROM audit.{view} "
                f"WHERE {' AND '.join(where)} ORDER BY {order}")
