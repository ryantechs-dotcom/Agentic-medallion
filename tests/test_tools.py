"""SQL tool, column profile tool and the shared tool schemas (in-memory DuckDB, no data)."""

import duckdb
import pytest

from medrag.tools import TOOL_NAMES, TOOLS, ToolContext, call_tool
from medrag.verify.profile import codebook_special_codes, profile_column
from medrag.verify.sql_tool import check_sql, json_safe, lock_down, run_sql

DIQ_RECORD = {
    "id": "nhanes/2017-2018_DIQ_J.htm#DIQ010", "doc": "nhanes/2017-2018_DIQ_J.htm",
    "section": "DIQ010", "source": "nhanes", "kind": "nhanes_variable", "title": "DIQ010",
    "order": 0, "metadata": {"component": "DIQ_J"},
    "text": "DIQ010 - Doctor told you have diabetes\nCodes: Code or Value | Value Description | "
            "Count | Skip to Item\n1 | Yes | 2 | \n2 | No | 1 | \n7 | Refused | 0 | \n"
            "9 | Don't know | 1 | \n. | Missing | 0 | ",
}


@pytest.fixture
def nhanes_db(tiny_db):
    tiny_db.execute("CREATE TABLE nhanes_2017_2018.diq_j (SEQN INTEGER, DIQ010 DOUBLE)")
    tiny_db.execute("INSERT INTO nhanes_2017_2018.diq_j VALUES "
                    "(1, 1), (2, 1), (3, 2), (4, 9), (5, NULL)")
    return tiny_db


@pytest.mark.parametrize("sql", [
    "SELECT 1", "WITH a AS (SELECT 1 AS x) SELECT x FROM a", "  select * from t  ;",
])
def test_check_sql_accepts_single_select(sql):
    assert check_sql(sql) is None


@pytest.mark.parametrize("sql", [
    "", "DROP TABLE t", "SELECT 1; DROP TABLE t", "COPY (SELECT 1) TO 'x.csv'",
    "ATTACH 'x.db'", "PRAGMA show_tables", "INSERT INTO t VALUES (1)", "SELEC 1",
])
def test_check_sql_rejects_everything_else(sql):
    assert check_sql(sql) is not None


def test_run_sql_rows_columns_and_truncation(tiny_db):
    out = run_sql("SELECT SEQN, RIAGENDR FROM nhanes_2017_2018.demo_j ORDER BY SEQN", 2, 5,
                  tiny_db)
    assert out == {"columns": ["SEQN", "RIAGENDR"], "rows": [[1, 1], [2, 2]],
                   "truncated": True, "error": None}


def test_run_sql_returns_errors_instead_of_raising(tiny_db):
    assert run_sql("DROP TABLE nhanes_2017_2018.demo_j", 5, 5, tiny_db)["error"].startswith(
        "rejected")
    assert "nope" in run_sql("SELECT * FROM nope", 5, 5, tiny_db)["error"]
    assert tiny_db.execute("SELECT count(*) FROM nhanes_2017_2018.demo_j").fetchone() == (3,)


def test_run_sql_times_out(tiny_db):
    out = run_sql("SELECT count(*) FROM range(100000000000)", 5, 0.2, tiny_db)
    assert out["error"] == "timed out after 0.2 s"


def test_lock_down_blocks_file_access(tiny_db, tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("a\n1\n")
    lock_down(tiny_db)
    out = run_sql(f"SELECT * FROM read_csv('{path.as_posix()}')", 5, 5, tiny_db)
    assert out["error"] and "Permission" in out["error"]


def test_json_safe_values():
    import datetime as dt
    import decimal
    assert json_safe(dt.date(2020, 1, 2)) == "2020-01-02"
    assert json_safe(decimal.Decimal("1.50")) == 1.5
    assert json_safe(float("nan")) == "nan"
    assert json_safe({"a": [dt.time(1, 2)]}) == {"a": ["01:02:00"]}


def test_codebook_special_codes():
    assert codebook_special_codes([DIQ_RECORD], "diq_j", "diq010") == {
        7.0: "Refused", 9.0: "Don't know"}
    assert codebook_special_codes([DIQ_RECORD], "DIQ_J", "DIQ999") == {}


def test_profile_excludes_codebook_special_codes(nhanes_db):
    profile = profile_column("nhanes_2017_2018", "DIQ_J", "diq010", top_k=5, con=nhanes_db,
                             codebook=[DIQ_RECORD])
    assert profile == {
        "dtype": "DOUBLE", "n_rows": 5, "n_null": 1, "n_distinct": 2,
        "top_values": [{"value": 1.0, "count": 2}, {"value": 2.0, "count": 1}],
        "min": 1.0, "max": 2.0,
        "special_codes": [{"value": 9.0, "label": "Don't know", "count": 1}],
    }


def test_profile_without_codebook_counts_everything(nhanes_db):
    profile = profile_column("nhanes_2017_2018", "diq_j", "DIQ010", top_k=1, con=nhanes_db)
    assert profile["n_distinct"] == 3 and profile["max"] == 9.0
    assert profile["top_values"] == [{"value": 1.0, "count": 2}]
    assert profile["special_codes"] == []


def test_profile_rejects_unknown_identifiers(nhanes_db):
    with pytest.raises(ValueError):
        profile_column("nhanes_2017_2018", "diq_j", 'DIQ010" FROM x; --', 5, con=nhanes_db)


def test_tool_schemas_are_well_formed():
    assert TOOL_NAMES == ("search_docs", "run_sql", "profile_column")
    for tool in TOOLS:
        assert set(tool) == {"name", "description", "input_schema"}
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert set(schema["required"]) <= set(schema["properties"])


def test_call_tool_dispatches_and_caps_rows(monkeypatch):
    seen = {}

    def fake_run_sql(sql, max_rows, timeout_s):
        seen.update(sql=sql, max_rows=max_rows, timeout_s=timeout_s)
        return {"columns": [], "rows": [], "truncated": False, "error": None}

    class OneHit:
        def search(self, query, k, filters=None):
            return [{"chunk_id": "a#b", "doc": "a", "section": "b", "text": query,
                     "score": 1.0}][:k]

    monkeypatch.setattr("medrag.tools.run_sql", fake_run_sql)
    config = {"retrieval": {"k": 5}, "verify": {"max_rows": 50, "timeout_s": 10},
              "profile": {"top_k": 10}}
    context = ToolContext(retriever=OneHit(), records=[], config=config)
    call_tool("run_sql", {"sql": "SELECT 1", "max_rows": 10_000}, context)
    assert seen == {"sql": "SELECT 1", "max_rows": 50, "timeout_s": 10}
    out = call_tool("search_docs", {"query": "diabetes"}, context)
    assert out["chunks"][0]["text"] == "diabetes"
    with pytest.raises(ValueError):
        call_tool("delete_everything", {}, context)
