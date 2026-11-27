"""scripts/p1_results_table.py on synthetic run folders (no model, no data, no network)."""

import json

import pytest

import p1_results_table as table

GROUPS = {"by_qtype": ("lookup", "unanswerable"), "by_needs_data": ("no", "yes")}
N_SPLIT = 10


def block(accuracy, n):
    return {"accuracy": accuracy, "abstain_rate": 0.1, "hallucination_rate": 0.0,
            "citation_hit_rate": 1.0, "mean_input_tokens": 1000.0, "mean_latency_s": 5.0,
            "mean_output_tokens": 300.0, "n": n, "n_judged": n, "n_error": 0, "n_skipped": 0,
            "partial_credit": accuracy}


def make_run(results_dir, condition, repeat, accuracy=0.5, *, commit="abc1234", dirty=False,
             split="test", limit=None, judged=True, date="2026-11-27", n_overall=N_SPLIT,
             n_outputs=N_SPLIT):
    run_dir = results_dir / f"{date}_p1_{condition}_test_r{repeat}"
    run_dir.mkdir(parents=True)
    config = {"condition": {"name": condition, "context": "none"}, "split": split,
              "eval": {"split": "dev"}, "git_commit": commit, "git_dirty": dirty,
              "limit": limit}
    (run_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    acc = accuracy if judged else None
    metrics = {"overall": block(acc, n_overall), "answerable": block(acc, 8),
               "n_questions_in_split": N_SPLIT,
               "judge": {"git_commit": commit, "git_dirty": False,
                         "prompt": {"sha256": "judge-sha"}}}
    for key, names in GROUPS.items():
        metrics[key] = {name: block(acc, 4) for name in names}
    (run_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (run_dir / "outputs.jsonl").write_text(
        "".join(json.dumps({"qid": f"Q{i}"}) + "\n" for i in range(n_outputs)), encoding="utf-8")
    return run_dir


def load_all(results_dir):
    return [{**table.load_run(d), "repeat": table.parse_repeat(d.name)}
            for d in sorted(results_dir.glob(table.RUN_GLOB))]


def table_lines(out):
    return (out / "table.md").read_text(encoding="utf-8").splitlines()


def test_parse_repeat_reads_the_folder_suffix():
    assert table.parse_repeat("2026-11-27_p1_c3_rag_test_r12") == 12
    with pytest.raises(table.RunSetError):
        table.parse_repeat("2026-11-27_p1_c3_rag_test_r1_old")


def test_mean_min_max_over_three_repeats(tmp_path):
    for repeat, accuracy in ((1, 0.6), (2, 0.7), (3, 0.8)):
        make_run(tmp_path, "c3_rag", repeat, accuracy)
    runs = load_all(tmp_path)
    table.validate_runs(runs)
    stats = table.aggregate(runs)["conditions"]["c3_rag"]
    assert stats["repeats"] == [1, 2, 3]
    acc = stats["metrics"]["accuracy"]
    assert acc["mean"] == pytest.approx(0.7)
    assert (acc["min"], acc["max"], acc["n_repeats"]) == (0.6, 0.8, 3)
    assert acc["values"] == [0.6, 0.7, 0.8]
    assert acc["n_values"] == [N_SPLIT] * 3
    assert stats["metrics"]["answerable_accuracy"]["n_values"] == [8, 8, 8]
    assert stats["metrics"]["accuracy_qtype_lookup"]["mean"] == pytest.approx(0.7)
    assert stats["metrics"]["accuracy_needs_data_yes"]["max"] == 0.8


def test_main_writes_summary_and_one_column_per_condition(tmp_path):
    results, out = tmp_path / "results", tmp_path / "out"
    for condition in ("c4_rag_verify", "c1_closed_book", "c2_long_context", "c3_rag"):
        for repeat in (1, 2):
            make_run(results, condition, repeat, 0.5 + 0.1 * repeat)
    assert table.main(["--results-dir", str(results), "--out", str(out)]) == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert list(summary["conditions"]) == list(table.CONDITIONS)
    assert len(summary["runs"]) == 8
    assert all(len(run["metrics_sha256"]) == 64 for run in summary["runs"])
    assert all("n_values" in stats for cond in summary["conditions"].values()
               for stats in cond["metrics"].values())
    lines = table_lines(out)
    header = next(line for line in lines if line.startswith("| Metric"))
    assert header == "| Metric | c1_closed_book | c2_long_context | c3_rag | c4_rag_verify |"
    accuracy = next(line for line in lines if line.startswith("| Accuracy, overall"))
    assert accuracy.count("|") == 6
    assert "0.650 (0.600–0.700), n=10" in accuracy


def test_answerable_accuracy_is_the_first_row_and_overall_shows_its_n(tmp_path):
    results, out = tmp_path / "results", tmp_path / "out"
    for condition in table.CONDITIONS:
        n_overall = 8 if condition == "c2_long_context" else N_SPLIT
        make_run(results, condition, 1, n_overall=n_overall)
    assert table.main(["--results-dir", str(results), "--out", str(out)]) == 0
    rows = [line for line in table_lines(out) if line.startswith("| ")][1:]   # skip header
    assert rows[0].startswith("| Repeats")
    assert "comparison row" in rows[1] and "n=" not in rows[1]
    assert rows[2].startswith("| Accuracy, overall")
    assert "0.500 (0.500–0.500), n=10" in rows[2] and "n=8" in rows[2]
    abstain = next(row for row in rows if row.startswith("| Abstain rate"))
    assert "n=8" in abstain     # n differs between conditions, so it is shown
    lookup = next(row for row in rows if "qtype = lookup" in row)
    assert "n=" not in lookup   # same n everywhere


@pytest.mark.parametrize("bad, message", [
    ({"commit": "def5678"}, "disagree on git_commit"),
    ({"dirty": True}, "git_dirty"),
    ({"judged": False}, "not judged"),
    ({"split": "dev"}, "split"),
    ({"limit": 5}, "limit"),
    ({"n_outputs": N_SPLIT - 1}, "incomplete, outputs.jsonl has 9 answers"),
])
def test_refuses_runs_that_are_not_one_clean_final_set(tmp_path, bad, message):
    make_run(tmp_path, "c1_closed_book", 1)
    make_run(tmp_path, "c3_rag", 1, **bad)
    with pytest.raises(table.RunSetError, match=message):
        table.validate_runs(load_all(tmp_path))


def test_refuses_duplicate_repeat_numbers(tmp_path):
    make_run(tmp_path, "c3_rag", 1, date="2026-11-27")
    make_run(tmp_path, "c3_rag", 1, date="2026-11-28")
    with pytest.raises(table.RunSetError, match="repeat 1 appears twice"):
        table.validate_runs(load_all(tmp_path))


def test_refuses_missing_metrics_and_exits_nonzero(tmp_path, capsys):
    run_dir = make_run(tmp_path, "c3_rag", 1)
    (run_dir / "metrics.json").unlink()
    assert table.main(["--results-dir", str(tmp_path), "--out", str(tmp_path / "out")]) == 1
    assert "incomplete, no metrics.json" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
