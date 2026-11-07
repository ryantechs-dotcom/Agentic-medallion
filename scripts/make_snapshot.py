#!/usr/bin/env python3
"""
make_snapshot.py - Freeze data/ into a versioned zip for the team's Google Drive.

Creates, in snapshots/:
  data_snapshot_<version>_<date>.zip
  data_snapshot_<version>_<date>.sha256
  SNAPSHOT_README.md

Usage (from repo root, after scripts/ingest_data.py finished with no failures):
    python scripts/make_snapshot.py --version v1

Teammates verify a download with:
    python scripts/make_snapshot.py --verify path/to/data_snapshot_v1_<date>.zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

CITATIONS = """\
- Johnson, A., Bulgarelli, L., Pollard, T., Celi, L. A., Mark, R., & Horng, S. (2023).
  MIMIC-IV Clinical Database Demo (version 2.2). PhysioNet. https://doi.org/10.13026/dp1f-ex47
- MIMIC-IV Clinical Database Demo (version 1.0). PhysioNet. https://doi.org/10.13026/jwtp-v091
- Kallfelz, M., Tsvetkova, A., Pollard, T., Kwong, M., Lipori, G., Huser, V., Osborn, J., Hao, S.,
  & Williams, A. (2021). MIMIC-IV demo data in the OMOP Common Data Model (version 0.9). PhysioNet.
- Goldberger, A., et al. (2000). PhysioBank, PhysioToolkit, and PhysioNet. Circulation 101(23).
- Centers for Disease Control and Prevention (CDC), National Center for Health Statistics.
  National Health and Nutrition Examination Survey Data, 2017-2018. Hyattsville, MD.
- OHDSI. MIMIC-IV to OMOP ETL. https://github.com/OHDSI/MIMIC
- OHDSI. OMOP Common Data Model v5.3. https://github.com/OHDSI/CommonDataModel
(Check each PhysioNet project page for its exact required citation before submitting.)
"""


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make(data_dir: Path, out_dir: Path, version: str) -> int:
    manifest = data_dir / "manifest.json"
    if not manifest.exists():
        print("No data/manifest.json - run scripts/ingest_data.py first.", file=sys.stderr)
        return 1
    files = json.loads(manifest.read_text())["files"]
    failed = [f for f in files if f["status"] == "failed"]
    if failed:
        print(f"{len(failed)} failed downloads in manifest - fix before snapshotting:",
              file=sys.stderr)
        for f in failed[:10]:
            print("  ", f["url"], f["note"], file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"data_snapshot_{version}_{date.today().isoformat()}"
    zpath = out_dir / f"{stem}.zip"
    skip_suffixes = (".part", ".wal")
    n = 0
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(data_dir.rglob("*")):
            if p.is_file() and not p.name.endswith(skip_suffixes):
                zf.write(p, Path("data") / p.relative_to(data_dir))
                n += 1
    digest = sha256_of(zpath)
    (out_dir / f"{stem}.sha256").write_text(f"{digest}  {zpath.name}\n")

    counts: dict[str, int] = {}
    for f in files:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    readme = f"""# {stem}

Frozen input data for the ADSP 32018 medallion/RAG project. Do not edit; if the
data needs to change, build a new version (v2, v3...) and record why in
docs/DECISIONS.md.

- Built: {date.today().isoformat()}
- Files in zip: {n}
- Zip size: {zpath.stat().st_size / 1e6:.1f} MB
- SHA-256: {digest}
- Manifest status counts: {counts}
- Built with: scripts/ingest_data.py (GitHub sources pinned by commit inside the script)

## How to use
1. Download the zip and the .sha256 file. Do NOT open the database from a synced Drive folder.
2. Verify: `python scripts/make_snapshot.py --verify <zip>`
3. Unzip at the repo root so you get `./data/...` (data/ is gitignored).
4. Open `data/project.duckdb` read-only from code:
   `duckdb.connect("data/project.duckdb", read_only=True)`

## Contents
- data/raw/physionet/mimic_demo_v1_0  - MIMIC-IV demo v1.0 (what the OMOP ETL was built against)
- data/raw/physionet/mimic_demo_v2_2  - MIMIC-IV demo v2.2 (matches current MIMIC docs)
- data/raw/physionet/omop_demo_v0_9   - MIMIC-IV demo in OMOP CDM 5.3.1 (mapping ground truth)
- data/raw/github/omop_etl            - OHDSI/MIMIC ETL SQL + custom concept mappings
- data/raw/nhanes/2017-2018           - NHANES .xpt data and .htm codebooks
- data/docs/{{mimic,omop,nhanes}}       - RAG corpus
- data/project.duckdb                 - everything above as queryable tables
- data/manifest.json                  - url, size, sha256, status for every file

## Citations
{CITATIONS}"""
    (out_dir / "SNAPSHOT_README.md").write_text(readme)
    print(f"Wrote {zpath} ({n} files, sha256 {digest[:12]}...)")
    print(f"Upload these three files to the team Drive folder (view-only for teammates):")
    print(f"  {zpath}\n  {out_dir / (stem + '.sha256')}\n  {out_dir / 'SNAPSHOT_README.md'}")
    return 0


def verify(zpath: Path) -> int:
    sums = zpath.with_suffix(".sha256")
    if not sums.exists():
        print(f"Expected checksum file next to the zip: {sums}", file=sys.stderr)
        return 1
    expected = sums.read_text().split()[0]
    actual = sha256_of(zpath)
    if actual == expected:
        print("OK - checksum matches.")
        return 0
    print(f"MISMATCH\n  expected {expected}\n  actual   {actual}", file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--out-dir", type=Path, default=Path("snapshots"))
    ap.add_argument("--version", default="v1")
    ap.add_argument("--verify", type=Path, help="verify a downloaded snapshot zip")
    args = ap.parse_args()
    return verify(args.verify) if args.verify else make(args.data_dir, args.out_dir, args.version)


if __name__ == "__main__":
    sys.exit(main())
