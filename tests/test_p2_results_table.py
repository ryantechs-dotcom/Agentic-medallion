"""scripts/p2_results_table.py: synthetic run folders, plus one fake end-to-end run."""

import json

import pytest

import p2_results_table as prt
from medrag.config import db_path

needs_data = pytest.mark.skipif(not db_path().exists(), reason="data snapshot not unzipped")

TABLES = ["admissions", "patients"]


def pair(f1=0.5, **extra):
    base = {"n_columns": 4, "n_specs": 4, "precision": 0.5, "recall": 0.5, "f1": f1,
            "precision_lenient": 0.75, "recall_lenient": 0.75, "f1_lenient": 0.75,
            "top1_accuracy": 0.5, "top1_accuracy_lenient": 0.75, "top3_accuracy": 0.75,
            "top3_accuracy_lenient": 1.0, "mapping_type_accuracy": 1.0,
            "columns_without_spec": []}
    return {**base, **extra}


def make_run(root, arch, repeat, *, split="test", commit="abc1234", sha="gt1", dirty=False,
             errors=(), overall=None, by_table=None, name=None, warnings=None, **top):
    """Write config.json + metrics.json like medrag_p2.run does; return the folder."""
    folder = root / (name or f"2026-12-01_p2_{arch}_{split}_r{repeat}")
    folder.mkdir(parents=True)
    config = {"architecture": arch, "split": split, "repeat": repeat, "tables": TABLES,
              "git_commit": commit, "git_dirty": dirty, "backend_name": "claude_cli",
              "p2": {"top_k": 3},
              "ground_truth": {"file": "eval/p2/p2_ground_truth.csv", "sha256": sha}}
    cost = {"model_calls": 10, "tool_calls": 20, "tool_calls_by_tool": {},
            "blocked_tool_calls": 0, "input_tokens": 1000, "output_tokens": 100,
            "latency_s": 12.5, "cost_usd_estimate": 0.1, "tables_with_error": list(errors),
            "needs_human_specs": 1, "dropped_specs": 0}
    if warnings is not None:
        cost["tables_with_warning"] = warnings
    metrics = {"overall": overall or pair(),
               "by_table": by_table or {t: pair() for t in TABLES},
               "evidence_valid_share": 0.9, "cost": cost,
               "ground_truth": config["ground_truth"]}
    if arch == "multi":
        metrics.update({"verifier_catch_rate": 0.5, "n_wrong_initial_specs": 2,
                        "verifier_false_alarm_rate": 0.0, "n_right_initial_specs": 2})
    metrics.update(top)
    (folder / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (folder / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return folder


def load_all(root, split="test", include_fake=False):
    return [prt.load_run(d) for d in prt.find_run_dirs(root, split, include_fake)]


def test_aggregates_mean_min_max_and_skips_none(tmp_path):
    for repeat, f1 in ((1, 0.4), (2, 0.6), (3, None)):
        make_run(tmp_path, "single", repeat, overall=pair(f1=f1))
        make_run(tmp_path, "multi", repeat, overall=pair(f1=0.8))
    summary = prt.build_summary(load_all(tmp_path), "test")
    single = summary["architectures"]["single"]
    assert single["n_repeats"] == 3 and single["repeats"] == [1, 2, 3]
    f1 = single["metrics"]["overall"]["f1"]
    assert f1 == {"mean": 0.5, "min": 0.4, "max": 0.6, "n": 2, "values": [0.4, 0.6, None]}
    assert summary["architectures"]["multi"]["metrics"]["overall"]["f1"]["mean"] == 0.8
    assert single["by_table"]["patients"]["f1_lenient"]["mean"] == 0.75
    assert single["metrics"]["cost"]["tables_with_error"]["mean"] == 0
    assert "tables_with_warning" not in single["metrics"]["cost"]
    assert len(summary["runs"]) == 6
    assert all(len(r["metrics_sha256"]) == 64 for r in summary["runs"])
    assert summary["git_commit"] == "abc1234" and summary["ground_truth"]["sha256"] == "gt1"
    md = prt.render_markdown(summary)
    assert "| f1 | 0.500 (0.400–0.600) n=2 | 0.800 (0.800–0.800) |" in md
    assert "| patients top1_accuracy |" in md and "cleaning-rule" in md


def test_all_none_metric_and_warning_counts(tmp_path):
    for repeat in (1, 2):
        make_run(tmp_path, "single", repeat, overall=pair(precision=None),
                 warnings=["patients"] * repeat)
    summary = prt.build_summary(load_all(tmp_path), "test")
    metrics = summary["architectures"]["single"]["metrics"]
    assert metrics["overall"]["precision"]["n"] == 0
    assert metrics["cost"]["tables_with_warning"]["values"] == [1, 2]
    assert "| precision | n/a |" in prt.render_markdown(summary)


def test_verifier_rates_only_for_multi(tmp_path):
    make_run(tmp_path, "single", 1)
    make_run(tmp_path, "multi", 1)
    summary = prt.build_summary(load_all(tmp_path), "test")
    assert "verifier" not in summary["architectures"]["single"]["metrics"]
    multi = summary["architectures"]["multi"]["metrics"]["verifier"]
    assert multi["verifier_catch_rate"]["mean"] == 0.5
    assert "| verifier_catch_rate | — | 0.500 (0.500–0.500) |" in prt.render_markdown(summary)


def test_skips_fake_and_other_splits(tmp_path):
    make_run(tmp_path, "single", 1)
    make_run(tmp_path, "single", 2, name="2026-12-01_p2_single_test_r2_fake")
    make_run(tmp_path, "single", 1, split="dev")
    assert [r["folder"] for r in load_all(tmp_path)] == ["2026-12-01_p2_single_test_r1"]
    assert len(load_all(tmp_path, include_fake=True)) == 2


@pytest.mark.parametrize("second, message", [
    ({"commit": "def5678"}, "git_commit"),
    ({"sha": "gt2"}, "ground_truth sha256"),
    ({"dirty": True}, "git_dirty"),
    ({"errors": ["mimic_demo_v1_0_hosp.transfers"]}, "tables with errors"),
    ({"repeat": 1, "name": "2026-12-02_p2_single_test_r1"}, "duplicate"),
])
def test_refuses_incomparable_runs(tmp_path, second, message):
    make_run(tmp_path, "single", 1)
    make_run(tmp_path, "single", **{"repeat": 2, **second})
    with pytest.raises(prt.RunSetError, match=message):
        prt.build_summary(load_all(tmp_path), "test")


def test_allow_flags_are_recorded(tmp_path):
    make_run(tmp_path, "single", 1, dirty=True, errors=["mimic_demo_v1_0_core.patients"])
    summary = prt.build_summary(load_all(tmp_path), "test", allow_errors=True,
                                allow_dirty=True)
    assert summary["allow_errors"] and summary["allow_dirty"]
    assert summary["runs"][0]["tables_with_error"] == ["mimic_demo_v1_0_core.patients"]
    errors = summary["architectures"]["single"]["metrics"]["cost"]["tables_with_error"]
    assert errors["values"] == [1]


def test_refuses_missing_metric_keys_and_empty(tmp_path):
    with pytest.raises(prt.RunSetError, match="no P2 run folders"):
        prt.build_summary([], "test")
    overall = pair()
    del overall["top3_accuracy"]
    make_run(tmp_path, "single", 1, overall=overall)
    with pytest.raises(prt.RunSetError, match="overall.top3_accuracy"):
        prt.build_summary(load_all(tmp_path), "test")


def test_main_writes_outputs_and_exit_codes(tmp_path, capsys):
    make_run(tmp_path, "single", 1)
    make_run(tmp_path, "multi", 1)
    out = tmp_path / "summary"
    assert prt.main(["--results-dir", str(tmp_path), "--out", str(out)]) == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["split"] == "test" and set(summary["architectures"]) == {"single", "multi"}
    assert (out / "table.md").read_text(encoding="utf-8").startswith("# P2 results, test")
    assert prt.main(["--results-dir", str(tmp_path), "--out", str(out)]) == 2
    make_run(tmp_path, "multi", 2, commit="other")
    assert prt.main(["--results-dir", str(tmp_path), "--out", str(out), "--overwrite"]) == 2
    assert "git_commit" in capsys.readouterr().err


@needs_data
def test_fake_runs_end_to_end(tmp_path):
    from medrag_p2.run import run
    for arch in ("single", "multi"):
        for repeat in (1, 2):
            result = run(arch, "dev", tables=["patients"], repeat=repeat, backend_name="fake",
                         run_dir=tmp_path / f"x_p2_{arch}_dev_r{repeat}_fake")
            run_dir = result[0] if isinstance(result, tuple) else result
            assert (run_dir / "metrics.json").is_file()
    runs = load_all(tmp_path, split="dev", include_fake=True)
    # allow_dirty: the fake runs record the working tree, which may have uncommitted edits.
    summary = prt.build_summary(runs, "dev", allow_dirty=True, include_fake=True)
    assert summary["backend_name"] == "fake" and summary["tables"] == ["patients"]
    for arch in ("single", "multi"):
        agg = summary["architectures"][arch]
        assert agg["n_repeats"] == 2
        assert agg["metrics"]["overall"]["precision"]["n"] == 0     # no specs: None
        assert agg["metrics"]["overall"]["recall"]["mean"] == 0.0
    assert "verifier" in summary["architectures"]["multi"]["metrics"]
    assert "## By table" in prt.render_markdown(summary)


def test_cell_formats_rates_and_counts():
    assert prt.cell(prt.stats([0.5, 0.25, None]), 3) == "0.375 (0.250–0.500) n=2"
    assert prt.cell(prt.stats([21, 22]), 2) == "21.5 (21–22)"
    assert prt.cell(prt.stats([None, None]), 2) == "n/a"
    assert prt.cell(None, 2) == "—"
