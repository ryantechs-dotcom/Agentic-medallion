"""P1 runner pieces and answer metrics on tiny in-memory inputs (no model, no data)."""

import json

import pytest

from medrag import contracts
from medrag.config import load_config
from medrag.evaluation import runner
from medrag.evaluation.metrics import answer_metrics, citation_check, group_by
from medrag.generation.llm import fake_complete

RECORDS = [
    {"id": "nhanes/DIQ_J.htm#DIQ010", "doc": "nhanes/DIQ_J.htm", "section": "DIQ010",
     "order": 1, "text": "DIQ010 diabetes 9 Don't know"},
    {"id": "nhanes/DIQ_J.htm#intro", "doc": "nhanes/DIQ_J.htm", "section": "intro",
     "order": 0, "text": "Diabetes questionnaire"},
    {"id": "mimic/patients.md#anchor_age", "doc": "mimic/patients.md", "section": "anchor_age",
     "order": 0, "text": "anchor_age is the age in anchor_year"},
]


def row(qid="NH-001", qtype="lookup", gold_doc="nhanes/DIQ_J.htm", gold_section="DIQ010",
        gold_evidence=""):
    return {"qid": qid, "split": "dev", "source": "nhanes", "qtype": qtype, "subtype": "",
            "question": "What does DIQ010 = 9 mean?", "gold_answer": "Don't know",
            "gold_doc": gold_doc, "gold_section": gold_section, "gold_evidence": gold_evidence,
            "needs_data": "no", "guessable": "yes", "notes": ""}


class FakeRetriever:
    def search(self, query, k, filters=None):
        return [{"chunk_id": r["id"], "doc": r["doc"], "section": r["section"],
                 "text": r["text"], "score": 1.0 / (i + 1)} for i, r in enumerate(RECORDS[:k])]


def test_evidence_docs_adds_gold_evidence_documents_once():
    r = row(gold_evidence="mimic/patients.md#anchor_age;nhanes/DIQ_J.htm#intro")
    assert runner.evidence_docs(r) == ["nhanes/DIQ_J.htm", "mimic/patients.md"]
    assert runner.evidence_docs(row(gold_doc="")) == []


def test_doc_passages_keep_document_order_and_fail_on_unknown_doc():
    by_doc = runner.group_records(RECORDS)
    ids = [p["id"] for p in runner.doc_passages(["nhanes/DIQ_J.htm"], by_doc)]
    assert ids == ["nhanes/DIQ_J.htm#intro", "nhanes/DIQ_J.htm#DIQ010"]
    with pytest.raises(ValueError):
        runner.doc_passages(["nhanes/missing.htm"], by_doc)


def test_build_context_per_kind():
    by_doc = runner.group_records(RECORDS)
    assert runner.build_context(row(), "none", 5, None, None) == ([], [], None)
    passages, retrieved, skip = runner.build_context(row(), "gold_docs", 5, by_doc, None)
    assert len(passages) == 2 and retrieved == [] and skip is None
    _, _, skip = runner.build_context(row(qtype="unanswerable", gold_doc=""), "gold_docs", 5,
                                      by_doc, None)
    assert skip is not None
    passages, retrieved, _ = runner.build_context(row(), "retrieval", 2, None, FakeRetriever())
    assert [p["id"] for p in passages] == [r["chunk_id"] for r in retrieved]
    assert len(retrieved) == 2 and "text" not in retrieved[0]
    with pytest.raises(ValueError):
        runner.build_context(row(), "oracle", 5, None, None)


def test_citation_check():
    passages = [{"id": r["id"], **{k: r[k] for k in ("doc", "section", "text")}}
                for r in RECORDS]
    assert citation_check(["nhanes/DIQ_J.htm#DIQ010"], passages, "nhanes/DIQ_J.htm",
                          "DIQ010") == (True, [])
    assert citation_check(["mimic/patients.md#anchor_age", "made-up"], passages,
                          "nhanes/DIQ_J.htm", "DIQ010") == (False, ["made-up"])
    assert citation_check([], [], "nhanes/DIQ_J.htm", "DIQ010") == (None, [])


def config_for(kind):
    config = load_config()
    config["condition"] = {"name": "test", "context": kind}
    config["generation"]["max_consecutive_errors"] = 2
    return config


def test_answer_row_outputs_validate_for_every_kind():
    by_doc = runner.group_records(RECORDS)
    for kind in runner.CONTEXT_KINDS:
        out = runner.answer_row(row(), config_for(kind), {"text": "S"}, fake_complete, by_doc,
                                FakeRetriever())
        contracts.validate(out, "run_output")
        assert out["error"] is None and out["answer"] == "fake answer"
    skipped = runner.answer_row(row(qtype="unanswerable", gold_doc=""),
                                config_for("gold_docs"), {"text": "S"}, fake_complete,
                                by_doc, None)
    assert skipped["skipped"] and skipped["answer"] is None and skipped["error"] is None


def test_run_rows_stops_after_consecutive_errors():
    def failing(system, user, schema, settings):
        return {"data": None, "usage": {"input_tokens": 0, "output_tokens": 0},
                "model": "m", "cost_usd": None, "error": "status 429"}
    written = []
    rows = [row(qid=f"NH-{i:03d}") for i in range(5)]
    done, stopped = runner.run_rows(rows, config_for("none"), {"text": "S"}, failing, None,
                                    None, written.append)
    assert stopped and done == 2 and len(written) == 2


def item(qtype="lookup", verdict="correct", error=None, abstained=False, skipped=None,
         citation_hit=None):
    return {"row": {**row(qtype=qtype)},
            "output": {"error": error, "abstained": abstained, "skipped": skipped,
                       "citation_hit": citation_hit, "latency_s": 2.0,
                       "usage": {"input_tokens": 100, "output_tokens": 10}},
            "judgment": {"verdict": verdict} if verdict else None}


def test_answer_metrics():
    items = [item(verdict="correct", citation_hit=True),
             item(verdict="partially_correct", citation_hit=False),
             item(verdict="abstained", abstained=True),
             item(qtype="unanswerable", verdict="correct", abstained=True),
             item(qtype="unanswerable", verdict="incorrect"),
             item(verdict=None, error="status 429"),
             item(verdict=None, skipped="no gold doc")]
    m = answer_metrics(items)
    assert (m["n"], m["n_skipped"], m["n_error"], m["n_judged"]) == (6, 1, 1, 5)
    assert m["accuracy"] == pytest.approx(2 / 5)
    assert m["partial_credit"] == pytest.approx(2.5 / 5)
    assert m["hallucination_rate"] == pytest.approx(1 / 2)
    assert m["wrong_abstain_rate"] == pytest.approx(1 / 3)
    assert m["citation_hit_rate"] == pytest.approx(1 / 2)
    assert m["abstain_rate"] == pytest.approx(2 / 5)
    assert answer_metrics([])["accuracy"] is None


def test_group_by_breaks_down_and_stays_json():
    metrics = group_by([item(), item(qtype="multihop", verdict="incorrect")], ("qtype",),
                       answer_metrics)
    assert set(metrics["by_qtype"]) == {"lookup", "multihop"}
    assert metrics["by_qtype"]["multihop"]["accuracy"] == 0.0
    json.loads(json.dumps(metrics, allow_nan=False))


def test_run_refuses_test_split_without_confirmation():
    with pytest.raises(PermissionError):
        runner.run("c1_closed_book", "test", backend_name="fake")


def test_run_name_marks_ablation_fake_and_smoke():
    config = load_config("c3_rag")
    assert runner.run_name(config, None, "claude_cli").endswith("_p1_c3_rag")
    config["retrieval"]["kind"] = "bm25"
    config["retrieval"]["chunking"] = "fixed"
    config["generation"]["prompt"] = "answer_v2"
    assert runner.run_name(config, 5, "fake").endswith(
        "_p1_c3_rag_bm25_fixed_answer_v2_fake_smoke5")


def test_sme_sample_is_stratified_and_reproducible():
    import importlib.util
    spec = importlib.util.spec_from_file_location("draw_sme_sample",
                                                  "scripts/draw_sme_sample.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [row(qid=f"Q-{i:02d}", qtype=qtype) for i, qtype in
            enumerate(["lookup"] * 8 + ["multihop"] * 3 + ["conflict"] * 6)]
    first = module.draw(rows, 5, seed=0)
    assert [r["qid"] for r in first] == [r["qid"] for r in module.draw(rows, 5, seed=0)]
    qtypes = ("lookup", "multihop", "conflict")
    counts = {q: sum(1 for r in first if r["qtype"] == q) for q in qtypes}
    assert counts == {"lookup": 5, "multihop": 3, "conflict": 5}
    assert "gold_answer" not in module.COLUMNS


def load_script(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_judge_sample_round_robins_verdicts_and_is_blind():
    module = load_script("draw_judge_sample")
    items = [{"run": "r", "qid": f"Q-{i:02d}", "verdict": v}
             for i, v in enumerate(["correct"] * 20 + ["incorrect"] * 3
                                   + ["partially_correct"] * 2)]
    sample = module.draw(items, 9, seed=0)
    counts = {v: sum(1 for s in sample if s["verdict"] == v) for v in
              ("correct", "incorrect", "partially_correct")}
    assert counts == {"correct": 4, "incorrect": 3, "partially_correct": 2}
    assert [s["qid"] for s in sample] == [s["qid"] for s in module.draw(items, 9, seed=0)]
    assert "verdict" not in module.COLUMNS


def test_cohen_kappa():
    module = load_script("draw_judge_sample")
    assert module.cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert module.cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    assert module.cohen_kappa(["a", "a"], ["a", "a"]) is None
    assert module.cohen_kappa([], []) is None


def test_resume_keeps_answers_and_judgments_of_a_finished_run(tmp_path):
    if not (runner.PROJECT_ROOT / "corpus" / "corpus_v1.manifest.json").exists():
        pytest.skip("corpus manifest not present")
    run_dir = tmp_path / "run"
    _, complete = runner.run("c1_closed_book", limit=2, backend_name="fake", run_dir=run_dir)
    assert complete and len(runner.read_jsonl(run_dir / "outputs.jsonl")) == 2
    runner.judge_run(run_dir)
    judged = runner.read_jsonl(run_dir / "judgments.jsonl")
    runner.run("c1_closed_book", limit=2, backend_name="fake", run_dir=run_dir, resume=True)
    assert runner.read_jsonl(run_dir / "judgments.jsonl") == judged
    with pytest.raises(FileExistsError):
        runner.run("c1_closed_book", limit=2, backend_name="fake", run_dir=run_dir)
