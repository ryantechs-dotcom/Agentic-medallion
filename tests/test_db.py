import duckdb
import pytest

from medrag import db


def test_snapshot_has_expected_schemas(snapshot_required):
    con = db.connect()
    try:
        assert db.schemas(con) == db.EXPECTED_SCHEMAS
    finally:
        con.close()


def test_snapshot_is_read_only(snapshot_required):
    con = db.connect()
    try:
        with pytest.raises(duckdb.Error):
            con.execute("CREATE TABLE should_fail (x INTEGER)")
    finally:
        con.close()


def test_tiny_db_fixture(tiny_db):
    rows = tiny_db.execute(
        "SELECT RIAGENDR, COUNT(*) FROM nhanes_2017_2018.demo_j GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert rows == [(1, 1), (2, 2)]
