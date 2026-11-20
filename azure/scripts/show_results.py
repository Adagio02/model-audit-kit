"""Shows audit results from Azure SQL in the terminal (signs in with your az login).

    .\.venv\Scripts\python.exe azure\scripts\show_results.py            # every run
    .\.venv\Scripts\python.exe azure\scripts\show_results.py findings   # every WARN/FAIL with its explanation
"""

import sys
import textwrap

import mssql_python

SERVER = "maudit-sql-6m5n2u.database.windows.net"
DATABASE = "auditdb"

QUERIES = {
    "runs": "SELECT client, batch, verdict, n_fail, n_warn, net_sharpe, error_message, audited_utc "
            "FROM audit.v_runs ORDER BY audited_utc DESC",
    "findings": "SELECT client, batch, check_key, status, explanation FROM audit.v_findings "
                "ORDER BY client, batch, check_key",
}


def main() -> int:
    what = sys.argv[1] if len(sys.argv) > 1 else "runs"
    if what not in QUERIES:
        print(f"Use one of: {', '.join(QUERIES)}")
        return 1
    print(f"Connecting to {SERVER} (can take up to a minute if the database was paused)...")
    conn = mssql_python.connect(f"Server=tcp:{SERVER},1433;Database={DATABASE};Encrypt=yes;"
                                "Authentication=ActiveDirectoryDefault", timeout=90)
    cur = conn.cursor()
    cur.execute(QUERIES[what])
    columns = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print("No rows yet. If you submitted a batch, check the audit-reports container and the Function's Monitor tab.")
        return 0
    for row in rows:
        print("-" * 80)
        for name, value in zip(columns, row):
            text = "" if value is None else str(value)
            print(f"{name:>14}: " + textwrap.fill(text, 90, subsequent_indent=" " * 16) if len(text) > 90
                  else f"{name:>14}: {text}")
    print("-" * 80)
    print(f"{len(rows)} row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
