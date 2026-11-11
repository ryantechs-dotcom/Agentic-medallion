#!/usr/bin/env python
"""Run one P1 condition on the eval set and write results/<date>_p1_<condition>[...]/.

    python scripts/run_p1.py --condition c1_closed_book --limit 5     # smoke test (5 dev rows)
    python scripts/run_p1.py --condition c3_rag                       # full dev split
    python scripts/run_p1.py --condition c3_rag --kind bm25 --chunking fixed   # ablation
    python scripts/run_p1.py --condition c3_rag --prompt answer_v2    # permissive grounding
    python scripts/run_p1.py --condition c1_closed_book --backend fake # dry run, no model calls
    python scripts/run_p1.py --condition c3_rag --resume              # after a stop
    python scripts/judge_p1.py results/<run folder>                   # then score it

The model, effort and backend come from configs/base.yaml (D-next). The test split is for final
runs only and is refused unless --confirm-test is given. Run format: docs/contracts.md
section 9.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from medrag.evaluation.runner import CONDITIONS, read_jsonl, run
from medrag.generation.llm import BACKENDS
from medrag.retrieval import KINDS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--condition", choices=CONDITIONS, required=True)
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--limit", type=int, default=None, help="first N rows (smoke test)")
    parser.add_argument("--backend", choices=sorted(BACKENDS), default=None,
                        help="default: generation.backend")
    parser.add_argument("--prompt", default=None,
                        help="answer prompt, e.g. answer_v2 (default: generation.prompt)")
    parser.add_argument("--kind", choices=KINDS, default=None, help="c3 retriever")
    parser.add_argument("--chunking", choices=("structure", "fixed"), default=None)
    parser.add_argument("--run-dir", type=Path, default=None,
                        help="resume a folder from another day")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--confirm-test", action="store_true")
    args = parser.parse_args()

    retrieval = {key: value for key, value in (("kind", args.kind),
                                               ("chunking", args.chunking)) if value}
    try:
        run_dir, complete = run(args.condition, args.split, limit=args.limit,
                                backend_name=args.backend, prompt_name=args.prompt,
                                retrieval=retrieval,
                                run_dir=args.run_dir, resume=args.resume or bool(args.run_dir),
                                overwrite=args.overwrite, confirm_test=args.confirm_test)
    except (PermissionError, FileExistsError, FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    outputs = read_jsonl(run_dir / "outputs.jsonl")
    errors = sum(1 for o in outputs if o["error"])
    print(f"{run_dir.name}: {len(outputs)} outputs, {errors} errors")
    if not complete:
        print("Stopped after repeated errors (seat usage limit?). Last error: "
              f"{outputs[-1]['error']}\nRe-run with --resume later.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
