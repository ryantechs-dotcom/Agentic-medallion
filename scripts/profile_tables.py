#!/usr/bin/env python
"""Bronze column profile of the whole project database (tracker task 7).

    python scripts/profile_tables.py            # writes results/<date>_p3_profile/

Writes column_profile.csv (one row per column: type, nulls, distinct, min/max, top values,
NHANES special codes) plus config.json (run log format, docs/contracts.md section 9).
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import date, datetime, timezone

from medrag import db
from medrag.config import PROJECT_ROOT, load_config
from medrag.corpus.chunking import load_records
from medrag_p3.bronze_profile import COLUMNS, profile_database


def git_commit() -> str:
    proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                          text=True, cwd=PROJECT_ROOT, check=False)
    return proc.stdout.strip() or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    config = load_config()
    run_dir = (PROJECT_ROOT / config["paths"]["results_dir"]
               / f"{date.today():%Y-%m-%d}_p3_profile")
    if run_dir.exists() and not args.overwrite:
        print(f"{run_dir.name} exists; add --overwrite to replace it.", file=sys.stderr)
        return 1

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = json.loads((PROJECT_ROOT / "corpus" / "corpus_v1.manifest.json").read_text())
    codebook = load_records(PROJECT_ROOT / config["paths"]["corpus_file"])
    con = db.connect()
    try:
        rows = profile_database(con, config["profile"]["top_k"], codebook)
    finally:
        con.close()

    run_dir.mkdir(parents=True, exist_ok=True)
    run_config = {**config, "condition": "profile", "git_commit": git_commit(), "prompts": {},
                  "corpus_sha256": manifest["sha256"], "snapshot": "v1", "split": None,
                  "started_at": started, "n_columns": len(rows)}
    (run_dir / "config.json").write_text(json.dumps(run_config, indent=2, sort_keys=True) + "\n",
                                         encoding="utf-8")
    with (run_dir / "column_profile.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    n_tables = len({(row["schema"], row["table"]) for row in rows})
    print(f"{run_dir.name}: {len(rows)} columns in {n_tables} tables")
    return 0


if __name__ == "__main__":
    sys.exit(main())
