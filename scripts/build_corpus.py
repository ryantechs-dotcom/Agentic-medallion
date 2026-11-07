"""Build the RAG corpus JSONL from the frozen data snapshot (tracker task 5).

Reads <data dir>/docs (NHANES codebooks, MIMIC docs, OMOP CDM spec), writes one section-level
record per line to `paths.corpus_file` (configs/base.yaml) plus a manifest with counts and
checksums. No network; the output is byte-identical for the same snapshot.

    python scripts/build_corpus.py           # build and print a summary
    python scripts/build_corpus.py --check   # rebuild in memory, compare with the file on disk
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone

from medrag import contracts
from medrag.config import PROJECT_ROOT, data_dir, load_config
from medrag.corpus.loaders import load_all


def serialize(records: list[dict]) -> bytes:
    """One JSON object per line, sorted keys, UTF-8, `\\n` line endings."""
    lines = [json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records]
    return ("\n".join(lines) + "\n").encode("utf-8")


def git_commit() -> str:
    """Current git commit (with -dirty if the tree has changes), or 'unknown'."""
    try:
        return subprocess.run(["git", "describe", "--always", "--dirty"], cwd=PROJECT_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def manifest(records: list[dict], payload: bytes) -> dict:
    """Counts, text-length stats and provenance for the corpus file."""
    lengths = [len(record["text"]) for record in records]
    snapshot_manifest = data_dir() / "manifest.json"
    return {
        "corpus_version": contracts.CORPUS_VERSION,
        "records": len(records),
        "by_source": dict(sorted(Counter(r["source"] for r in records).items())),
        "by_kind": dict(sorted(Counter(r["kind"] for r in records).items())),
        "text_chars": {"min": min(lengths), "median": statistics.median(lengths),
                       "max": max(lengths)},
        "sha256": hashlib.sha256(payload).hexdigest(),
        "snapshot_manifest_sha256": hashlib.sha256(snapshot_manifest.read_bytes()).hexdigest(),
        "snapshot_generated_at": json.loads(snapshot_manifest.read_text())["generated_at"],
        "git_commit": git_commit(),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="rebuild in memory and compare with the existing corpus file")
    args = parser.parse_args()

    out_path = PROJECT_ROOT / load_config()["paths"]["corpus_file"]
    records = contracts.validate_all(load_all(data_dir()), "corpus_record")
    payload = serialize(records)

    if args.check:
        if not out_path.exists():
            print(f"{out_path} not found - build it first")
            return 1
        same = out_path.read_bytes() == payload
        print(f"{out_path.name}: {'identical' if same else 'DIFFERS from'} rebuild "
              f"({len(records)} records)")
        return 0 if same else 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(payload)
    info = manifest(records, payload)
    manifest_path = out_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {out_path.relative_to(PROJECT_ROOT)}: {info['records']} records, "
          f"sha256 {info['sha256'][:12]}...")
    print("by source:", info["by_source"])
    print("by kind:", info["by_kind"])
    print("text chars (min / median / max):", *info["text_chars"].values())
    return 0


if __name__ == "__main__":
    sys.exit(main())
