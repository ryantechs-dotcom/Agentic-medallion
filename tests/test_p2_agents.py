"""P2 agents (#14/#15) on a scripted backend: no model, no API key, no network."""

import json

import pytest

from medrag import contracts
from medrag.config import db_path, load_config
from medrag_p2 import agents, tools
from medrag_p2.scoring import score_run

needs_data = pytest.mark.skipif(not db_path().exists(), reason="data snapshot not unzipped")

P2 = load_config("p2")["p2"]
TABLE = {"schema": "mimic_demo_v1_0_core", "table": "patients", "n_rows": 100,
         "columns": [{"name": "gender", "dtype": "VARCHAR"},
                     {"name": "dod", "dtype": "VARCHAR"}]}
PROMPTS = {role: {"text": f"{role} prompt", "file": f"{role}.txt", "sha256": "x"}
           for role in ("base", "single", "retriever", "proposer", "verifier")}


def spec(col, table=None, field=None, mtype="direct", conf=0.9, evidence=None):
    return {"source_column": col, "target_table": table, "target_field": field,
            "mapping_type": mtype, "target_type": None, "transform_rule": "copy",
            "evidence": evidence or [{"doc": "omop/x.csv", "section": "person", "sql": "",
                                      "result": ""}], "confidence": conf}


def tool_step(tool, args):
    return {"action": "tool", "tool": tool, "tool_input_json": json.dumps(args),
            "output": {}}


def finish(key, items):
    return {"action": "finish", "tool": "", "tool_input_json": "", "output": {key: items}}


class Scripted:
    """A backend that replays steps per role (told apart by the role prompt in `system`)."""

    def __init__(self, by_role):
        self.by_role = {role: list(steps) for role, steps in by_role.items()}
        self.calls = []

    def __call__(self, system, user, schema, settings):
        role = system.rsplit("\n\n", 1)[-1].split()[0]
        self.calls.append({"role": role, "user": user, "schema": schema})
        data = self.by_role[role].pop(0)
        if isinstance(data, Exception):
            return {"data": None, "usage": {}, "model": "m", "cost_usd": None,
                    "error": str(data)}
        return {"data": data, "usage": {"input_tokens": 10, "output_tokens": 5},
                "model": "m", "cost_usd": 0.01, "error": None}


def recording_caller(log):
    def call(name, args):
        log.append((name, args))
        return {"columns": ["n"], "rows": [[1]], "truncated": False, "error": None}
    return tools.make_caller(call, P2)


# --- guard ---------------------------------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "SELECT * FROM omop_demo_v0_9.person",
    "select * from OMOP_DEMO_V0_9.death",
    "SELECT * FROM query_table('omop_demo_v0_9.person')",
    "SELECT * FROM mimic_demo_v2_2_hosp.admissions",
])
def test_guard_blocks_answer_key_and_other_schemas(sql):
    log = []
    out = recording_caller(log)("run_sql", {"sql": sql})
    assert out["error"].startswith("rejected: only the source schemas") and log == []


def test_guard_allows_source_and_checks_profile_schema():
    log = []
    caller = recording_caller(log)
    assert caller("run_sql", {"sql": "SELECT 1 FROM mimic_demo_v1_0_core.patients"})["error"] \
        is None
    assert "works on" in caller("profile_column", {"schema": "omop_demo_v0_9",
                                                   "table": "person", "column": "x"})["error"]
    assert [name for name, _ in log] == ["run_sql"]


def test_tool_exception_becomes_error_result():
    def boom(name, args):
        raise KeyError("column")
    out = tools.make_caller(boom, P2)("profile_column", {"schema": "mimic_demo_v1_0_core"})
    assert out["error"].startswith("KeyError")


# --- step loop -----------------------------------------------------------------------------

def test_step_schema_matches_role_tools():
    assert agents.step_schema("proposer")["properties"]["action"]["enum"] == ["finish"]
    verifier = agents.step_schema("verifier")
    assert verifier["properties"]["tool"]["enum"] == ["run_sql", "profile_column", ""]
    assert "verdicts" in verifier["properties"]["output"]["properties"]


def test_loop_runs_tool_feeds_result_back_then_finishes():
    backend = Scripted({"single": [
        tool_step("run_sql", {"sql": "SELECT 1 FROM mimic_demo_v1_0_core.patients"}),
        finish("specs", [spec("gender", "person", "gender_source_value")])]})
    log = []
    out = agents.run_agent("single", "base\n\nsingle prompt", "task", backend, {},
                           recording_caller(log), 5, 1000)
    assert out["error"] is None and out["model_calls"] == 2 and len(log) == 1
    assert '"rows": [[1]]' in backend.calls[1]["user"]       # result shown in the next call
    assert out["usage"] == {"input_tokens": 20, "output_tokens": 10}
    assert out["tool_calls"][0]["tool"] == "run_sql"


def test_bad_tool_input_is_fed_back_and_uses_a_step():
    bad = {"action": "tool", "tool": "run_sql", "tool_input_json": "not json", "output": {}}
    backend = Scripted({"single": [bad, finish("specs", [])]})
    out = agents.run_agent("single", "b\n\nsingle p", "task", backend, {},
                           recording_caller([]), 5, 1000)
    assert out["error"] is None and "not a JSON object" in backend.calls[1]["user"]


def test_step_budget_and_backend_error_stop_the_agent():
    loop = [tool_step("run_sql", {"sql": "SELECT 1"})] * 3
    out = agents.run_agent("single", "b\n\nsingle p", "t", Scripted({"single": loop}), {},
                           recording_caller([]), 3, 1000)
    assert "step budget (3)" in out["error"] and out["output"] is None
    out = agents.run_agent("single", "b\n\nsingle p", "t",
                           Scripted({"single": [RuntimeError("CLI timed out")]}), {},
                           recording_caller([]), 3, 1000)
    assert "CLI timed out" in out["error"]


# --- specs ---------------------------------------------------------------------------------

def test_to_specs_validates_numbers_and_drops_unknown_columns():
    raw = [spec("gender", "Person", "Gender_Source_Value"),
           spec("gender", "person", "gender_concept_id", "concept_lookup"),
           spec("dod", None, None, "not_mapped"), spec("no_such_column", "person", "x")]
    specs, dropped = agents.to_specs(raw, TABLE, "proposed", "single")
    assert dropped == 1
    assert [s["spec_id"] for s in specs] == ["patients.gender", "patients.gender#2",
                                             "patients.dod"]
    assert specs[0]["target_table"] == "person" and specs[2]["target_field"] is None
    for s in specs:
        contracts.validate(s, "p2_spec")


def test_single_pipeline():
    backend = Scripted({"single": [finish("specs", [
        spec("gender", "person", "gender_source_value"), spec("dod", None, None, "not_mapped")])]})
    result = agents.run_single(TABLE, PROMPTS, backend, {}, recording_caller([]), P2)
    assert [s["status"] for s in result["specs"]] == ["proposed", "proposed"]
    assert result["model_calls"] == 1


def test_multi_pipeline_revises_rejected_and_escalates_to_human():
    backend = Scripted({
        "retriever": [tool_step("profile_column", {"schema": "mimic_demo_v1_0_core",
                                                   "table": "patients", "column": "dod"}),
                      finish("notes", [{"source_column": "dod", "findings": "all null",
                                        "evidence": []}])],
        "proposer": [finish("specs", [spec("gender", "person", "gender_source_value"),
                                      spec("dod", "death", "death_date", "transform")]),
                     finish("specs", [spec("dod", "person", "birth_datetime", "transform")])],
        "verifier": [finish("verdicts", [
                        {"spec_id": "patients.gender", "status": "verified", "reason": "",
                         "evidence": []},
                        {"spec_id": "patients.dod", "status": "rejected", "reason": "all NULL",
                         "evidence": [{"doc": "", "section": "",
                                       "sql": "SELECT COUNT(dod) FROM x", "result": "0"}]}]),
                     finish("verdicts", [{"spec_id": "patients.dod", "status": "rejected",
                                          "reason": "still wrong", "evidence": []}])],
    })
    result = agents.run_multi(TABLE, PROMPTS, backend, {}, recording_caller([]), P2)
    assert [c["role"] for c in backend.calls] == ["retriever", "retriever", "proposer",
                                                  "verifier", "proposer", "verifier"]
    status = {s["source_column"]: s["status"] for s in result["specs"]}
    assert status == {"gender": "verified", "dod": "needs_human"}      # 1 revision round
    assert result["initial_specs"][1]["target_table"] == "death"
    assert [(v["round"], v["status"]) for v in result["verdicts"]] == [
        (1, "verified"), (1, "rejected"), (2, "rejected")]
    assert "all NULL" in backend.calls[4]["user"]          # reasons go back to the proposer


# --- scoring -------------------------------------------------------------------------------

def gt(table, col, tt, tf, primary="Y", mtype="direct", alts="", split="dev"):
    return {"source_table": table, "source_column": col, "target_table": tt,
            "target_field": tf, "is_primary": primary, "mapping_type": mtype,
            "acceptable_alternatives": alts, "split": split}


GOLD = [gt("patients", "gender", "person", "gender_concept_id", mtype="concept_lookup"),
        gt("patients", "gender", "person", "gender_source_value", primary="N"),
        gt("patients", "dod", "", "", mtype="not_mapped", alts="death.death_date")]


def scored(raw, arch="single", extra=None):
    specs, _ = agents.to_specs(raw, TABLE, "proposed", arch)
    out = {"qid": "x", "table": "patients", "architecture": arch, "specs": specs,
           "tool_calls": [], "usage": {}, **(extra or {})}
    return score_run([out], GOLD, {("omop/x.csv", "person")}, lambda sql: True, 3)


def test_scoring_strict_and_lenient():
    m = scored([spec("gender", "person", "gender_source_value", conf=0.5),
                spec("gender", "person", "gender_concept_id", "concept_lookup", conf=0.9),
                spec("dod", "death", "death_date", "transform")])["overall"]
    assert (m["precision"], m["recall"]) == (round(2 / 3, 4), round(2 / 3, 4))
    assert (m["precision_lenient"], m["recall_lenient"]) == (1.0, 1.0)
    assert (m["top1_accuracy"], m["top1_accuracy_lenient"]) == (0.5, 1.0)
    assert m["mapping_type_accuracy"] == 1.0


def test_scoring_not_mapped_counts_and_missing_columns_listed():
    m = scored([spec("dod", None, None, "not_mapped")])["overall"]
    assert m["precision"] == 1.0 and m["recall"] == round(1 / 3, 4)
    assert m["columns_without_spec"] == ["patients.gender"]


def test_evidence_validity():
    good = spec("gender", "person", "gender_source_value")
    fake_doc = spec("dod", None, None, "not_mapped",
                    evidence=[{"doc": "made/up.md", "section": "x", "sql": "", "result": ""}])
    assert scored([good, fake_doc])["evidence_valid_share"] == 0.5


def test_verifier_catch_rate():
    initial, _ = agents.to_specs([spec("gender", "person", "gender_source_value"),
                                  spec("dod", "person", "birth_datetime", "transform")],
                                 TABLE, "proposed", "multi:proposer")
    verdicts = [{"round": 1, "spec_id": "patients.gender", "status": "verified"},
                {"round": 1, "spec_id": "patients.dod", "status": "rejected"}]
    m = scored([], "multi", {"initial_specs": initial, "verdicts": verdicts})
    assert (m["verifier_catch_rate"], m["verifier_false_alarm_rate"]) == (1.0, 0.0)


# --- runner --------------------------------------------------------------------------------

@needs_data
def test_fake_run_writes_a_scored_run_folder(tmp_path):
    from medrag_p2.run import run
    run_dir = run("multi", "dev", tables=["patients"], backend_name="fake",
                  run_dir=tmp_path / "r")
    config = json.loads((run_dir / "config.json").read_text())
    assert set(config["prompts"]) == {"base", "retriever", "proposer", "verifier"}
    assert config["ground_truth"]["sha256"]
    metrics = json.loads((run_dir / "metrics.json").read_text())
    assert metrics["overall"]["n_columns"] == 6 and metrics["overall"]["recall"] == 0.0


@needs_data
def test_real_run_needs_frozen_ground_truth_and_test_needs_confirmation(tmp_path):
    from medrag_p2.run import PROJECT_ROOT, run
    if (PROJECT_ROOT / P2["ground_truth"]).exists():
        pytest.skip("ground truth already frozen")
    with pytest.raises(PermissionError, match="D16"):
        run("single", "dev", run_dir=tmp_path / "r")
    with pytest.raises(PermissionError, match="final runs"):
        run("single", "test", backend_name="fake", run_dir=tmp_path / "t")
