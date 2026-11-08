# ADSP 32018 - RAG and agents for a medallion architecture

Team: Ryan, Jack, Skylar, Nikhil. Due December 6, 2026.

Can retrieval over documentation, combined with verification against the actual data, help build
Bronze/Silver/Gold layers on top of a messy system of record? Background in
`docs/PROJECT_CONTEXT.md`; decisions in `docs/DECISIONS.md`.

## Layout
```
CLAUDE.md                 shared Claude Code instructions (+ nested ones in src/, eval/)
CLAUDE.local.example.md   template for your personal CLAUDE.local.md (gitignored, one per person)
pyproject.toml            installable package `medrag` (pip install -e .)
configs/                  base.yaml + one YAML per experimental condition (no hardcoded params)
docs/                     context, P1 plan, architecture, decisions, contracts.md, sources.md
scripts/ingest_data.py    builds data/ from public sources (snapshot owner only)
scripts/make_snapshot.py  freezes data/ into a versioned zip + checksum; verifies downloads
scripts/build_corpus.py   builds corpus/corpus_v1.jsonl from data/docs (see RAG corpus)
scripts/sync_drive.py     copies results/ and eval/ to Google Drive (see Syncing)
scripts/legacy/           the unpinned ingest script that built snapshot v1 (provenance only)
src/medrag/               project code: corpus, retrieval, verify, generation, evaluation
src/medrag_p2/            Problem 2 code: schema-mapping agents and their prompts (Skylar)
eval/                     evaluation question set (questions_template.csv shows the schema)
tests/                    pytest; no API key or network needed
notebooks/                exploration only, never imported by src/
results/                  one folder per experiment run
corpus/                   built RAG corpus - gitignored, rebuilt or downloaded from Drive
data/                     frozen snapshot - gitignored, never edited
```

## Setup
1. Clone the repo and install: `pip install -e ".[dev,dense]"` (`dense` adds
   sentence-transformers for the embedding model; tests and CI only need `[dev]`)
2. Download `data_snapshot_v1_<date>.zip` and its `.sha256` from the team Google Drive folder
   into the repo root (not a synced Drive folder).
3. Verify: `python scripts/make_snapshot.py --verify data_snapshot_v1_<date>.zip`
4. Unzip at the repo root so you have `./data/project.duckdb`.
5. Copy `.env.example` to `.env` and add your API key.

Quick check: `pytest` (the snapshot test confirms all expected schemas open read-only), or
```python
from medrag import db
con = db.connect()          # read-only; honors MEDRAG_DATA_DIR in .env
print(sorted(db.schemas(con)))
```

## Working together
One branch per tracker task (`<name>/<task#>-<slug>`), a PR to `main`, and a review from the
owner of any shared file it touches. CI (`.github/workflows/tests.yml`) runs `pytest` and the
style check on every PR. Run them locally first:
```
pytest
python -m pycodestyle --max-line-length=99 --exclude=legacy src scripts tests
```
Per-problem layout (code, prompts, eval, results, Drive): `docs/contracts.md` section 1.
Details and decision numbering: `CLAUDE.md` "Working together (git)".

## Team Google Drive (NLP_Project Shared Drive)
Data, eval sets, results and Colab model outputs live on the NLP_Project Shared Drive; code lives
here. Its root `README.md` explains the layout: `00_admin/`, `01_data_snapshots/vN/`,
`02_corpus/`, `03_eval/pN/`, `04_results/pN/`, `05_models/pN/`, `06_colab/`, `07_report/`.
- **Colab:** as a member of the Shared Drive, run
  `06_colab/00_colab_setup.ipynb` (source: `notebooks/00_colab_setup.ipynb`). It copies the
  snapshot to the Colab disk, verifies its checksum, and creates a run folder under `05_models/`.
- **New snapshot version:** after `make_snapshot.py --version vN`, upload with
  `rclone copy snapshots/ gdrive:01_data_snapshots/vN --checksum`.

## RAG corpus
`python scripts/build_corpus.py` turns `data/docs` (NHANES codebooks, MIMIC docs, OMOP CDM
spec) into `corpus/corpus_v1.jsonl`: one section-level record per NHANES variable or narrative
section, MIMIC heading, and OMOP table or field (format: `docs/contracts.md` section 2;
decisions: `docs/DECISIONS.md` D13). It also writes `corpus_v1.manifest.json` with counts and
the sha256. The build needs no network and is byte-identical for the same snapshot;
`--check` confirms that. If you'd rather not rebuild, download both files from Drive
`02_corpus/v1/`. Snapshot owner, after a build:
`rclone copy corpus/ gdrive:02_corpus/v1/ --checksum`.

## Syncing results/ and eval/ to Google Drive
`scripts/sync_drive.py` sends **only your own problem's files** (`MEDRAG_PROBLEM` in `.env`)
to `MEDRAG_DRIVE_REMOTE`: your run folders `results/<date>_<pN>_*/` -> `04_results/<pN>/`, and
your eval files -> `03_eval/<pN>/` (p1: the top level of `eval/`; p2/p3: `eval/p2/`,
`eval/p3/`). It uses `rclone copy --checksum`: only changed files upload and nothing on Drive
is deleted.
`data/` is never synced (new snapshot versions go up as above).
1. One-time: install rclone (`winget install Rclone.Rclone` on Windows,
   `brew install rclone` on macOS), then `rclone config` (Google Drive remote named
   `gdrive`; answer yes to Shared Drive and pick NLP_Project), then set
   `MEDRAG_DRIVE_REMOTE=gdrive:` and `MEDRAG_PROBLEM` to your problem (`p1`, `p2` or `p3`)
   in `.env`.
2. Check: `python scripts/sync_drive.py --dry-run`
3. Automatic (optional, personal): a Claude Code `SessionEnd` hook in
   `.claude/settings.local.json` and a daily Windows scheduled task both run
   `python scripts/sync_drive.py --quiet`. Each run is logged to `logs/sync.log`.

## Rebuilding the data (snapshot owner only)
```
python scripts/ingest_data.py            # downloads everything, checks checksums, builds DuckDB
python scripts/make_snapshot.py --version v2
```
Record the reason for a new version in `docs/DECISIONS.md` first.

## Data sources and licenses
MIMIC-IV Clinical Database Demo v1.0 and v2.2 and MIMIC-IV Demo in OMOP CDM v0.9 (PhysioNet,
ODbL v1.0); NHANES 2017-2018 (CDC/NCHS, public domain); OHDSI/MIMIC ETL and OHDSI/CommonDataModel
(open source); MIMIC-IV documentation (MIT-LCP). Licenses and full citations per source:
`docs/sources.md`; confirm each PhysioNet page's required citation before submitting.
