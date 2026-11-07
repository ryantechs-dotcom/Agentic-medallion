# Decision log

Newest at the bottom. Each entry: what we decided, why, and what would make us revisit it.

## D1 - Data lives locally, not in a hosted database
- **Decision:** each person works from a local copy of `data/` with a local DuckDB file.
- **Why:** the data is small (tens of MB per source); DuckDB is an embedded single-file database
  that handles many readers but one writer, so a shared networked copy would cause locking
  problems; no accounts or costs; works offline for grading and demos.
- **Revisit if:** we build a live demo that needs a hosted endpoint (e.g., MotherDuck), or move
  to full MIMIC-IV (credentialed - must never go to shared/public storage).

## D2 - One frozen snapshot instead of everyone running ingestion
- **Decision:** Ryan builds the data once, freezes it as `data_snapshot_v1_<date>.zip` with a
  SHA-256 checksum, and everyone uses that file. Ingestion is not re-run unless we cut a new version.
- **Why:** upstream sources change (GitHub docs and ETL repo, occasional NHANES revisions).
  Teammates downloading on different days could silently get different documentation, which
  would corrupt RAG comparisons. One snapshot = identical inputs and a citable data version.
- **Process for a new version:** record the reason here, bump the pinned commits in
  `scripts/ingest_data.py` if needed, rebuild, `make_snapshot.py --version vN`, upload, announce.

## D3 - Snapshot stored on the team Google Drive
- **Decision:** upload the zip, its `.sha256`, and `SNAPSHOT_README.md` to a team Drive folder.
  Teammates get view-only access; only the snapshot owner can edit.
- **Rules:** download and unzip to a normal local folder; never open `project.duckdb` from a
  synced Drive folder (sync can lock, conflict-copy, or corrupt it).
- **Licensing:** MIMIC demos are ODbL (redistribution with attribution), NHANES is public domain,
  OHDSI/MIMIC is Apache 2.0. Per-source licenses and citations: `docs/sources.md`.

## D4 - GitHub sources pinned to commits
- **Decision:** `ingest_data.py` downloads MIT-LCP/mimic-website, OHDSI/MIMIC, and
  OHDSI/CommonDataModel at fixed commit SHAs rather than `main`.
- **Why:** makes even a rebuild reproducible.

## D5 - Download both MIMIC demo v1.0 and v2.2
- **Decision:** keep both. Score Problem 2 mappings against **v1.0**.
- **Why:** the OHDSI ETL (and therefore the OMOP demo) was built against MIMIC-IV v1.0, which
  still had a `core` module; v2.x merged it into `hosp`. Current MIMIC docs describe v2.x. The
  mismatch is used deliberately as a doc-vs-data conflict test in Problem 1.

## D6 - NHANES limited to 2017-2018
- **Decision:** one cycle (suffix `_J`), 14 component files (demographics, body measures,
  blood pressure, core labs, key questionnaires, prescriptions).
- **Why:** avoids cross-cycle variable renames dominating the work. Trim to the components the
  eval set actually uses; add the 2021-2023 cycle only via a new snapshot version.

## D7 - Evaluation set before retrieval
- **Decision:** write and split `eval/questions.csv` before building or tuning any retriever;
  test split untouched until final runs.
- **Why:** prevents questions drifting toward what the system can already answer.

## D8 - PROPOSED (Ryan to confirm): snapshot v1 was built from unpinned `main`
- **Finding:** `data/manifest.json` (1,035 files, all `downloaded`) shows the GitHub sources were
  fetched from `refs/heads/main` / `.../main/...`, by the script now kept at
  `scripts/legacy/ingest_v1_unpinned.py`. The pinned commit SHAs in `scripts/ingest_data.py` (D4)
  were added afterwards, so a rebuild with the current script may not reproduce v1 exactly.
- **Options:** (a) state this in the report and keep v1; (b) check that the pinned SHAs were
  `main` on 2026-10-27, and if so note that v1 is equivalent; (c) cut v2 with the pinned script.
- **Revisit if:** any doc in `data/docs/` differs from the pinned-commit version.

## D9 - PROPOSED: team Drive layout, and syncing results/ and eval/ with rclone
- **Layout:** the root of the **NLP_Project Shared Drive** (see its README.md):
  `00_admin/` (plan, tracker), `01_data_snapshots/vN/` (frozen, checksum-verified),
  `02_corpus/`, `03_eval/pN/`, `04_results/pN/`, `05_models/pN/` (Colab training outputs),
  `06_colab/` (setup notebook), `07_report/`. Organized by problem, not by person, so the report
  pulls from one place. Snapshot v1 uploaded 2026-11-01 (sha256 `7afa0862...`).
- **Access:** Shared Drive membership controls who gets in, and nobody needs per-folder sharing.
  "Never edit snapshots" (D3) is backed by the `.sha256` check in the Colab notebook and
  `make_snapshot.py --verify`.
- **Sync:** `scripts/sync_drive.py` runs `rclone copy --checksum` for `results/` and `eval/` to
  `04_results/<problem>/` and `03_eval/<problem>/`, at the end of each Claude Code session
  (personal SessionEnd hook) and optionally daily (Windows Task Scheduler). `data/` is excluded;
  it changes only via new snapshot versions (D2/D3).
- **Why:** these folders change between sessions and teammates need them. `copy` (not `sync`)
  never deletes from Drive; checksums skip unchanged files; dated run folders avoid overwriting.
- **Revisit if:** the team repo takes over sharing (commit eval/ and results/ to git instead).

## D10 - PROPOSED (Ryan to confirm): NHANES zeros are stored as 5.4e-79 in project.duckdb
- **Finding (2026-11-01):** every NHANES value documented as `0` is stored as
  `5.397605346934028e-79` (the SAS transport-file encoding of zero, read without rounding).
  For example, DMDHHSZA = 0 should match 6,183 rows, WTMEC2YR = 0 should match 550, and
  DID260 = 0 should match 178, but `WHERE x = 0` returns no rows for any of them.
- **Proposal:** keep the frozen v1 data as is (D2). Treat this as a Silver-layer rule (round
  values below 1e-70 to 0) and use it as conflict questions in the P1 eval set
  (data-quality conflict introduced at ingestion). Optionally fix it at ingestion in a v2 snapshot.
- **Revisit if:** the team prefers a v2 snapshot with the fix applied at ingestion.

## D11 - PROPOSED: P1 eval set drafted from the corpus, reviewed by a human
- **What:** `scripts/draft_eval_questions.py` builds 122 draft questions (53 lookup, 29 multihop,
  20 conflict, 20 unanswerable): lookups generated from codebooks/docs with seed 0, the rest
  hand-written in `eval/handwritten_draft.csv`. Every row cites a doc section; SQL checks run
  read-only. All rows are `author = Claude (draft)`.
- **Why:** follows the plan's "questions generated from the parsed codebooks" and D7 (eval set
  before retrieval). The seeded generator avoids picking questions that suit the system.
- **Integrity:** Ryan reviews every row and creates `eval/questions.csv`. Skylar answers a sample
  independently for agreement. The proposed 60/40 split is frozen before any results exist.
- **Revision (2026-11-01, after an independent Claude review; Ryan accepted the review):** the
  draft is now 133 questions (64 lookup, 26 multihop, 23 conflict, 20 unanswerable).
  - Fixed: the MI-024 gold (POE link via pharmacy); the radiology question moved from
    unanswerable to conflict (the schema overview names the table).
  - Relabelled: single-chunk "multihop" questions are now lookups.
  - Dropped: 3 duplicates or near-duplicates.
  - Added: 17 verified questions covering RXQ_RX, HDL, TCHOL, ICU docs and OMOP conventions.
  - Generator: no Yes/No or non-response answers in code lookups, one question per
    special-code pair, ICU columns parsed, no repeats of hand-written variables.
  - New columns: subtype, gold_evidence, needs_data, guessable, cluster.
  - The split keeps each cluster in one split and balances every qtype x source x template
    cell.
  - Not decided here: whether the OMOP ETL repo docs join the corpus. That would make the cross
    questions doc-answerable; for now, `needs_data` marks them instead.
- **Frozen v1 (2026-11-02, Ryan's decision):**
  - A second independent Claude review covered the 67 rows added or reworded in the revision.
    Its fixes were applied:
    - MI-029's gold fixed (wrong clause on inpatient weight);
    - two dev-to-test give-aways reworded;
    - the OMOP ethnicity gold corrected;
    - tag fixes;
    - one redundant lookup dropped.
  - Generated-row fixes live in `eval/generated_overrides.csv`.
  - Ryan then accepted the set as reviewed and froze it as `eval/questions.csv` and
    `eval/qa_eval.jsonl` (a one-off copy of the draft): 132 questions, 77 dev / 55 test.
  - sha256:
    - `questions.csv` `3a9758544a347eb6c0b4d1b3120b9c288cacee2263cadff3463e6529b8f54e14`
    - `qa_eval.jsonl` `3fe1fe8f8b2813bc4911bc9b51636653de8fd32b485bf5baa42a44ed2915e0d1`
  - From now on, no gold or split changes without a new version and a reason logged here.
    `reviewed_by` stays empty until Skylar's agreement sample.

## D12 - FUTURE PLAN (Ryan, 2026-11-03; for team agreement): feedback loop to the SOR owners
- **Idea:** the source of record is never fixed in place (Bronze stays as it arrived), but the
  workflow already finds its problems. It could write them out for the SOR owners:
  documentation errata (doc vs data, with evidence), a generated data dictionary (meanings,
  valid and special codes, citations), and a data-quality issue log tagged with P3 conflict types.
- **Scope now:** not built as a new problem. Described in Model Ops (HITL feedback loop) and as
  future work in the Conclusion, optionally with one example artifact from existing outputs.
- **Revisit if:** the team agrees at kickoff to build the example artifact, or results lock early.

## D13 - PROPOSED (Skylar, 2026-11-07; Ryan to confirm): P2 code location
- **Decision:** Problem 2 code and prompts live in `src/medrag_p2/` (prompts in
  `src/medrag_p2/prompts/`), installed by the same `pip install -e .`.
- **Why:** a separate package keeps P2 out of `src/medrag/` (Ryan's) while still importing
  `medrag.db` and `medrag.retrieval`, and gives P2 its own nested `CLAUDE.md`.
- **Alternative:** `src/medrag/mapping/` (the example in `CLAUDE.local.example.md`): one package,
  but P2 files would sit inside Ryan's package and load `src/medrag/CLAUDE.md`.
- **Revisit if:** the team prefers one package per person, or P2 needs a separate install.

## D14 - PROPOSED (Skylar, 2026-11-07; Ryan/Nikhil to confirm): P2 ground truth design
- **Unit:** one row per (MIMIC v1.0 source column, OMOP target field) pair in
  `eval/p2/p2_ground_truth_draft.csv`. `is_primary` marks a column's main target, for top-1
  accuracy. Columns the ETL drops get a `not_mapped` row, so precision penalizes invented
  mappings.
- **Granularity:** field level only. Concept values (itemid/code -> concept_id, the `gcpt_*`
  files) are out of scope for now; `concept_ref` names the lookup file used.
- **Evidence:** each row cites lines in the snapshot's OHDSI/MIMIC ETL copy (unpinned `main`,
  see D8) and has a `verify_sql` against `omop_demo_v0_9` that must return 0 mismatches.
  `python -m medrag_p2.ground_truth` runs all checks and writes `*_review.md`.
- **ETL code is not the truth by itself.** The snapshot's ETL is the v2.x version
  (`st_core.sql:54` reads `race AS ethnicity`), and in one place the OMOP demo disagrees with it
  (`gcpt_per_ethnicity` maps UNKNOWN to 0; the demo stores 2000001401). Rows therefore follow
  the OMOP demo data, and disagreements are recorded in `notes` as P3 conflict candidates.
- **NHANES:** excluded (there's no external expert mapping; labels by the system's own builder
  would be circular).
- **Split:** by source table, so whole tables are held out. `patients` and `admissions` are dev
  (used to build #14/#15). Test tables are chosen and frozen before any agent run.
- **Acceptable alternatives** are written before any agent output exists (e.g. `patients.dod`
  -> `death.death_date`, `insurance` -> `payer_plan_period.payer_source_value`).
- **Changeable until the first agent run.** After that, any gold, alternative or split change
  needs a new version and a reason logged here (same rule as D11).
- **Review:** rows are `author = Claude (draft)`; Skylar reviews, then Nikhil. Frozen as
  `eval/p2/p2_ground_truth.csv` with a sha256 here.
- **Revisit if:** scoring needs concept-level truth, or the team adds NHANES hand labels.
