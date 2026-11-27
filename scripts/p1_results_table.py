#!/usr/bin/env python
"""Build the final P1 metrics table (mean and range over repeats) from the test-split runs.

    python scripts/p1_results_table.py
    python scripts/p1_results_table.py --results-dir results --out results/my_summary

Reads every run folder matching `*_p1_*_test_r<N>` under --results-dir (config.json,
outputs.jsonl and a judged metrics.json). The condition comes from config.json, the repeat
number N from the folder name. Refuses (exit 1) unless all runs share one git commit, none is
dirty (answers or judgments), all are split=test without a limit, all are complete (metrics.json
present, an answer for every question in the split) and fully judged, and no condition has the
same repeat number twice. Writes results/<YYYY-MM-DD>_p1_test_summary/ with
    summary.json    per-condition mean/min/max/n_repeats, per-repeat values and the n behind
                    each value, plus every source folder with its git commit and metrics.json
                    sha256
    table.md        rows = metrics, columns = conditions, cells "mean (min–max)"
Answerable accuracy is the comparison row: C2 skips the unanswerable questions, so overall
metrics cover a different question set for C2 and are shown with their n.
Every number comes from the metrics.json files; nothing is typed by hand.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean

from medrag.config import PROJECT_ROOT, load_config
from medrag.evaluation.runner import CONDITIONS, write_json

RUN_GLOB = "*_p1_*_test_r*"
REPEAT_RE = re.compile(r"_r(\d+)$")
GROUPS = ("qtype", "needs_data")    # breakdowns reported as accuracy rows


class RunSetError(ValueError):
    """The run folders do not form one clean, comparable set of final runs."""


def parse_repeat(folder_name: str) -> int:
    """Repeat number from a run folder name ending in `_r<N>`."""
    match = REPEAT_RE.search(folder_name)
    if not match:
        raise RunSetError(f"{folder_name}: name does not end in _r<N>")
    return int(match.group(1))


def load_run(run_dir: Path) -> dict:
    """One run folder: config.json, metrics.json (None if missing), their identity and the
    number of answers in outputs.jsonl."""
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    metrics_path, outputs_path = run_dir / "metrics.json", run_dir / "outputs.jsonl"
    metrics_bytes = metrics_path.read_bytes() if metrics_path.exists() else None
    n_outputs = 0
    if outputs_path.exists():
        with outputs_path.open(encoding="utf-8") as f:
            n_outputs = sum(1 for line in f if line.strip())
    return {
        "folder": run_dir.name,
        "config": config,
        "metrics": json.loads(metrics_bytes) if metrics_bytes is not None else None,
        "metrics_sha256": (hashlib.sha256(metrics_bytes).hexdigest()
                           if metrics_bytes is not None else None),
        "n_outputs": n_outputs,
    }


def run_problems(run: dict) -> list[str]:
    """Reasons one run cannot be part of the final table (empty list = fine)."""
    name, config, metrics = run["folder"], run["config"], run["metrics"]
    problems = []
    if config.get("git_dirty") is not False:
        problems.append(f"{name}: git_dirty is {config.get('git_dirty')!r}, not false")
    if config.get("split") != "test":
        problems.append(f"{name}: split is {config.get('split')!r}, not 'test'")
    if config.get("limit") is not None:
        problems.append(f"{name}: limit is {config['limit']!r}; final runs use no limit")
    if config.get("condition", {}).get("name") not in CONDITIONS:
        problems.append(f"{name}: unknown condition {config.get('condition')!r}")
    if metrics is None:
        return problems + [f"{name}: incomplete, no metrics.json"]
    expected = metrics.get("n_questions_in_split")
    if not isinstance(expected, int) or run["n_outputs"] < expected:
        problems.append(f"{name}: incomplete, outputs.jsonl has {run['n_outputs']} answers "
                        f"for n_questions_in_split={expected!r}")
    overall = metrics.get("overall", {})
    if overall.get("accuracy") is None:
        problems.append(f"{name}: metrics.json has no accuracy (run not judged)")
    elif overall.get("n_judged") != overall.get("n"):
        problems.append(f"{name}: only {overall.get('n_judged')}/{overall.get('n')} "
                        "questions judged (errors or unfinished judging)")
    if metrics.get("judge", {}).get("git_dirty") is not False:
        problems.append(f"{name}: judged with git_dirty "
                        f"{metrics.get('judge', {}).get('git_dirty')!r}, not false")
    return problems


def validate_runs(runs: list[dict]) -> None:
    """Raise RunSetError listing every reason the runs are not one clean final set."""
    if not runs:
        raise RunSetError(f"no run folders matching {RUN_GLOB}")
    problems = [problem for run in runs for problem in run_problems(run)]
    commits = sorted({str(run["config"].get("git_commit")) for run in runs})
    if len(commits) > 1:
        problems.append(f"runs disagree on git_commit: {', '.join(commits)}")
    judge_prompts = sorted({str(run["metrics"].get("judge", {}).get("prompt", {}).get("sha256"))
                            for run in runs if run["metrics"] is not None})
    if len(judge_prompts) > 1:
        problems.append(f"runs were judged with different prompts: {', '.join(judge_prompts)}")
    seen: dict[tuple, str] = {}
    for run in runs:
        key = (run["config"].get("condition", {}).get("name"), run["repeat"])
        if key in seen:
            problems.append(f"{key[0]} repeat {key[1]} appears twice: {seen[key]}, "
                            f"{run['folder']}")
        seen[key] = run["folder"]
    if problems:
        raise RunSetError("refusing to build the table:\n  " + "\n  ".join(problems))


def metric_specs(runs: list[dict]) -> list[dict]:
    """Table rows: key, label, path into metrics.json, path to the n behind the value, decimals
    and whether the cell always shows its n.

    The first row (answerable accuracy) is the comparison row: every condition answers the
    same answerable questions, while C2 skips the unanswerable ones, so overall rows can have
    a different n per condition.
    """
    specs = [
        {"key": "answerable_accuracy", "label": "**Accuracy, answerable (comparison row)**",
         "path": ["answerable", "accuracy"], "n_path": ["answerable", "n"]},
        {"key": "accuracy", "label": "Accuracy, overall (n differs, see note)",
         "path": ["overall", "accuracy"], "show_n": True},
        {"key": "hallucination_rate", "label": "Hallucination rate (unanswerable)",
         "path": ["overall", "hallucination_rate"],
         "n_path": ["by_qtype", "unanswerable", "n"]},
        {"key": "abstain_rate", "label": "Abstain rate (overall)",
         "path": ["overall", "abstain_rate"]},
    ]
    for group in GROUPS:
        names = sorted({name for run in runs for name in run["metrics"].get(f"by_{group}", {})})
        specs += [{"key": f"accuracy_{group}_{name}", "label": f"Accuracy, {group} = {name}",
                   "path": [f"by_{group}", name, "accuracy"],
                   "n_path": [f"by_{group}", name, "n"]} for name in names]
    specs += [
        {"key": "mean_input_tokens", "label": "Mean input tokens",
         "path": ["overall", "mean_input_tokens"], "digits": 0},
        {"key": "mean_latency_s", "label": "Mean latency (s)",
         "path": ["overall", "mean_latency_s"], "digits": 1},
        {"key": "n", "label": "n questions (overall)", "path": ["overall", "n"], "digits": 0,
         "collapse": True},
        {"key": "answerable_n", "label": "n questions (answerable)",
         "path": ["answerable", "n"], "digits": 0, "collapse": True},
    ]
    return [{"digits": 3, "collapse": False, "show_n": False, "n_path": ["overall", "n"],
             **spec} for spec in specs]


def lookup(metrics: dict, path: list[str]) -> float | None:
    """Value at `path` in a metrics dict; None if any step is missing."""
    value = metrics
    for step in path:
        if not isinstance(value, dict) or step not in value:
            return None
        value = value[step]
    return value


def describe(values: list[float | None], ns: list[int | None]) -> dict:
    """mean/min/max over the non-missing values (None if all are missing), with the n behind
    each repeat's value."""
    present = [v for v in values if v is not None]
    return {"mean": mean(present) if present else None,
            "min": min(present) if present else None,
            "max": max(present) if present else None,
            "n_repeats": len(present), "values": values, "n_values": ns}


def aggregate(runs: list[dict]) -> dict:
    """Per-condition statistics of every metric spec, in CONDITIONS order."""
    specs = metric_specs(runs)
    conditions = {}
    for condition in CONDITIONS:
        mine = sorted((run for run in runs if run["config"]["condition"]["name"] == condition),
                      key=lambda run: run["repeat"])
        if not mine:
            continue
        conditions[condition] = {
            "n_repeats": len(mine),
            "repeats": [run["repeat"] for run in mine],
            "folders": [run["folder"] for run in mine],
            "metrics": {spec["key"]: describe([lookup(run["metrics"], spec["path"])
                                               for run in mine],
                                              [lookup(run["metrics"], spec["n_path"])
                                               for run in mine])
                        for spec in specs},
        }
    return {"metric_specs": specs, "conditions": conditions}


def fmt(value: float | None, digits: int) -> str:
    return "n/a" if value is None else f"{value:,.{digits}f}"


def n_label(stats: dict) -> str:
    """"n=47", or "n=45–47" if the repeats differ."""
    ns = sorted({n for n in stats["n_values"] if n is not None})
    if not ns:
        return "n=?"
    return f"n={ns[0]}" if len(ns) == 1 else f"n={ns[0]}–{ns[-1]}"


def cell(stats: dict, digits: int, collapse: bool = False, show_n: bool = False) -> str:
    """"mean (min–max)"; with `collapse`, just the value when every repeat agrees; with
    `show_n`, followed by ", n=N"."""
    if stats["mean"] is None:
        return "n/a"
    if collapse and stats["min"] == stats["max"]:
        text = fmt(stats["mean"], digits)
    else:
        text = (f"{fmt(stats['mean'], digits)} "
                f"({fmt(stats['min'], digits)}–{fmt(stats['max'], digits)})")
    return f"{text}, {n_label(stats)}" if show_n else text


def row_cells(conditions: dict, spec: dict) -> list[str]:
    """One table row. The n is shown when the spec asks for it or when it differs between
    conditions (the values then cover different question sets)."""
    stats = [conditions[c]["metrics"][spec["key"]] for c in conditions]
    labels = {n_label(s) for s in stats if s["mean"] is not None}
    show_n = not spec["collapse"] and (spec["show_n"] or len(labels) > 1)
    return [cell(s, spec["digits"], spec["collapse"], show_n) for s in stats]


def render_table(summary: dict) -> str:
    """table.md: one row per metric, one column per condition."""
    conditions = summary["conditions"]
    names = list(conditions)
    lines = [
        "# P1 test-split results",
        "",
        f"Generated {summary['generated_at']} by `scripts/p1_results_table.py` from "
        f"{len(summary['runs'])} run folders at git commit `{summary['git_commit']}`. "
        "Cells are mean (min–max) over repeats.",
        "",
        "| Metric | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
        "| Repeats | " + " | ".join(str(conditions[c]["n_repeats"]) for c in names) + " |",
    ]
    for spec in summary["metric_specs"]:
        lines.append(f"| {spec['label']} | " + " | ".join(row_cells(conditions, spec)) + " |")
    lines += ["",
              "Compare conditions on the first row: c2_long_context skips the unanswerable "
              "questions, so overall rows cover a different question set per condition (their "
              "n is shown where it differs) and are not comparable.",
              "",
              "Notes:",
              "- n/a = the metric does not apply to that condition (c2_long_context has no "
              "unanswerable questions, so no hallucination rate).",
              "", "Source runs (folder, git commit, metrics.json sha256):", ""]
    lines += [f"- `{run['folder']}` `{run['git_commit']}` `{run['metrics_sha256']}`"
              for run in summary["runs"]]
    return "\n".join(lines) + "\n"


def build_summary(runs: list[dict], results_dir: Path, generated_at: str) -> dict:
    """summary.json content: aggregates plus the identity of every source run."""
    order = {name: i for i, name in enumerate(CONDITIONS)}
    ordered = sorted(runs, key=lambda r: (order[r["config"]["condition"]["name"]], r["repeat"]))
    return {
        "generated_at": generated_at,
        "results_dir": str(results_dir),
        "git_commit": runs[0]["config"]["git_commit"],
        "runs": [{"folder": run["folder"], "condition": run["config"]["condition"]["name"],
                  "repeat": run["repeat"], "git_commit": run["config"]["git_commit"],
                  "judge_git_commit": run["metrics"]["judge"].get("git_commit"),
                  "metrics_sha256": run["metrics_sha256"]}
                 for run in ordered],
        **aggregate(runs),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--results-dir", type=Path,
                        default=PROJECT_ROOT / load_config()["paths"]["results_dir"])
    parser.add_argument("--out", type=Path, default=None,
                        help="output folder (default: <results-dir>/<today>_p1_test_summary)")
    args = parser.parse_args(argv)
    run_dirs = sorted(d for d in args.results_dir.glob(RUN_GLOB) if d.is_dir())
    try:
        runs = [{**load_run(d), "repeat": parse_repeat(d.name)} for d in run_dirs]
        validate_runs(runs)
    except (RunSetError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = build_summary(runs, args.results_dir, generated_at)
    out = args.out or args.results_dir / f"{date.today():%Y-%m-%d}_p1_test_summary"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "summary.json", summary)
    (out / "table.md").write_text(render_table(summary), encoding="utf-8", newline="\n")
    print(f"{len(runs)} runs -> {out}")
    # ASCII only here: Windows consoles are often cp1252
    for condition, stats in summary["conditions"].items():
        answerable = stats["metrics"]["answerable_accuracy"]
        overall = stats["metrics"]["accuracy"]
        print(f"  {condition}: repeats {stats['repeats']} answerable mean "
              f"{answerable['mean']:.3f} (min {answerable['min']:.3f}, "
              f"max {answerable['max']:.3f}, n {answerable['n_values']}); overall mean "
              f"{overall['mean']:.3f} (n {overall['n_values']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
