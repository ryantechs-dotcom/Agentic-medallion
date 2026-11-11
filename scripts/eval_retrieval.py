#!/usr/bin/env python
"""Retrieval-only evaluation (recall@k, MRR) of one retriever on the P1 eval set.

    python scripts/eval_retrieval.py --kind hybrid            # dev split
    python scripts/eval_retrieval.py --kind bm25 --chunking fixed
    python scripts/eval_retrieval.py --kind bm25 --bm25-stopwords none

Scores every question that has a gold_doc (unanswerable questions have none) with the gold
matching rule in docs/contracts.md. Writes results/<date>_p1_retrieval_<kind>[_fixed][_nostop]/
{config.json, outputs.jsonl, metrics.json} (run log format, contracts section 9). The test
split is for final runs only and is refused unless --confirm-test is given.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date, datetime, timezone

from medrag import contracts
from medrag.config import PROJECT_ROOT, load_config
from medrag.evaluation.metrics import by_group, first_hit_rank
from medrag.evaluation.runner import git_commit
from medrag.retrieval import KINDS, build_retriever, load_chunks

KS = (1, 3, 5, 10)


def load_questions(config: dict, split: str) -> list[dict]:
    """Eval rows of one split that have a gold document."""
    with (PROJECT_ROOT / config["paths"]["eval_file"]).open(encoding="utf-8", newline="") as f:
        return [row for row in csv.DictReader(f) if row["split"] == split and row["gold_doc"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--kind", choices=KINDS, default=None, help="default: retrieval.kind")
    parser.add_argument("--chunking", choices=("structure", "fixed"), default=None)
    parser.add_argument("--bm25-stopwords", choices=("english", "none"), default=None)
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--confirm-test", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.split == "test" and not args.confirm_test:
        print("The test split is for final runs only; add --confirm-test.", file=sys.stderr)
        return 1

    config = load_config()
    if args.chunking:
        config["retrieval"]["chunking"] = args.chunking
    if args.bm25_stopwords:
        config["retrieval"]["bm25_stopwords"] = args.bm25_stopwords
    kind = args.kind or config["retrieval"]["kind"]
    suffix = "" if config["retrieval"]["chunking"] == "structure" else "_fixed"
    if kind != "dense" and config["retrieval"]["bm25_stopwords"] == "none":
        suffix += "_nostop"
    run_dir = (PROJECT_ROOT / config["paths"]["results_dir"]
               / f"{date.today():%Y-%m-%d}_p1_retrieval_{kind}{suffix}")
    if run_dir.exists() and not args.overwrite:
        print(f"{run_dir.name} exists; add --overwrite to replace it.", file=sys.stderr)
        return 1

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = json.loads((PROJECT_ROOT / "corpus" / "corpus_v1.manifest.json").read_text())
    chunks = load_chunks(config)
    retriever = build_retriever(config, kind, chunks=chunks)
    questions = load_questions(config, args.split)
    depth = max(KS)

    outputs, ranks = [], []
    for row in questions:
        start = time.perf_counter()
        retrieved = retriever.search(row["question"], depth)
        latency = time.perf_counter() - start
        ranks.append(first_hit_rank(retrieved, row["gold_doc"], row["gold_section"]))
        outputs.append(contracts.validate({
            "qid": row["qid"], "answer": None, "citations": [], "retrieved": retrieved,
            "tool_calls": [], "usage": {}, "latency_s": round(latency, 4), "error": None,
            "first_hit_rank": ranks[-1],
        }, "run_output"))

    metrics = by_group(questions, ranks, ("qtype", "source"), KS)
    metrics["n_chunks"] = len(chunks)
    run_config = {**config, "condition": f"retrieval_{kind}{suffix}", "kind": kind,
                  "git_commit": git_commit(), "prompts": {}, "corpus_sha256": manifest["sha256"],
                  "snapshot": "v1", "split": args.split, "started_at": started, "ks": list(KS)}

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(json.dumps(run_config, indent=2, sort_keys=True) + "\n",
                                         encoding="utf-8")
    with (run_dir / "outputs.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for output in outputs:
            f.write(json.dumps(output, sort_keys=True, ensure_ascii=False) + "\n")
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8")
    overall = metrics["overall"]
    print(f"{run_dir.name}: n={overall['n']} chunks={len(chunks)} "
          + " ".join(f"recall@{k}={overall[f'recall@{k}']:.3f}" for k in KS)
          + f" mrr={overall['mrr']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
