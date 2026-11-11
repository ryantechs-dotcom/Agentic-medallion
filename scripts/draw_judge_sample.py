#!/usr/bin/env python
"""Blind hand-labeling sample to validate the LLM judge, and its agreement score.

    python scripts/draw_judge_sample.py results/2026-11-10_p1_c1_closed_book results/...
        -> eval/judge_label_sample.csv (fill in human_verdict, then:)
    python scripts/draw_judge_sample.py --score
        -> results/<date>_p1_judge_agreement/{config.json, metrics.json}

The sample takes only answers the judge model graded (rule-scored abstentions need no check),
round-robin over the judge's verdicts so rare verdicts (incorrect, partially_correct) are not
crowded out, with a fixed seed. The sheet does not show the judge's verdict. `--score` looks
the verdicts up again in each run's judgments.jsonl and reports exact agreement, Cohen's kappa
and the confusion matrix. The judge is the same model as the generator (D-next), so this is the
check for self-preference.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from medrag.config import PROJECT_ROOT
from medrag.evaluation.judge import MODEL_VERDICTS
from medrag.evaluation.runner import load_eval_rows, read_jsonl, write_json

SHEET = PROJECT_ROOT / "eval" / "judge_label_sample.csv"
COLUMNS = ["sample_id", "run", "qid", "qtype", "question", "gold_answer", "notes", "answer",
           "human_verdict", "human_notes"]


def model_judged_items(run_dir: Path) -> list[dict]:
    """Answers in one run that the judge model graded, joined with their eval rows."""
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    rows = {row["qid"]: row for row in load_eval_rows(config, config["split"])}
    outputs = {o["qid"]: o for o in read_jsonl(run_dir / "outputs.jsonl")}
    items = []
    for judgment in read_jsonl(run_dir / "judgments.jsonl"):
        if judgment["judged_by"] != "model":
            continue
        row = rows[judgment["qid"]]
        items.append({"run": run_dir.name, "qid": row["qid"], "qtype": row["qtype"],
                      "question": row["question"], "gold_answer": row["gold_answer"],
                      "notes": row["notes"], "answer": outputs[row["qid"]]["answer"],
                      "verdict": judgment["verdict"]})
    return items


def draw(items: list[dict], n: int, seed: int) -> list[dict]:
    """Round-robin over judge verdicts (each group shuffled with `seed`) until n items."""
    rng = random.Random(seed)
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in sorted(items, key=lambda i: (i["run"], i["qid"])):
        groups[item["verdict"]].append(item)
    for group in groups.values():
        rng.shuffle(group)
    order = sorted(groups)
    sample: list[dict] = []
    while len(sample) < n and any(groups.values()):
        for verdict in order:
            if groups[verdict] and len(sample) < n:
                sample.append(groups[verdict].pop())
    return sample


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    """Cohen's kappa for two raters over the same items (None if undefined)."""
    if not a or len(a) != len(b):
        return None
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[label] * count_b[label] for label in set(a) | set(b)) / n ** 2
    return None if expected == 1 else (observed - expected) / (1 - expected)


def score(sheet: Path) -> dict:
    """Agreement between human_verdict and the judge for every labeled row of the sheet."""
    with sheet.open(encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["human_verdict"].strip()]
    bad = [r["sample_id"] for r in rows if r["human_verdict"].strip() not in MODEL_VERDICTS]
    if bad:
        raise ValueError(f"human_verdict must be one of {MODEL_VERDICTS}; check {bad}")
    judge = {}
    for run in {r["run"] for r in rows}:
        for j in read_jsonl(PROJECT_ROOT / "results" / run / "judgments.jsonl"):
            judge[(run, j["qid"])] = j["verdict"]
    human = [r["human_verdict"].strip() for r in rows]
    model = [judge[(r["run"], r["qid"])] for r in rows]
    confusion = Counter(f"human={h} judge={m}" for h, m in zip(human, model))
    return {"n_labeled": len(rows),
            "agreement": sum(h == m for h, m in zip(human, model)) / len(rows) if rows else None,
            "cohen_kappa": cohen_kappa(human, model), "confusion": dict(sorted(confusion.items())),
            "runs": sorted({r["run"] for r in rows})}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("runs", nargs="*", type=Path, help="judged run folders to sample from")
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--score", action="store_true", help="score the filled sheet")
    args = parser.parse_args()
    if args.score:
        metrics = score(SHEET)
        out = PROJECT_ROOT / "results" / f"{date.today():%Y-%m-%d}_p1_judge_agreement"
        out.mkdir(parents=True, exist_ok=True)
        write_json(out / "config.json", {"sheet": SHEET.relative_to(PROJECT_ROOT).as_posix(),
                                         "seed": args.seed})
        write_json(out / "metrics.json", metrics)
        print(f"{out.name}: n={metrics['n_labeled']} agreement={metrics['agreement']} "
              f"kappa={metrics['cohen_kappa']}")
        return 0
    if not args.runs:
        parser.error("give judged run folders, or --score")
    if SHEET.exists():
        print(f"{SHEET.name} exists; the sample is drawn once.", file=sys.stderr)
        return 1
    items = [item for run in args.runs for item in model_judged_items(run)]
    sample = draw(items, args.n, args.seed)
    with SHEET.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for i, item in enumerate(sample, 1):
            writer.writerow({**item, "sample_id": f"J{i:02d}", "human_verdict": "",
                             "human_notes": ""})
    print(f"{SHEET.name}: {len(sample)} answers from {len(args.runs)} runs "
          f"(pool {len(items)}, verdict mix {dict(Counter(i['verdict'] for i in sample))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
