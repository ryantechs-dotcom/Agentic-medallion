"""Condition 4 data checks: table hints, plan validation, running checks, the runner path."""

from medrag import contracts
from medrag.config import load_config
from medrag.evaluation import runner
from medrag.verify import checks

CATALOG = {
    ("nhanes_2017_2018", "diq_j"): ["SEQN", "DIQ010", "DID260"],
    ("mimic_demo_v1_0_hosp", "prescriptions"): ["subject_id", "pharmacy_id"],
    ("mimic_demo_v2_2_hosp", "prescriptions"): ["subject_id", "pharmacy_id", "poe_id"],
    ("omop_demo_v0_9", "person"): ["person_id", "year_of_birth"],
}


def passage(doc, section="", pid="p"):
    return {"id": pid, "doc": doc, "section": section, "text": "t"}


def config():
    c = load_config("c4_rag_verify")
    c["generation"]["max_consecutive_errors"] = 2
    return c


def test_doc_tables_map_each_source_to_its_tables():
    assert checks.doc_tables("nhanes/2017-2018_DIQ_J.htm", "DID260", CATALOG) == [
        ("nhanes_2017_2018", "diq_j")]
    assert checks.doc_tables("mimic/hosp__prescriptions.md", "poe_id", CATALOG) == [
        ("mimic_demo_v1_0_hosp", "prescriptions"), ("mimic_demo_v2_2_hosp", "prescriptions")]
    assert checks.doc_tables("omop/OMOP_CDMv5.3_Field_Level.csv", "person.year_of_birth",
                             CATALOG) == [("omop_demo_v0_9", "person")]
    assert checks.doc_tables("mimic/about__changelog.md", "trimmed", CATALOG) == []
    assert checks.doc_tables("nhanes/2017-2018_AUX_J.htm", "x", CATALOG) == []


def test_table_hints_dedupe_and_cap_columns():
    hints = checks.table_hints([passage("mimic/hosp__prescriptions.md", "poe_id"),
                                passage("mimic/hosp__prescriptions.md", "drug")], CATALOG, 2)
    assert hints.splitlines() == [
        "mimic_demo_v1_0_hosp.prescriptions: subject_id, pharmacy_id",
        "mimic_demo_v2_2_hosp.prescriptions: subject_id, pharmacy_id, ... (1 more)"]
    assert checks.table_hints([passage("mimic/about__changelog.md")], CATALOG, 5) == \
        checks.NO_TABLES


def test_check_plan_limits():
    assert checks.check_plan({"queries": ["SELECT 1"]}, 3) is None
    assert checks.check_plan({"queries": ["a", "b", "c", "d"]}, 3) is not None
    assert checks.check_plan({"queries": [1]}, 3) is not None
    assert checks.check_plan({"answer": "x"}, 3) is not None
    assert checks.plan_schema(3)["properties"]["queries"]["maxItems"] == 3


def test_run_checks_turns_results_into_citable_passages():
    def sql(query, max_rows, timeout_s):
        if "bad" in query:
            return {"columns": [], "rows": [], "truncated": False, "error": "rejected: x"}
        return {"columns": ["n"], "rows": [[3]], "truncated": False, "error": None}

    passages, calls = checks.run_checks(["SELECT 3 AS n", "bad"], config(), sql,
                                        clock=lambda: 0.0)
    assert [p["id"] for p in passages] == ["sql:1", "sql:2"]
    assert "Query: SELECT 3 AS n\nResult:\nn\n3" in passages[0]["text"]
    assert "Error: rejected: x" in passages[1]["text"]
    assert calls[0] == {"tool": "run_sql", "input": {"sql": "SELECT 3 AS n"},
                        "output_summary": "1 rows x 1 columns", "latency_s": 0.0}
    assert calls[1]["output_summary"].startswith("error:")


def backend_with_plan(queries, plan_error=None):
    def complete(system, user, schema, settings):
        usage = {"input_tokens": 10, "output_tokens": 2}
        if "queries" in schema["properties"]:
            assert "Tables behind these passages" in user
            return {"data": {"queries": queries}, "usage": usage, "model": "m",
                    "cost_usd": 0.5, "error": plan_error}
        assert "[sql:1]" in user or not queries
        return {"data": {"answer": "a", "citations": ["sql:1"], "abstain": False},
                "usage": usage, "model": "m", "cost_usd": 0.25, "error": None}
    return complete


class Retriever:
    def search(self, query, k, filters=None):
        return [{"chunk_id": "nhanes/2017-2018_DIQ_J.htm#DID260",
                 "doc": "nhanes/2017-2018_DIQ_J.htm", "section": "DID260", "text": "codes",
                 "score": 1.0}]


def row():
    return {"qid": "NH-042", "question": "How many never check?", "gold_doc":
            "nhanes/2017-2018_DIQ_J.htm", "gold_section": "DID260"}


def test_answer_row_with_verifier_records_tool_calls_and_both_calls_usage():
    sql = {"columns": ["n"], "rows": [[178]], "truncated": False, "error": None}
    verifier = {"prompt": {"text": "P"}, "catalog": CATALOG, "sql": lambda q, m, t: sql}
    out = runner.answer_row(row(), config(), {"text": "S"},
                            backend_with_plan(["SELECT COUNT(*) AS n FROM x"]), None,
                            Retriever(), verifier)
    contracts.validate(out, "run_output")
    assert out["error"] is None and out["citations"] == ["sql:1"]
    assert out["invalid_citations"] == [] and out["n_passages"] == 2
    assert [c["tool"] for c in out["tool_calls"]] == ["run_sql"]
    assert out["usage"]["input_tokens"] == 20 and out["cost_usd"] == 0.75
    assert [r["chunk_id"] for r in out["retrieved"]] == ["nhanes/2017-2018_DIQ_J.htm#DID260"]


def test_answer_row_with_verifier_fails_the_item_on_a_plan_error():
    verifier = {"prompt": {"text": "P"}, "catalog": CATALOG}
    out = runner.answer_row(row(), config(), {"text": "S"},
                            backend_with_plan([], plan_error="CLI timed out"), None,
                            Retriever(), verifier)
    assert out["error"] == "verify plan: CLI timed out" and out["answer"] is None


def test_c4_config_keeps_c3_retrieval_and_the_frozen_answer_prompt():
    c4, c3 = load_config("c4_rag_verify"), load_config("c3_rag")
    assert c4["condition"]["verify"] is True and c4["condition"]["context"] == "retrieval"
    assert c4["retrieval"] == c3["retrieval"] and c4["generation"] == c3["generation"]
    assert "c4_rag_verify" in runner.CONDITIONS
