#!/usr/bin/env python
"""Judge a P1 run folder: write judgments.jsonl and update metrics.json with accuracy.

    python scripts/judge_p1.py results/2026-11-11_p1_c1_closed_book

Uses the run's own backend and model (config.json) with prompt judge_v1. Abstentions are
scored by rule, without a model call. Safe to re-run: judgments without error are kept.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from medrag.evaluation.runner import judge_run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    if not (args.run_dir / "outputs.jsonl").exists():
        print(f"{args.run_dir} has no outputs.jsonl", file=sys.stderr)
        return 1
    metrics, complete = judge_run(args.run_dir)
    overall = metrics["overall"]

    def fmt(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.3f}"

    print(f"{args.run_dir.name}: judged {overall['n_judged']}/{overall['n']} "
          f"accuracy={fmt(overall['accuracy'])} "
          f"partial_credit={fmt(overall['partial_credit'])} "
          f"hallucination_rate={fmt(overall['hallucination_rate'])}")
    if not complete:
        print("Stopped after repeated judge errors; re-run later to finish.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
