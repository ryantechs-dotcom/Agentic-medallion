"""Shared fixtures. Tests never need an API key or network."""

import duckdb
import pytest

from medrag.config import db_path


@pytest.fixture
def tiny_db():
    """In-memory DuckDB with a minimal NHANES-like table, for unit tests of SQL code."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA nhanes_2017_2018")
    con.execute("CREATE TABLE nhanes_2017_2018.demo_j (SEQN INTEGER, RIAGENDR INTEGER)")
    con.execute("INSERT INTO nhanes_2017_2018.demo_j VALUES (1, 1), (2, 2), (3, 2)")
    yield con
    con.close()


@pytest.fixture
def snapshot_required():
    """Skip tests that need the real data snapshot when it is not unzipped."""
    if not db_path().exists():
        pytest.skip("data snapshot not present")
