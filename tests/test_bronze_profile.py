"""Bronze column profile (task 7): in-memory DuckDB, plus one check on the real snapshot."""

import json

import pytest

from medrag import db
from medrag_p3.bronze_profile import (COLUMNS, flatten, list_columns, profile_database,
                                      validate_profile)
from test_tools import DIQ_RECORD


@pytest.fixture
def con(tiny_db):
    tiny_db.execute("CREATE TABLE nhanes_2017_2018.diq_j (SEQN INTEGER, DIQ010 DOUBLE)")
    tiny_db.execute("INSERT INTO nhanes_2017_2018.diq_j VALUES "
                    "(1, 1), (2, 1), (3, 2), (4, 9), (5, NULL)")
    tiny_db.execute("CREATE VIEW nhanes_2017_2018.v AS SELECT 1 AS x")
    tiny_db.execute("CREATE SCHEMA other")
    tiny_db.execute("CREATE TABLE other.t (a INTEGER)")
    return tiny_db


def test_list_columns_skips_views_and_unknown_schemas(con):
    columns = list_columns(con)
    assert ("nhanes_2017_2018", "demo_j", "SEQN", 1) in columns
    assert all(schema == "nhanes_2017_2018" for schema, *_ in columns)
    assert not any(table == "v" for _, table, *_ in columns)
    assert [c[3] for c in columns if c[1] == "diq_j"] == [1, 2]


def test_profile_database_one_row_per_column_with_special_codes(con):
    rows = profile_database(con, 10, [DIQ_RECORD])
    assert len(rows) == 4                       # demo_j (2) + diq_j (2)
    assert all(set(row) == set(COLUMNS) for row in rows)
    diq = next(row for row in rows if row["column"] == "DIQ010")
    assert diq["n_rows"] == 5 and diq["n_null"] == 1 and diq["null_pct"] == 20.0
    assert diq["n_distinct"] == 2               # the 9 is a code, not a value
    assert diq["n_special"] == 1 and diq["max"] == 2.0
    assert json.loads(diq["special_codes"])[0]["label"] == "Don't know"
    assert json.loads(diq["top_values"])[0] == {"value": 1.0, "count": 2}


def test_flatten_empty_table_has_no_null_pct():
    profile = {"dtype": "INTEGER", "n_rows": 0, "n_null": 0, "n_distinct": 0, "top_values": [],
               "min": None, "max": None, "special_codes": []}
    assert flatten("s", "t", "c", 1, profile)["null_pct"] is None


@pytest.mark.parametrize("change", [{"n_null": 9}, {"n_distinct": 9}])
def test_validate_profile_rejects_inconsistent_counts(change):
    profile = {"dtype": "INTEGER", "n_rows": 3, "n_null": 0, "n_distinct": 2, "top_values": [],
               "min": None, "max": None, "special_codes": []}
    with pytest.raises(ValueError):
        validate_profile({**profile, **change}, "s.t.c")


def test_validate_profile_rejects_missing_keys():
    with pytest.raises(ValueError, match="missing"):
        validate_profile({"dtype": "INTEGER"}, "s.t.c")


def test_real_snapshot_patients_gender(snapshot_required):
    con = db.connect()
    try:
        rows = profile_database(con, 10, None)
    finally:
        con.close()
    gender = next(row for row in rows if row["schema"] == "mimic_demo_v1_0_core"
                  and row["table"] == "patients" and row["column"] == "gender")
    assert json.loads(gender["top_values"]) == [{"value": "M", "count": 57},
                                                {"value": "F", "count": 43}]
    assert len(rows) == 1335
