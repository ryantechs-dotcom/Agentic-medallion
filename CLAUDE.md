# ADSP 32018 - RAG + agents for a medallion architecture over a messy source of record

This is a team research project, not a course assignment: the notebook/HTML-export rules in
`../CLAUDE.md` do not apply here. Only its code style carries over (PEP 8, 99-char lines).

Graduate team project (NLP and Agentic AI), due **December 6, 2026**; full report draft due
**November 24** (Thanksgiving week has reduced availability). I'm Ryan; I own Problem 1.

Research question: can RAG and agentic workflows help build Bronze/Silver/Gold layers on top of a
poorly structured system of record, by retrieving documentation AND verifying it against the data?

## Who owns what
- Problem 1 - RAG vs. non-RAG for documentation Q&A: **Ryan** (this is most of my work here)
- Problem 2 - schema mapping, single-agent vs. multi-agent: **Skylar** (also SME for gold answers)
- Problem 3 - conflict classification: **Jack**
- EDA, evaluation lead, project manager: **Nikhil**
Don't change code or files another owner is responsible for without saying so explicitly.

## Data (read docs/DECISIONS.md before touching data)
- `data/` is a **frozen snapshot** (v1) downloaded from the team Google Drive. It is gitignored.
  Never modify files in `data/`, never re-run ingestion casually, never "fix" source data in place.
- Open the database read-only via `medrag.db.connect()` (wraps
  `duckdb.connect(..., read_only=True)` and honors `MEDRAG_DATA_DIR`).
- Schemas: `mimic_demo_v1_0_{core,hosp,icu}`, `mimic_demo_v2_2_{hosp,icu}`, `omop_demo_v0_9`,
  `nhanes_2017_2018`, plus `mimic_demo_v2_2.demo_subject_id` (the demo patient-ID list).
  RAG corpus lives in `data/docs/{mimic,omop,nhanes}`.
- The project folder is OneDrive-synced; D3 warns against opening DuckDB from synced folders.
- OMOP `person.person_source_value` = MIMIC `subject_id` as a string (the join key across them).

## Pitfalls that matter for results
- The OMOP demo was built from MIMIC-IV **v1.0** (has a `core` module). Current MIMIC docs describe
  **v2.x** (`core` merged into `hosp`). Score mappings against v1.0. The doc/data mismatch is a
  deliberate test case for Problem 1, not a bug to fix.
- OMOP ground truth is **one ETL team's choices**, not universal truth. Allow an
  "acceptable alternative" judgment when scoring.
- Only **100 patients** - distribution-based checks are weak; rare codes may appear once or never.
- NHANES special codes (7/9, 77/99, 777/999 = refused / don't know) must not be treated as values.
  Variable names and file suffixes change across cycles; we use 2017-2018 (suffix `_J`) only.
- CDC servers can return HTTP 200 with an HTML error page; check Content-Type, not just status.

## Research-integrity rules
- Build/extend the evaluation set in `eval/` **before** tuning retrieval. Never edit gold answers
  to match system output. The test split is touched only for final runs.
- Every gold answer cites its source document/section; data-verifiable ones include a SQL check.
- Every experiment run writes config + outputs to `results/<date>_<condition>/` so numbers in the
  report are traceable. No hand-typed numbers in the report.
- I'm a student: explain design choices and trade-offs so I can defend them; don't silently make
  methodological decisions for me - propose them.

## Conventions
- Python 3.11+, pandas, duckdb. Pure functions per rule, thresholds in config (not hardcoded),
  schema validation at layer boundaries.
- Secrets in `.env` (see `.env.example`); never commit keys or `data/`.
- Prefer simple over comprehensive (single-table trackers, minimal abstractions).

## Where to look
| Working on... | Read first |
|---|---|
| data, snapshot, schemas | `docs/DECISIONS.md`, `scripts/ingest_data.py` |
| eval questions / gold answers | `eval/CLAUDE.md` (auto-loads there), `docs/PROBLEM1_PLAN.md` |
| retrieval, chunking, verification, runner | `docs/ARCHITECTURE.md`, `src/medrag/CLAUDE.md` |
| experiment parameters | `configs/base.yaml` + condition YAMLs |
| interface with Problem 2 | `docs/ARCHITECTURE.md` "Retriever tool contract" |
| report numbers | `results/<date>_<condition>/` only |

## Commands
- Install: `pip install -e ".[dev]"`
- Tests: `pytest` (no API key or network needed)
- Style: `python -m pycodestyle --max-line-length=99 src scripts tests`
- Rebuild the P1 eval draft: `python scripts/draft_eval_questions.py` (writes `eval/*_draft*`)
- Sync results/ and eval/ to Drive: `python scripts/sync_drive.py` (`--dry-run` to preview)
- Team Drive = NLP_Project Shared Drive, rclone remote `gdrive:` (layout in its README.md):
  admin, snapshots, corpus, eval, results, Colab models. Colab starts with
  `notebooks/00_colab_setup.ipynb`.
- Verify a snapshot download: `python scripts/make_snapshot.py --verify <zip>`
- Rebuild data (snapshot owner only): `python scripts/ingest_data.py` then
  `python scripts/make_snapshot.py --version vN`

## More context (read when relevant, not every session)
- docs/PROJECT_CONTEXT.md - datasets, team, architecture background
- docs/PROBLEM1_PLAN.md - eval set schema, experimental conditions, metrics, timeline
- docs/DECISIONS.md - decision log (why data is local, why v1.0, snapshot process)
