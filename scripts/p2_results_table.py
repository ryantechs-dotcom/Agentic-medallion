#!/usr/bin/env python
"""Build the final P2 metrics table (#18) from the run folders of one split.

    python scripts/p2_results_table.py                      # test split, real runs only
    python scripts/p2_results_table.py --split dev --include-fake   # dry-run check
    python scripts/p2_results_table.py --allow-errors       # keep runs with failed tables

Reads every `results/*_p2_<arch>_<split>_r<repeat>/` folder written by `python -m
medrag_p2.run` (config.json + metrics.json; `_fake` folders only with --include-fake) and
writes `results/<YYYY-MM-DD>_p2_<split>_summary/` (`--out` overrides):
- summary.json: per architecture, the mean, min, max, n and per-repeat values of every
  metric (overall mapping metrics, evidence_valid_share, verifier rates for multi, cost), a
  by_table breakdown, the source folders, git commit, ground-truth sha256 and the sha256 of
  each metrics.json, so every number traces back to a run;
- table.md: rows = metrics, columns = single | multi, cells "mean (min-max)" to 3 decimals.
Metrics that are None in a repeat (e.g. precision when a run made no specs) are left out of
that metric's mean, min and max; `n` says how many repeats it covers.

The runs must be comparable, otherwise the script refuses (exit code 2): one git commit, one
ground truth (sha256), one backend, top_k and table list; no run with uncommitted changes
(git_dirty, unless --allow-dirty); one folder per (architecture, repeat); no table that
failed (cost.tables_with_error, unless --allow-errors). Both flags are recorded in the output.

Cleaning-rule correctness is not scored by medrag_p2.scoring (it needs a judge; see that
module's docstring), so it is not in this table.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from medrag.config import PROJECT_ROOT, load_config
from medrag.evaluation.runner import write_json

ARCH_ORDER = ("single", "multi")
OVERALL_KEYS = ("n_columns", "n_specs", "precision", "recall", "f1", "precision_lenient",
                "recall_lenient", "f1_lenient", "top1_accuracy", "top1_accuracy_lenient",
                "top{k}_accuracy", "top{k}_accuracy_lenient", "mapping_type_accuracy")
EVIDENCE_KEYS = ("evidence_valid_share",)
VERIFIER_KEYS = ("verifier_catch_rate", "n_wrong_initial_specs", "verifier_false_alarm_rate",
                 "n_right_initial_specs")
COST_KEYS = ("model_calls", "tool_calls", "blocked_tool_calls", "input_tokens",
             "output_tokens", "latency_s", "cost_usd_estimate", "needs_human_specs",
             "dropped_specs")
COST_LIST_KEYS = ("tables_with_error", "tables_with_warning")   # reported as counts
OPTIONAL_COST_KEYS = ("tables_with_warning",)   # added by PR #21; absent in older runs
BY_TABLE_KEYS = ("f1", "f1_lenient", "top1_accuracy")
SECTIONS = {"overall": "Mapping (overall, all tables of the split)",
            "evidence": "Evidence", "verifier": "Verifier (multi-agent only)",
            "cost": "Cost (per run, summed over tables)"}
DECIMALS = 3


class RunSetError(ValueError):
    """The run folders can't be combined into one table."""


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_run_dirs(results_dir: Path, split: str, include_fake: bool) -> list[Path]:
    """Run folders of `split` (`*_p2_*_<split>_r*`), sorted; `_fake` ones only if asked."""
    dirs = [p for p in sorted(results_dir.glob(f"*_p2_*_{split}_r*")) if p.is_dir()]
    return [p for p in dirs if include_fake or not p.name.endswith("_fake")]


def load_run(run_dir: Path) -> dict:
    """config.json and metrics.json of one run folder, plus the metrics.json sha256."""
    missing = [n for n in ("config.json", "metrics.json") if not (run_dir / n).is_file()]
    if missing:
        raise RunSetError(f"{run_dir.name}: missing {', '.join(missing)} (incomplete run?)")
    raw = (run_dir / "metrics.json").read_bytes()
    return {"folder": run_dir.name,
            "config": json.loads((run_dir / "config.json").read_text(encoding="utf-8")),
            "metrics": json.loads(raw), "metrics_sha256": file_sha256(raw)}


def overall_keys(top_k: int) -> list[str]:
    return [key.format(k=top_k) for key in OVERALL_KEYS]


def shared_value(runs: list[dict], what: str, get) -> tuple[object, list[str]]:
    """The value `get(run)` if all runs agree on it, else (None, [problem])."""
    values = {}
    for run in runs:
        values.setdefault(json.dumps(get(run), sort_keys=True), []).append(run["folder"])
    if len(values) == 1:
        return get(runs[0]), []
    detail = "; ".join(f"{value}: {', '.join(folders)}" for value, folders in values.items())
    return None, [f"runs disagree on {what} ({detail})"]


def missing_keys(run: dict, top_k: int) -> list[str]:
    """Metric keys this script reads that the run's metrics.json lacks."""
    metrics, arch = run["metrics"], run["config"].get("architecture")
    need = [f"overall.{k}" for k in overall_keys(top_k) if k not in metrics.get("overall", {})]
    need += [k for k in EVIDENCE_KEYS if k not in metrics]
    if arch == "multi":
        need += [k for k in VERIFIER_KEYS if k not in metrics]
    cost = metrics.get("cost", {})
    need += [f"cost.{k}" for k in COST_KEYS + COST_LIST_KEYS
             if k not in cost and k not in OPTIONAL_COST_KEYS]
    for table, by in metrics.get("by_table", {}).items():
        need += [f"by_table.{table}.{k}" for k in BY_TABLE_KEYS if k not in by]
    return need


def validate_runs(runs: list[dict], split: str, *, allow_errors: bool = False,
                  allow_dirty: bool = False) -> dict:
    """Check the runs are comparable; return what they share. Raises RunSetError."""
    if not runs:
        raise RunSetError(f"no P2 run folders for split {split!r}")
    problems = []
    shared = {}
    for what, get in (
            ("git_commit", lambda r: r["config"].get("git_commit")),
            ("ground_truth sha256", lambda r: r["config"].get("ground_truth", {}).get("sha256")),
            ("backend_name", lambda r: r["config"].get("backend_name")),
            ("p2.top_k", lambda r: r["config"].get("p2", {}).get("top_k")),
            ("tables", lambda r: sorted(r["config"].get("tables", [])))):
        shared[what], found = shared_value(runs, what, get)
        problems += found
    no_gt = [r["folder"] for r in runs if not r["config"].get("ground_truth", {}).get("sha256")]
    if no_gt:
        problems.append(f"no ground_truth sha256 in config.json: {', '.join(no_gt)}")
    seen: dict[tuple, str] = {}
    for run in runs:
        config, name = run["config"], run["folder"]
        if config.get("split") != split:
            problems.append(f"{name}: config split is {config.get('split')!r}, not {split!r}")
        if config.get("architecture") not in ARCH_ORDER:
            problems.append(f"{name}: unknown architecture {config.get('architecture')!r}")
        if not isinstance(config.get("repeat"), int):
            problems.append(f"{name}: repeat is {config.get('repeat')!r}, not an integer")
        key = (config.get("architecture"), config.get("repeat"))
        if key in seen:
            problems.append(f"duplicate (architecture, repeat) {key}: {seen[key]} and {name}")
        seen.setdefault(key, name)
        if config.get("git_dirty") is not False and not allow_dirty:
            state = ("git state unknown" if config.get("git_dirty") is None
                     else "made with uncommitted changes")
            problems.append(f"{name}: {state} (git_dirty); pass --allow-dirty to keep it")
        failed = run["metrics"].get("cost", {}).get("tables_with_error") or []
        if failed and not allow_errors:
            problems.append(f"{name}: tables with errors {failed}; pass --allow-errors to "
                            "keep it")
        if isinstance(shared["p2.top_k"], int):
            lacking = missing_keys(run, shared["p2.top_k"])
            if lacking:
                problems.append(f"{name}: metrics.json lacks {', '.join(lacking)}")
    if problems:
        raise RunSetError("refusing to build the table:\n- " + "\n- ".join(problems))
    shared["ground_truth"] = runs[0]["config"]["ground_truth"]
    return shared


def stats(values: list) -> dict:
    """Mean, min, max over the non-None values; `n` counts them; `values` keeps all."""
    present = [v for v in values if v is not None]
    if not present:
        return {"mean": None, "min": None, "max": None, "n": 0, "values": values}
    return {"mean": round(statistics.fmean(present), 6), "min": min(present),
            "max": max(present), "n": len(present), "values": values}


def run_values(run: dict, top_k: int) -> dict[str, dict]:
    """One run's metrics by section (list-valued cost entries become counts)."""
    metrics = run["metrics"]
    cost = metrics["cost"]
    values = {"overall": {k: metrics["overall"][k] for k in overall_keys(top_k)},
              "evidence": {k: metrics[k] for k in EVIDENCE_KEYS},
              "cost": {k: cost[k] for k in COST_KEYS}}
    values["cost"].update({k: len(cost[k]) for k in COST_LIST_KEYS if k in cost})
    if run["config"]["architecture"] == "multi":
        values["verifier"] = {k: metrics[k] for k in VERIFIER_KEYS}
    return values


def aggregate_arch(runs: list[dict], top_k: int, tables: list[str]) -> dict:
    """Stats per section and metric, and per table, over the repeats of one architecture."""
    runs = sorted(runs, key=lambda r: r["config"]["repeat"])
    per_run = [run_values(r, top_k) for r in runs]
    metrics = {}
    for section in SECTIONS:
        keys = list(dict.fromkeys(k for v in per_run for k in v.get(section, {})))
        if keys:
            metrics[section] = {k: stats([v[section].get(k) for v in per_run]) for k in keys}
    by_table = {t: {k: stats([r["metrics"]["by_table"].get(t, {}).get(k) for r in runs])
                    for k in BY_TABLE_KEYS} for t in tables}
    return {"n_repeats": len(runs), "repeats": [r["config"]["repeat"] for r in runs],
            "folders": [r["folder"] for r in runs], "metrics": metrics, "by_table": by_table}


def build_summary(runs: list[dict], split: str, *, allow_errors: bool = False,
                  allow_dirty: bool = False, include_fake: bool = False) -> dict:
    """summary.json content: validated, aggregated runs of one split."""
    shared = validate_runs(runs, split, allow_errors=allow_errors, allow_dirty=allow_dirty)
    archs = [a for a in ARCH_ORDER if any(r["config"]["architecture"] == a for r in runs)]
    return {
        "split": split, "git_commit": shared["git_commit"],
        "ground_truth": shared["ground_truth"], "backend_name": shared["backend_name"],
        "top_k": shared["p2.top_k"], "tables": shared["tables"],
        "allow_errors": allow_errors, "allow_dirty": allow_dirty, "include_fake": include_fake,
        "not_scored": ["cleaning-rule correctness (needs a judge; see medrag_p2/scoring.py)"],
        "runs": [{"folder": r["folder"], "architecture": r["config"]["architecture"],
                  "repeat": r["config"]["repeat"], "git_dirty": r["config"].get("git_dirty"),
                  "tables_with_error": r["metrics"]["cost"]["tables_with_error"],
                  "metrics_sha256": r["metrics_sha256"]}
                 for r in sorted(runs, key=lambda r: (ARCH_ORDER.index(
                     r["config"]["architecture"]), r["config"]["repeat"]))],
        "architectures": {a: aggregate_arch([r for r in runs
                                             if r["config"]["architecture"] == a],
                                            shared["p2.top_k"], shared["tables"])
                          for a in archs},
    }


def cell(stat: dict | None, n_repeats: int) -> str:
    """'mean (min–max)' to DECIMALS places; 'n/a' if never defined, '—' if not applicable."""
    if stat is None:
        return "—"
    if stat["n"] == 0:
        return "n/a"
    mean, low, high = (f"{stat[k]:.{DECIMALS}f}" for k in ("mean", "min", "max"))
    text = f"{mean} ({low}–{high})"
    return text + (f" n={stat['n']}" if stat["n"] < n_repeats else "")


def md_table(rows: list[tuple[str, list[str]]], archs: list[str]) -> list[str]:
    lines = ["| metric | " + " | ".join(archs) + " |", "|---|" + "---|" * len(archs)]
    return lines + [f"| {label} | " + " | ".join(cells) + " |" for label, cells in rows]


def render_markdown(summary: dict) -> str:
    """table.md: one table per section, rows = metrics, columns = architectures."""
    archs = [a for a in ARCH_ORDER if a in summary["architectures"]]   # JSON sorts keys
    by_arch = summary["architectures"]
    gt = summary["ground_truth"]
    lines = [f"# P2 results, {summary['split']} split", "",
             "Generated by `scripts/p2_results_table.py` from the run folders below; every "
             "number comes from their metrics.json (sha256 in summary.json).", "",
             f"- git commit: `{summary['git_commit']}`",
             f"- ground truth: `{gt['file']}` (sha256 `{gt['sha256']}`)",
             f"- backend: `{summary['backend_name']}`; tables: "
             + ", ".join(f"`{t}`" for t in summary["tables"]),
             f"- flags: allow_errors={summary['allow_errors']}, "
             f"allow_dirty={summary['allow_dirty']}, include_fake={summary['include_fake']}"]
    for arch in archs:
        lines.append(f"- {arch}: {by_arch[arch]['n_repeats']} repeats ("
                     + ", ".join(f"`{f}`" for f in by_arch[arch]["folders"]) + ")")
    lines += ["", "Cells: mean (min–max) over repeats. `n=k`: the metric is defined (not None) "
              "in only k repeats. `n/a`: never defined. `—`: not applicable.",
              "Not scored, so not in the table: " + "; ".join(summary["not_scored"]) + "."]
    for section, title in SECTIONS.items():
        keys = list(dict.fromkeys(k for a in archs
                                  for k in by_arch[a]["metrics"].get(section, {})))
        if not keys:
            continue
        rows = [(key, [cell(by_arch[a]["metrics"].get(section, {}).get(key),
                            by_arch[a]["n_repeats"]) for a in archs]) for key in keys]
        lines += ["", f"## {title}", ""] + md_table(rows, archs)
    rows = [(f"{table} {key}", [cell(by_arch[a]["by_table"][table][key],
                                     by_arch[a]["n_repeats"]) for a in archs])
            for table in summary["tables"] for key in BY_TABLE_KEYS]
    lines += ["", "## By table", ""] + md_table(rows, archs)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    config = load_config("p2")
    results = PROJECT_ROOT / config["paths"]["results_dir"]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="test", choices=["dev", "test"])
    parser.add_argument("--results-dir", type=Path, default=results)
    parser.add_argument("--include-fake", action="store_true", help="also read _fake runs")
    parser.add_argument("--allow-errors", action="store_true",
                        help="keep runs with tables in cost.tables_with_error (recorded)")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="keep runs made with uncommitted changes (recorded)")
    parser.add_argument("--out", type=Path, help="output folder (default: results/"
                        "<YYYY-MM-DD>_p2_<split>_summary)")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    out = args.out or results / f"{date.today():%Y-%m-%d}_p2_{args.split}_summary"
    if out.exists() and not args.overwrite:
        print(f"error: {out} exists; pass --overwrite to replace it", file=sys.stderr)
        return 2
    try:
        runs = [load_run(d) for d in find_run_dirs(args.results_dir, args.split,
                                                   args.include_fake)]
        summary = build_summary(runs, args.split, allow_errors=args.allow_errors,
                                allow_dirty=args.allow_dirty, include_fake=args.include_fake)
    except RunSetError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    summary["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "summary.json", summary)
    (out / "table.md").write_text(render_markdown(summary), encoding="utf-8")
    print(out)
    for arch, agg in summary["architectures"].items():
        f1 = agg["metrics"]["overall"]["f1"]
        print(f"{arch}: {agg['n_repeats']} repeats, mean f1 {f1['mean']} (n={f1['n']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
