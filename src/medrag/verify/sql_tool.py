"""Read-only SQL tool for condition 4 and the P2 verifier (docs/contracts.md section 5).

Defense in depth:
1. `check_sql` parses the text with DuckDB and accepts exactly one SELECT statement (WITH
   queries parse as SELECT); COPY, ATTACH, PRAGMA, DDL and `;`-chained statements are
   rejected before anything runs.
2. The connection is read-only (`medrag.db.connect`) and external file access is switched off,
   so a SELECT can't read or write files outside the database.
3. Rows are capped and long queries are interrupted (`verify.max_rows`, `verify.timeout_s`).
Errors are returned in `error` rather than raised, because the model reads them and retries.
"""

from __future__ import annotations

import datetime as dt
import decimal
import math
import threading
import uuid

import duckdb

from medrag import db


def check_sql(sql: str) -> str | None:
    """Return None if `sql` is a single SELECT statement, else the reason it is rejected."""
    if not sql or not sql.strip():
        return "empty query"
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as err:
        return f"parse error: {err}"
    if len(statements) != 1:
        return f"exactly one statement allowed, got {len(statements)}"
    kind = statements[0].type
    if kind != duckdb.StatementType.SELECT:
        return f"only SELECT/WITH queries are allowed, got {kind.name}"
    return None


def json_safe(value):
    """Convert a DuckDB value to something json.dumps accepts."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, (dt.timedelta, uuid.UUID, bytes)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    return str(value)


def lock_down(con: duckdb.DuckDBPyConnection) -> None:
    """Switch off file and network access for this connection (cannot be switched back)."""
    con.execute("SET enable_external_access = false")


def run_sql(sql: str, max_rows: int, timeout_s: float,
            con: duckdb.DuckDBPyConnection | None = None) -> dict:
    """Run one SELECT and return `{columns, rows, truncated, error}` (contract 5).

    `con` is for tests (e.g. an in-memory database); by default the project database is
    opened read-only, locked down, and closed afterwards.
    """
    result = {"columns": [], "rows": [], "truncated": False, "error": None}
    reason = check_sql(sql)
    if reason:
        result["error"] = f"rejected: {reason}"
        return result
    own = con is None
    if own:
        con = db.connect()
        lock_down(con)
    timer = threading.Timer(timeout_s, con.interrupt)
    timer.start()
    try:
        cursor = con.execute(sql)
        rows = cursor.fetchmany(max_rows + 1)
        result["columns"] = [d[0] for d in cursor.description]
        result["truncated"] = len(rows) > max_rows
        result["rows"] = [[json_safe(v) for v in row] for row in rows[:max_rows]]
    except duckdb.InterruptException:
        result["error"] = f"timed out after {timeout_s} s"
    except duckdb.Error as err:
        result["error"] = f"{type(err).__name__}: {err}"
    finally:
        timer.cancel()
        if own:
            con.close()
    return result
