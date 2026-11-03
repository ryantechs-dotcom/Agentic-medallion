"""Read-only access to the frozen DuckDB snapshot.

This is the only module that calls `duckdb.connect`, so the read-only rule is enforced in one
place.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from medrag.config import db_path

EXPECTED_SCHEMAS = frozenset({
    "mimic_demo_v1_0_core",
    "mimic_demo_v1_0_hosp",
    "mimic_demo_v1_0_icu",
    "mimic_demo_v2_2",
    "mimic_demo_v2_2_hosp",
    "mimic_demo_v2_2_icu",
    "nhanes_2017_2018",
    "omop_demo_v0_9",
})


def connect(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open the project database read-only."""
    path = path or db_path()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - unzip the data snapshot at the repo root.")
    return duckdb.connect(str(path), read_only=True)


def schemas(con: duckdb.DuckDBPyConnection) -> set[str]:
    """Return the user schemas present in the database."""
    rows = con.execute(
        "SELECT DISTINCT table_schema FROM information_schema.tables "
        "WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'main')"
    ).fetchall()
    return {row[0] for row in rows}
