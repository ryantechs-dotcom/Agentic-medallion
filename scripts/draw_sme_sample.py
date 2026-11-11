#!/usr/bin/env python
"""Draw the SME agreement sample from the frozen P1 eval set (docs/PROBLEM1_PLAN.md).

    python scripts/draw_sme_sample.py            # writes eval/sme_agreement_sample.csv

Draws `--per-type` questions (default 5) of each qtype from both splits with a fixed seed, so
the sample is reproducible. The file has no gold answers: the SME (Skylar) answers
independently in the empty columns, and agreement with the gold answers is reported later.
Refuses to overwrite an existing sample, since it is drawn once.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import defaultdict

from medrag.config import PROJECT_ROOT, load_config

OUT = PROJECT_ROOT / "eval" / "sme_agreement_sample.csv"
COLUMNS = ["qid", "split", "source", "qtype", "question", "sme_answer", "sme_doc",
           "sme_section", "sme_notes"]


def draw(rows: list[dict], per_type: int, seed: int) -> list[dict]:
    """`per_type` random rows per qtype (all of them if fewer), sorted by qtype then qid."""
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: r["qid"]):
        by_type[row["qtype"]].append(row)
    rng = random.Random(seed)
    sample = []
    for qtype in sorted(by_type):
        group = by_type[qtype]
        sample += sorted(rng.sample(group, min(per_type, len(group))), key=lambda r: r["qid"])
    return sample


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--per-type", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if OUT.exists():
        print(f"{OUT.name} exists; the sample is drawn once.", file=sys.stderr)
        return 1
    eval_file = PROJECT_ROOT / load_config()["paths"]["eval_file"]
    with eval_file.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    sample = draw(rows, args.per_type, args.seed)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sample)
    print(f"{OUT.name}: {len(sample)} questions "
          f"({args.per_type} per qtype, seed {args.seed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
