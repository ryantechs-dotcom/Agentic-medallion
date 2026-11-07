# ADSP 32018 - RAG + agents for a medallion architecture over a messy source of record

Shared instructions for the whole team (Ryan, Skylar, Jack, Nikhil). Each person's role, tasks
and preferences live in their own `CLAUDE.local.md` at the repo root. It is gitignored and
loaded after this file. If yours is missing, copy `CLAUDE.local.example.md` to
`CLAUDE.local.md` and fill it in.

This is a team research project, not a course assignment. If a course-level `CLAUDE.md` sits
above this folder, its notebook/HTML-export rules don't apply here; only its code style does
(PEP 8, 99-character lines).

Graduate team project (NLP and Agentic AI), due **December 6, 2026**. The full report draft is
due **November 24** (Thanksgiving week has reduced availability).

Research question: can RAG and agentic workflows help build Bronze/Silver/Gold layers on top of a
poorly structured system of record, by retrieving documentation AND verifying it against the data?

## Who owns what
- Problem 1 - RAG vs. non-RAG for documentation Q&A: **Ryan**
- Problem 2 - schema mapping, single-agent vs. multi-agent: **Skylar** (also SME for gold answers)
- Problem 3 - conflict classification: **Jack**
- EDA, evaluation lead, project manager: **Nikhil**
Don't change code or files another owner is responsible for without saying so explicitly.

## Team plan and tracker
- Tasks, owners, due dates and status: `00_admin/project_tracker.xlsx` on the Shared Drive.
  Background plan: `00_admin/project_plan.md`.
- The **Can start after** column lists the task numbers that must be Done before a task can
  start. A number in parentheses is a soft dependency: a draft can start earlier.
- **Keep the tracker current.** When work in a session meets a tracker task's "Done when"
  criterion, or clearly finishes the task, ask the user to update that task's Status. Name the
  task number, say which criterion was met, and list the tasks whose "Can start after"
  prerequisites are now all Done, so the user can tell those owners they can start. Also ask
  when a task's scope or due date changed during the session. Don't edit the tracker yourself
  unless the user asks.

## Data (read docs/DECISIONS.md before touching data)
- `data/` is a **frozen snapshot** (v1) downloaded from the team Google Drive. It is gitignored.
  Never modify files in `data/`, never re-run ingestion casually, never "fix" source data in place.
- Open the database read-only via `medrag.db.connect()` (wraps
  `duckdb.connect(..., read_only=True)` and honors `MEDRAG_DATA_DIR`).
- Schemas: `mimic_demo_v1_0_{core,hosp,icu}`, `mimic_demo_v2_2_{hosp,icu}`, `omop_demo_v0_9`,
  `nhanes_2017_2018`, plus `mimic_demo_v2_2.demo_subject_id` (the demo patient-ID list).
  RAG corpus lives in `data/docs/{mimic,omop,nhanes}`.
- Don't open DuckDB from a cloud-synced folder (OneDrive, Drive): see D3 in `docs/DECISIONS.md`.
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
- Build or extend the evaluation set / ground truth (P1 `eval/`, P2 mapping ground truth)
  **before** tuning the system it scores. Never edit gold answers to match system output. Test
  splits are touched only for final runs.
- Every gold answer cites its source document/section; data-verifiable ones include a SQL check.
- Every experiment run writes config + outputs to `results/<date>_<condition>/` so numbers in the
  report are traceable. No hand-typed numbers in the report.
- We're students: explain design choices and trade-offs so we can defend them. Don't silently
  make methodological decisions; propose them.

## Conventions
- Python 3.11+, pandas, duckdb. Pure functions per rule, thresholds in config (not hardcoded),
  schema validation at layer boundaries.
- Secrets in `.env` (see `.env.example`); never commit keys or `data/`.
- Prefer simple over comprehensive (single-table trackers, minimal abstractions).

## Where to look
| Working on... | Read first |
|---|---|
| data, snapshot, schemas | `docs/DECISIONS.md`, `scripts/ingest_data.py` |
| P1 eval questions / gold answers | `eval/CLAUDE.md` (auto-loads there), `docs/PROBLEM1_PLAN.md` |
| retrieval, chunking, verification, runner | `docs/ARCHITECTURE.md`, `src/medrag/CLAUDE.md` |
| experiment parameters | `configs/base.yaml` + condition YAMLs |
| interface between Problem 1 and Problem 2 | `docs/ARCHITECTURE.md` "Retriever tool contract" |
| report numbers | `results/<date>_<condition>/` only |

## Commands
- Install: `pip install -e ".[dev]"`
- Tests: `pytest` (no API key or network needed)
- Style: `python -m pycodestyle --max-line-length=99 src scripts tests`
- P1 only - rebuild the eval draft: `python scripts/draft_eval_questions.py`
  (writes `eval/*_draft*`)
- Sync results/ and eval/ to Drive: `python scripts/sync_drive.py` (`--dry-run` to preview).
  Each person sets `MEDRAG_PROBLEM` (p1, p2, ...) in their own `.env`.
- Team Drive = NLP_Project Shared Drive, rclone remote `gdrive:` (layout in its README.md):
  admin, snapshots, corpus, eval, results, Colab models. Colab starts with
  `notebooks/00_colab_setup.ipynb`.
- Verify a snapshot download: `python scripts/make_snapshot.py --verify <zip>`
- Rebuild data (snapshot owner only): `python scripts/ingest_data.py` then
  `python scripts/make_snapshot.py --version vN`

## More context (read when relevant, not every session)
- docs/PROJECT_CONTEXT.md - datasets, team, architecture background
- docs/PROBLEM1_PLAN.md - P1 eval set schema, experimental conditions, metrics, timeline
- docs/DECISIONS.md - decision log (why data is local, why v1.0, snapshot process)
- docs/sources.md - every data source with version, license and citation
