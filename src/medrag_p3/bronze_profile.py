"""Bronze column profile: one row per column of every table in the project database (task 7).

Reuses `medrag.verify.profile.profile_column` (contract 11) so the profile an agent sees through
the tool and the profile in the EDA are the same numbers. NHANES refused / don't-know codes come
from the corpus codebook and are reported apart from the values (see that module).
"""

from __future__ import annotations

import json

import duckdb

from medrag import db
from medrag.verify.profile import profile_column

PROFILE_KEYS = ("dtype", "n_rows", "n_null", "n_distinct", "top_values", "min", "max",
                "special_codes")
COLUMNS = ("schema", "table", "column", "ordinal", "dtype", "n_rows", "n_null", "null_pct",
           "n_distinct", "n_special", "min", "max", "top_values", "special_codes")


def list_columns(con: duckdb.DuckDBPyConnection,
                 schemas: frozenset[str] = db.EXPECTED_SCHEMAS) -> list[tuple[str, str, str, int]]:
    """Return (schema, table, column, ordinal) of every base-table column, in a stable order."""
    rows = con.execute(
        "SELECT c.table_schema, c.table_name, c.column_name, c.ordinal_position "
        "FROM information_schema.columns c JOIN information_schema.tables t "
        "ON c.table_schema = t.table_schema AND c.table_name = t.table_name "
        "WHERE t.table_type = 'BASE TABLE' "
        "ORDER BY c.table_schema, c.table_name, c.ordinal_position").fetchall()
    return [row for row in rows if row[0] in schemas]


def validate_profile(profile: dict, where: str) -> dict:
    """Check a profile has the contract-11 keys and consistent counts; fail loudly."""
    missing = [key for key in PROFILE_KEYS if key not in profile]
    if missing:
        raise ValueError(f"{where}: profile missing {missing}")
    if not 0 <= profile["n_null"] <= profile["n_rows"]:
        raise ValueError(f"{where}: n_null {profile['n_null']} outside 0..{profile['n_rows']}")
    if profile["n_distinct"] > profile["n_rows"] - profile["n_null"]:
        raise ValueError(f"{where}: n_distinct exceeds the non-null rows")
    return profile


def flatten(schema: str, table: str, column: str, ordinal: int, profile: dict) -> dict:
    """One flat table row. List-valued fields are JSON strings so the table fits a CSV."""
    n_rows = profile["n_rows"]
    return {
        "schema": schema, "table": table, "column": column, "ordinal": ordinal,
        "dtype": profile["dtype"], "n_rows": n_rows, "n_null": profile["n_null"],
        "null_pct": round(100 * profile["n_null"] / n_rows, 2) if n_rows else None,
        "n_distinct": profile["n_distinct"],
        "n_special": sum(code["count"] for code in profile["special_codes"]),
        "min": profile["min"], "max": profile["max"],
        "top_values": json.dumps(profile["top_values"], ensure_ascii=False),
        "special_codes": json.dumps(profile["special_codes"], ensure_ascii=False),
    }


def profile_database(con: duckdb.DuckDBPyConnection, top_k: int,
                     codebook: list[dict] | None = None) -> list[dict]:
    """Profile every column and return the flat rows (read-only; raises on the first failure)."""
    rows = []
    for schema, table, column, ordinal in list_columns(con):
        profile = profile_column(schema, table, column, top_k, con=con, codebook=codebook)
        validate_profile(profile, f"{schema}.{table}.{column}")
        rows.append(flatten(schema, table, column, ordinal, profile))
    return rows
