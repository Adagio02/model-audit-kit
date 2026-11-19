"""Runs a .sql file against Azure SQL as you (az login), splitting on GO like sqlcmd does.

    python azure/scripts/apply_sql.py --server <srv>.database.windows.net --database auditdb \
        --file azure/sql/schema.sql [--var APP_NAME=maudit-func-abc123]

Uses the same mssql-python driver as the Function, so no sqlcmd install is needed.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path


def batches(sql: str, variables: dict[str, str]) -> list[str]:
    for key, value in variables.items():
        if not re.fullmatch(r"[A-Za-z0-9_.@-]+", value):
            raise ValueError(f"Unsafe value for {key}: {value!r}")
        sql = sql.replace(f"$({key})", value)
    parts = re.split(r"^\s*GO\s*;?\s*$", sql, flags=re.MULTILINE | re.IGNORECASE)
    return [p.strip() for p in parts if p.strip() and not all(
        line.strip().startswith("--") or not line.strip() for line in p.splitlines())]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--var", action="append", default=[], help="NAME=value, replaces $(NAME)")
    args = parser.parse_args()

    import mssql_python

    variables = dict(v.split("=", 1) for v in args.var)
    conn_str = (f"Server=tcp:{args.server},1433;Database={args.database};Encrypt=yes;"
                "TrustServerCertificate=no;ConnectRetryCount=3;ConnectRetryInterval=10;Authentication=ActiveDirectoryDefault")
    for attempt in range(1, 6):  # the serverless database may be paused; it resumes on first connect
        try:
            conn = mssql_python.connect(conn_str, timeout=60)
            break
        except mssql_python.Error as exc:
            if attempt == 5:
                raise
            print(f"  connect attempt {attempt} failed ({exc}); retrying in 20 s")
            time.sleep(20)
    conn.setautocommit(True)
    cur = conn.cursor()
    for i, batch in enumerate(batches(Path(args.file).read_text(encoding="utf-8"), variables), 1):
        cur.execute(batch)
        print(f"  batch {i} ok")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
