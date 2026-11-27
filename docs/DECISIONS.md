# Decision log

Newest at the bottom. Each entry: what we decided, why, and what would make us revisit it.
On a branch, title a new entry `## D-next - ...`; it gets the next number when its PR
merges, and references to it are updated in the same PR (D17).

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

## D13 - DECIDED (Ryan, 2026-11-07): RAG corpus v1 = section-level records from snapshot v1
- **Scope:** tracker task 5 named "codebooks, questionnaires and Data Briefs", but frozen
  snapshot v1 holds only the 14 NHANES codebook pages. The codebooks already carry each
  question's English wording, and adding Data Briefs would need a v2 snapshot. That would also
  change the corpus the frozen eval set's unanswerable checks (D11) were run against. So v1 is
  codebooks only; Data Briefs are future work, through a v2 snapshot that re-checks the
  unanswerable questions first.
- **What:** `scripts/build_corpus.py` builds `corpus/corpus_v1.jsonl` from all three RAG
  sources with one schema (`docs/contracts.md` section 2). 1,270 records:
  - 319 NHANES variables and 113 NHANES narrative sections;
  - 405 MIMIC heading sections;
  - 37 OMOP tables and 396 OMOP fields.
  Text length ranges from 41 to 16,608 characters (median 356.5).
  sha256 `6333aa6efd25def1c8f53863448a6e9a208d57e46d480a4fe412ae78658a7ff0`.
- **Why section-level:** each source's natural unit is also the unit the gold answers cite
  (variable, column heading, OMOP field). Chunking (task 9) then stays a separate, swappable
  step for the fixed-size ablation.
- **Parsing choices** (whitespace and rendering only; source text is never rewritten):
  - Non-breaking spaces become plain spaces. MIMIC uses them, e.g. `core\xa0module`.
  - MIMIC Jekyll includes (`{% include hadm_id.md %}`, 42 uses) are filled in from
    `_includes/` in the frozen `data/raw/github/mimic_docs.zip`, as the website renders them.
  - **MIMIC HTML comments are dropped.** They aren't shown on the website, for example a
    commented-out "Types of data" section in `about__concepts.md`. Confirmed by Ryan
    (2026-11-07): the corpus is what is actually published.
  - The blank `NA` trailing row of the OMOP field CSV is skipped, and `NA` cells are left out
    of record text.
  - NHANES cumulative counts are dropped; code, description, count and skip-to are kept.
- **Check:** `tests/test_corpus_snapshot.py` confirms that every gold reference in
  `eval/questions.csv` is covered: all 129 `gold_doc`/`gold_section` + `gold_evidence`
  entries, 115 of them by section name and the rest by phrase. The test reads gold metadata
  only, never outputs.
- **Where:** `corpus/` is gitignored (derived data; the MIMIC docs' license isn't recorded) and
  shared on Drive `02_corpus/v1/` with its manifest.
- **Revisit if:** a v2 snapshot, or the team wants Data Briefs / questionnaire PDFs.

## D14 - PROPOSED: shared formats in docs/contracts.md (tracker task 4)
- **What:**
  - one document for every cross-owner format: corpus record, chunk, retriever tool, SQL tool,
    P1 eval set, P2 column spec + ground truth, P3 conflict label, run log, prompt versioning;
  - `medrag.contracts` validates them at layer boundaries;
  - `medrag.generation.load_prompt` returns the prompt text plus its sha256 for run logs.
- **Status:**
  - The P1 eval set is AGREED (frozen, D11).
  - Everything else is PROPOSED until reviewed: Skylar reviews the retriever, SQL tool and P2
    sections, and Jack reviews the P3 section.
  - P3 `conflict_type` reuses the P1 conflict subtypes so P1 conflict questions can seed P3.
- **Changes from before:** run folders gain a problem prefix (`<date>_<pN>_<condition>`).
  Prompt naming was first proposed as `<pN>_<purpose>_v<N>.txt` in one shared folder;
  superseded by D17 (one prompts folder per problem package).
- **Revisit if:** an owner edits their section in review; record the agreed version here.

## D15 - DECIDED (proposed by Skylar, accepted by Ryan, 2026-11-07): P2 code location
- **Decision:** Problem 2 code and prompts live in `src/medrag_p2/` (prompts in
  `src/medrag_p2/prompts/`), installed by the same `pip install -e .`.
- **Why:** a separate package keeps P2 out of `src/medrag/` (Ryan's) while still importing
  `medrag.db` and `medrag.retrieval`, and gives P2 its own nested `CLAUDE.md`.
- **Alternative:** `src/medrag/mapping/` (the example in `CLAUDE.local.example.md`): one package,
  but P2 files would sit inside Ryan's package and load `src/medrag/CLAUDE.md`.
- **Revisit if:** the team prefers one package per person, or P2 needs a separate install.

## D16 - ACCEPTED (proposed by Skylar, accepted by Ryan, 2026-11-07): P2 ground truth design
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
- **Conditions from Ryan's acceptance (2026-11-07):**
  - The **test tables are chosen, mapped and frozen** (with the sha256 logged here) **before
    the first #14 or #15 agent run**, since every current row is dev.
  - Nikhil's review of the frozen file remains tracker #12's "done when".
- **Revisit if:** scoring needs concept-level truth, or the team adds NHANES hand labels.

## D17 - DECIDED (Ryan, 2026-11-07): conventions for working across problems
Settled while merging Skylar's P2 branch into main, where the two sets of conventions clashed.
- **Prompts:** each problem keeps its prompts in its own package (`src/medrag/generation/
  prompts/`, `src/medrag_p2/prompts/`, `src/medrag_p3/prompts/`), named `<purpose>_v<N>.txt`.
  `medrag.generation.load_prompt(name, prompts_dir)` returns file, text and sha256, and runs
  record `prompts: {role: {file, sha256}}` so multi-agent runs fit. Replaces D14's shared-folder
  proposal: no P1 prompts existed yet, and the folder already says whose prompt it is.
- **P2 formats:** `docs/contracts.md` section 7 adopts Skylar's ground-truth schema (the
  source of truth is `medrag_p2.ground_truth.REQUIRED_COLUMNS`). The P2 spec uses the same
  field names, so scoring is a join, and is validated as `medrag.contracts` kind `p2_spec`.
- **One layout per problem** (code, prompts, eval, results, Drive): `docs/contracts.md`
  section 1. P3 (Jack) follows the same pattern in `src/medrag_p3/` and `eval/p3/`.
- **Drive sync per problem:** `sync_drive.py` sends only the syncing person's eval folder and
  `results/*_<pN>_*` run folders. Before, a P2 sync would have copied P1's frozen eval set to
  `03_eval/p2/`.
- **Column profile tool** contract added (section 11, PROPOSED for Jack's #7) so #9, #14 and
  #15 can build against a stub now.
- **Decision numbers** are assigned at merge time (`D-next` on branches). Skylar's branch and
  main both added a D13/D14; hers became D15/D16.
- **Team workflow:** one branch per tracker task, PR to main, the owner of any shared file
  reviews, and CI runs tests and the style check (root CLAUDE.md "Working together").
- **Revisit if:** an owner objects after reviewing the merged integration PR (#2). It was
  merged without Skylar's review to unblock #14/#15; her review follows the merge.

## D18 - DECIDED (Ryan, 2026-11-07): retriever design for task 9
- **Chunking:** structure chunks, one per corpus record; records over `max_chunk_tokens = 300`
  words are split on line boundaries and each part repeats the title line. "Tokens" are
  whitespace-separated words, which is model-agnostic and deterministic. 300 words stays inside
  bge's 512-wordpiece input, so no chunk is silently truncated. 1,270 records give 1,325 chunks,
  and every gold reference is still covered (`tests/test_retrieval_snapshot.py`).
- **Dense model:** `BAAI/bge-small-en-v1.5`. Local and free, needs no API key, deterministic
  on CPU, and small enough for teammates and Colab. Embeddings are cached in `corpus/index/`,
  keyed on a hash of every chunk id and text. Alternatives: bge-base (about 3x slower, possibly
  a little better) and API embeddings (cost, keys, network).
- **Hybrid:** reciprocal rank fusion, `rrf_k = 60`, top 50 from each retriever. It uses ranks
  only, so there's no score calibration and no mixing weight to tune on dev.
- **BM25 tokens:** identifiers are kept whole and also split on underscores
  (`gender_concept_id` also gives `gender concept id`). English stopwords (NLTK's list) are
  dropped (`retrieval.bm25_stopwords`). This was decided after a sanity query, before any dev
  metrics: "What does DIQ010 = 9 mean?" ranked DIQ291 ("What does Dr say A1C should be") first.
  Both settings were then compared on dev.
- **Profile tool:** a minimal contract-11 `profile_column` was built in #9, so P2 gets real
  profiles now. NHANES special codes come from the codebook record, not from the values.
- **Dev check** (65 dev questions with a gold doc, structure chunks; files in
  `results/2026-11-07_p1_retrieval_*/`, commit 2895e43):

  | retriever | recall@1 | recall@5 | recall@10 | MRR |
  |---|---|---|---|---|
  | BM25, no stopwords | 0.508 | 0.708 | 0.769 | 0.593 |
  | BM25, stopwords | 0.508 | 0.723 | 0.785 | 0.612 |
  | dense | 0.462 | 0.754 | 0.785 | 0.571 |
  | hybrid, no stopwords | 0.554 | 0.754 | 0.769 | 0.632 |
  | hybrid, stopwords (default) | 0.585 | 0.754 | 0.769 | 0.649 |

  One question is 1.5 points, so the stopword differences are small. Hybrid has the best
  recall@1 and MRR. Weak spots: multihop (recall@10 0.46) and conflict questions, which need
  several documents (the case for condition 4). Some NHANES lookups also miss: in "What does
  the NHANES 2017-2018 variable MCQ366c in the MCQ_J file record?", the boilerplate words match
  the MCQ_J narrative sections more often than the one identifier matches. Dense alone misses
  identifier queries such as DIQ010.
- **Revisit if:** the condition 3 ablation (Nov 17, #13) shows fixed chunks or another fusion
  doing clearly better on dev, or P2 needs a different retriever interface (agree with Skylar).

## D19 - DECIDED (Ryan, 2026-11-10): which NHANES labels are special codes
The profile tool (contract 11) sets special codes aside from the values. Until now only labels
starting with "Refused" or "Don't know" counted. Two other labels looked like non-answers
(found in the task 7/8 review). Counts are from the v1 snapshot and corpus_v1:

| Label | Where | Code | Rows |
|---|---|---|---|
| Unknown | `RXQ_RX_J.RXDDRUG` (drug name) and `RXDRSC1` (ICD-10-CM code), both text | 55555 | 13 and 84 |
| Could not obtain | 9 `BMX_J.BMI*` comment columns | 1 | 1,805 in total |
| Could not obtain | 5 `BPX_J` columns (BPAARM, BPXPTY, BPAEN1-4) | 8 | 0 |

- **Unknown counts.** 55555 sits in the same columns as 77777 Refused and 99999 Don't know and
  is not a drug name or an ICD code. The frozen P1 gold answers NH-031 and NH-044 already say
  these codes "must be treated as missing"; before this change the tool counted "55555" as a
  drug name.
- **Could not obtain stays a value.** The BMX comment columns exist to record why a
  measurement is missing. In all 334 rows with `BMILEG = 1` the measurement `BMXLEG` is NULL,
  and in 6 of the 9 columns code 1 is the only value. Calling it a special code would leave
  those columns with 0 distinct values and hide the reason, which is what a Silver rule or an
  agent needs. The BPX code 8 never occurs, so it changes nothing.
- **Rule:** a special code stands in for a non-answer inside a column of answers. Codes in a
  column whose purpose is to explain missingness are values.
- **Effect on the profile:** only RXDDRUG and RXDRSC1 change. Columns with special codes stay
  at 122. Special cells go from 6,528 to 6,625 (+97). No gold answer or test-split run is
  touched; the task 26 draft and tabular EDA notebook were updated in the same PR.

## D20 - DECIDED (Ryan, 2026-11-10): P1 generation setup for task 13
- **Model and settings:** `claude-opus-5-5`, effort `high`, the same for every condition and
  every final run (`configs/base.yaml`, `generation`). There is no `temperature` key: current
  Claude models reject it, so determinism comes from the fixed model, effort and prompt
  version, and run-to-run variance is measured by #17's three repeats.
- **Backend: headless Claude Code on Ryan's Claude seat (`claude_cli`).** No one on the team has
  API credits; the Enterprise seat runs `claude -p` without an API key. Isolation, so a
  closed-book run can't read local files: `--tools ""`, `--safe-mode` (no CLAUDE.md, skills,
  hooks, MCP), `--strict-mcp-config`, a replaced system prompt, a scratch folder outside the
  repo, and API-key variables removed so the seat is used. A probe call confirmed it saw no
  CLAUDE.md or memory and had no tools besides structured output.
- **Limitations to report:** the model answers inside Claude Code's harness (it adds about
  1,300 input tokens), not a bare API call; usage counts against the seat's limits; the CLI's
  `total_cost_usd` is a list-price estimate, not a bill. Token counts are taken only from the
  answering model (Claude Code also makes a small side call with another model).
- **Scope: Claude only.** Calls go through one backend interface (`generation/llm.py`), so an
  Anthropic API backend can be added if a key appears. Other providers (OpenAI-compatible,
  local models), C4 tool-format converters and a bring-your-own-model setup are future work,
  for the Model Ops sections (#20, #21) to cite.
- **Condition 2** pastes the gold doc plus gold_evidence docs and is scored on answerable rows
  only; the 12 dev unanswerable rows are recorded as skipped.
- **Refusals:** no fallback to another model; a refusal is an error, counted per condition.
- **Judge:** same model and backend as generation (`judge_v1`). Abstentions are scored by rule
  (correct on unanswerable, `abstained` on answerable). Self-preference is checked against
  Ryan's hand labels on a stratified sample (~30 items) before results are reported.
- **SME sample:** `eval/sme_agreement_sample.csv`, 20 questions (5 per qtype, both splits,
  seed 0), without gold answers, for Skylar.
- **Smoke tests** (first 5 dev rows, all multihop; `results/2026-11-10_p1_c1_closed_book_smoke5`,
  `results/2026-11-10_p1_c3_rag_smoke5`): closed-book 5/5 correct, RAG 1/5 with 4 abstentions,
  because the prompt says to answer from the passages and retrieval misses one of the needed
  documents on multihop questions (D18). Too small to conclude anything.
- **Grounding policy, prompt ablation on dev (Ryan, 2026-11-10):** strict `answer_v1` (answer
  only from passages, else abstain) vs permissive `answer_v2` (passages first; own knowledge
  allowed if the answer says so; the only change). C2 and C3 run with both; C1 with v1 only
  (it gets no passages). One prompt is frozen for all conditions before the final runs; if it
  is v2, C1 is re-run with v2. **Choice (Ryan, 2026-11-18): `answer_v2`**, frozen for every
  condition and every final run (`configs/base.yaml`, `generation.prompt`). Why: v1's
  abstentions mostly measure retrieval misses (C3 multihop 0.231 vs 0.923), which recall@k
  already measures, so v1 would count the retriever's misses twice instead of testing whether
  documentation helps. Cost: out-of-scope questions get answered from general knowledge (C3
  hallucination 0.000 vs 0.167, the same as closed-book). The dev v1-vs-v2 runs are reported
  as a grounding-policy ablation. Chosen on dev only; the test split is untouched. C1 is re-run
  with v2 so every condition uses byte-identical prompt text. Result
  (`results/2026-11-18_p1_c1_closed_book`, commit `04d426e`, clean tree): the same accuracy as
  v1 (0.857 overall, 0.862 answerable) and the same hallucination rate (0.167). But v2 still
  changes C1's wording: 71 of 77 answers say they come from general knowledge, so the
  "passages not enough" line also fires when there are no passages at all.
- **Dev results** (77 dev questions; C2 has 65 answerable; `results/2026-11-10_p1_*` and
  `results/2026-11-18_p1_c1_closed_book`,
  metrics.json `overall` / `answerable` / `by_qtype`):

  | run | accuracy (all) | accuracy (answerable) | wrong abstain | hallucination | citation hit |
  |---|---|---|---|---|---|
  | C1 closed-book, v1 | 0.857 | 0.862 | 0.077 | 0.167 | - |
  | C1 closed-book, v2 (2026-11-18) | 0.857 | 0.862 | 0.062 | 0.167 | - |
  | C2 long context, v1 | 0.785 | 0.785 | 0.169 | n/a | 0.954 |
  | C2 long context, v2 | 0.892 | 0.892 | 0.031 | n/a | 0.969 |
  | C3 RAG hybrid k=5, v1 | 0.688 | 0.631 | 0.231 | 0.000 | 0.754 |
  | C3 RAG hybrid k=5, v2 | 0.870 | 0.877 | 0.031 | 0.167 | 0.754 |

  - By qtype: on conflict questions (n=14), closed-book v1 (0.714) beats C2 v1/v2
    (0.286/0.643) and C3 v1/v2 (0.214/0.500); closed-book v2 gets one question fewer (0.643),
    tying C2 v2. The v2.x docs pull the model toward the wrong version on the
    MIMIC version_mismatch rows, which is the case condition 4 targets. On NHANES rows the docs
    help: C1 0.767 (both prompts), C2 v1/v2 0.960, C3 v1/v2 0.800/0.900.
  - All hallucinations are `out_of_scope` rows (2 of 7, NH-046 and NH-049, in C1 and C3 v2),
    answered from general knowledge, and the same two in C1 v2; there are none on
    `false_premise` rows (0 of 5).
  - Strict v1 abstains whenever retrieval misses (C3 v1 multihop 0.231 vs v2 0.923; needs_data
    rows 0.000 vs 0.667).
  - Small n: one conflict or multihop question is 7-8 points. Dev only, one run, judge not yet
    validated against hand labels.
  - C3 and most of C1 ran one call at a time; the two C2 runs ran in parallel with each other,
    so dev latency is not comparable across conditions. Final runs (#17) run one at a time.
- **Provenance of the Nov 10 dev runs (Ryan, 2026-11-18):** their `config.json` says
  `git_commit: a34901e` (main at the time), but they ran from an uncommitted working tree
  that was committed two minutes after the last judging pass as `40aa256` (rebased onto main
  as `f0ee301`, same content). The answer-prompt sha256 in each run matches the committed
  files (`answer_v1` 24e1429b..., `answer_v2` 6f7486f2...), and so does the judge prompt's
  sha256 in `metrics.json` (`judge_v1` d777bf2e...). The numbers stand; read `40aa256` for
  the code. Found on the way: the `.gitattributes` rule meant to keep prompts byte-for-byte
  (`src/*/prompts/*.txt`) missed `src/medrag/generation/prompts/`, so the rebase's Windows
  checkout wrote them as CRLF and changed their sha256 (`answer_v2` became bcb84ac1...). Fixed
  in `04d426e` (`src/**/prompts/*.txt`, plus a test); the one smoke run made with CRLF prompts
  was deleted. **Guard from now on:** `runner.git_state()` records `git_commit` and `git_dirty`
  (uncommitted edits under `src/`, `configs/`, `scripts/`, `eval/`) in `config.json` and in
  `metrics.json` `judge`. `run` and `judge_run` refuse a dirty tree, and `run` refuses to resume
  after HEAD moved, unless it's a smoke (`--limit`) or `fake` run or `--allow-dirty` is passed
  (recorded as `allow_dirty`).
- **Seat note:** twice, three calls in a row failed because `claude.exe` didn't start (Windows
  `0xC0000142`, 0.1-0.5 s, no output); the runner stopped as designed and `--resume` redid
  them. 0 errors remain in the five dev runs.
- **Judge validation:** `scripts/draw_judge_sample.py` draws 30 model-judged dev answers,
  round-robin over verdicts (seed 0), into a blind sheet (`eval/judge_label_sample.csv`);
  `--score` reports agreement and Cohen's kappa against Ryan's labels.
- **Revisit if:** an API key becomes available (switch backend for all runs at once, never
  mid-comparison), or the seat's limits make the final runs infeasible.

## D-next - DECIDED (Ryan, 2026-11-19): C3 retriever and chunking ablation on dev
- **Question:** which retriever (BM25, dense, hybrid; D18) and which chunking (structure vs
  fixed-size) to use for condition 3 in the final runs (#17). The P1 plan's Nov 17 milestone.
- **Fixed-size chunks need a fair size first.** `fixed_chunk_tokens` was 400 words (+50
  overlap), while structure chunks have a median of 57 words (302 fixed chunks vs 1,325
  structure chunks). With k=5, 400-word windows give the model much more text (measured below:
  about 3x), and the gold matching rule (gold section name anywhere in the chunk text,
  contracts section 2) favours big chunks, so a 400-word comparison would mostly measure context
  size.
- **Step 1, retrieval-only scan (no model calls):** BM25, dense and hybrid with structure chunks
  (re-run at the current commit), and with fixed chunks of 60, 150 and 400 words (overlap 1/8
  of the window, the configured 400/50 ratio; `eval_retrieval.py --fixed-tokens N`). 60 is about
  the structure median. Each run also reports the mean words of chunk text in the top k=5.
- **Selection rule, fixed before the scan is run:** the fixed size carried into the end-to-end
  run is the one with the best **hybrid recall@5** on dev (C3 uses k=5; the plan's ablation is
  "same retriever"). Ties go to the higher MRR, then to the smaller size (less context). The
  chosen size becomes `retrieval.fixed_chunk_tokens` / `fixed_chunk_overlap` in base.yaml.
- **Step 2, end-to-end on dev** (`answer_v2`, k=5, one run at a time so latency is comparable,
  each judged with `judge_v1`): hybrid + structure (a re-run of the Nov 10 configuration, so all
  variants share one commit; comparing it with the Nov 10 run gives a first estimate of
  run-to-run noise), BM25 + structure, dense + structure, hybrid + fixed (chosen size).
- **Retrieval-only results** (`results/2026-11-18_p1_retrieval_*`, commit `80ab3f5`; n = 65 dev
  questions with a gold doc):

  | retriever | chunking | chunks | recall@1 | recall@5 | recall@10 | MRR | context words (k=5) |
  |---|---|---|---|---|---|---|---|
  | bm25 | structure | 1325 | 0.508 | 0.723 | 0.785 | 0.612 | 493 |
  | dense | structure | 1325 | 0.462 | 0.754 | 0.785 | 0.571 | 639 |
  | hybrid | structure | 1325 | 0.585 | 0.754 | 0.769 | 0.649 | 590 |
  | bm25 | fixed 60 | 1935 | 0.462 | 0.692 | 0.738 | 0.564 | 299 |
  | dense | fixed 60 | 1935 | 0.431 | 0.692 | 0.769 | 0.542 | 298 |
  | hybrid | fixed 60 | 1935 | 0.492 | 0.723 | 0.769 | 0.592 | 298 |
  | bm25 | fixed 150 | 777 | 0.400 | 0.677 | 0.723 | 0.512 | 740 |
  | dense | fixed 150 | 777 | 0.308 | 0.631 | 0.723 | 0.440 | 741 |
  | hybrid | fixed 150 | 777 | 0.369 | 0.662 | 0.723 | 0.495 | 739 |
  | bm25 | fixed 400 | 302 | 0.415 | 0.692 | 0.754 | 0.523 | 1937 |
  | dense | fixed 400 | 302 | 0.262 | 0.723 | 0.815 | 0.452 | 1922 |
  | hybrid | fixed 400 | 302 | 0.338 | 0.723 | 0.800 | 0.495 | 1924 |

  - The structure re-runs reproduce the Nov 7 numbers exactly (D18), as expected: retrieval is
    deterministic.
  - **Rule applied:** hybrid recall@5 ties at 0.723 for fixed 60 and fixed 400 (fixed 150:
    0.662); the higher MRR picks **fixed 60** (0.592 vs 0.495). base.yaml now sets
    `fixed_chunk_tokens: 60`, `fixed_chunk_overlap: 8`.
  - Structure chunks beat every fixed size on recall@5 and MRR, for all three retrievers
    (hybrid 0.754 / 0.649 vs at best 0.723 / 0.592). Larger fixed windows raise recall@10
    (dense fixed 400: 0.815) but bury the answer lower (MRR 0.452) at about 3x the context.
  - Caveat for step 2: fixed 60 hands the model about half the context of structure chunks
    (298 vs 590 words in the top 5), so the end-to-end chunking comparison is not
    budget-matched either.
- **End-to-end results** (dev, 77 questions, `answer_v2`, k=5; `results/2026-11-18_p1_c3_rag*`,
  commit `8940e52`, clean tree, 0 errors; the Nov 10 hybrid run is
  `results/2026-11-10_p1_c3_rag_answer_v2`, commit `a34901e`; structure chunks unless noted;
  acc ans = answerable rows, wr abst = wrong abstain, cite = citation hit,
  halluc = unanswerable rows, confl/multi = conflict/multihop accuracy, tokens and sec = mean
  input tokens and latency per answerable row):

  | C3 run | acc all | acc ans | wr abst | halluc | cite | confl | multi | tokens | sec |
  |---|---|---|---|---|---|---|---|---|---|
  | hybrid, Nov 10 | 0.870 | 0.877 | 0.031 | 0.167 | 0.754 | 0.500 | 0.923 | 3608 | 6.5 |
  | hybrid, re-run | 0.857 | 0.862 | 0.046 | 0.167 | 0.738 | 0.500 | 0.846 | 3621 | 6.5 |
  | BM25 | 0.870 | 0.877 | 0.031 | 0.167 | 0.723 | 0.571 | 0.846 | 3414 | 6.3 |
  | dense | 0.883 | 0.877 | 0.015 | 0.083 | 0.738 | 0.571 | 0.923 | 3739 | 7.4 |
  | hybrid, fixed 60 | 0.818 | 0.815 | 0.092 | 0.167 | 0.692 | 0.500 | 0.923 | 2905 | 9.7 |

  - **Run-to-run noise:** the two identical hybrid + structure runs disagree on 1 of 77
    questions (CR-005: correct on Nov 10, not on the re-run). CR-005 is also the one question
    every variant gains over the re-run, so it behaves like a coin flip. One pair of runs is a
    weak estimate; #17's three repeats will measure noise properly.
  - **Per question vs the hybrid re-run:** BM25 +3 / -2 (net +1), dense +4 / -2 (net +2),
    fixed 60 +2 / -5 (net -3). Four of the five fixed-60 losses are NHANES codebook questions
    (NH-006, NH-021, NH-024, NH-041). In all four, retrieval ranks the gold chunk first, but
    the 60-word window ends before the code table, and the model says so (NH-024: "The MCQ035
    entry is cut off at 'Codes: Code or Value | Value'"). Three are abstentions, one partial.
    So recall@k counts a hit when the needed text isn't in the chunk; structure chunks keep a
    variable's codes together.
  - **Retrievers:** BM25 and dense are within one or two questions of hybrid, about the size
    of the noise. Dense's lower hallucination rate (0.083 vs 0.167) is one question (NH-046,
    out of 12 unanswerable). Retrieval-only, hybrid has the best recall@1 and MRR.
  - **Chunking:** structure chunks beat fixed 60 on retrieval (recall@5 0.754 vs 0.723) and
    end to end (net 3 questions; wrong abstain 0.046 vs 0.092; citation hit 0.738 vs 0.692),
    with the caveat that fixed 60 gives about half the context.
  - **Latency is not comparable here:** the fixed run (9.7 s) ran after a wifi outage, and two
    dense questions (OM-017, OM-018) failed during the outage and were redone with
    `--resume` at the same commit.
- **Champion for #17: DECIDED (Ryan, 2026-11-19).** Keep **hybrid + structure** (the D18
  default). No variant beats it by more than about two questions, which is at the level of
  the observed noise, and the pre-set rule was to switch only for a gain larger than that.
  BM25, dense and fixed 60 are reported as ablations.

## D-next - DECIDED (Ryan, 2026-11-19): P1 judge validation against hand labels
- **Why:** the judge (`judge_v1`) is the same model as the generator (D20), so its verdicts are
  checked against Ryan's hand labels before any P1 number is reported.
- **Sample:** `eval/judge_label_sample.csv`, 30 model-judged dev answers from the four Nov 10
  runs (C1, C2 v2, C3 v1, C3 v2), drawn round-robin over the judge's verdicts (seed 0), so the
  judge said correct / partially_correct / incorrect 10 times each. The sheet never shows the
  judge's verdict. Because rare verdicts are oversampled, agreement here is not an accuracy
  estimate for any condition.
- **How the labels were made:**
  - Each item was shown as an evidence card (`scripts/judge_evidence_cards.py`): the corpus
    text of the sections the gold cites and the gold's `verify_sql` result, next to the answer.
    No model call, no judge output.
  - Verdicts are Ryan's. Claude showed the cards and quoted the rubric when asked, and gave no
    verdicts. One factual check on Ryan's request (J25: SMQ_J item order and SMQ895 counts).
  - J23 was changed from correct to incorrect before freezing: Ryan had misread the item code,
    caught when Claude pointed out the answer names a different item (AGQ030) from the gold
    (MCQ053).
  - Notes on non-correct labels: J02's is Ryan's; the other seven (J09, J11, J14, J20, J23,
    J26, J29) were drafted by Claude from the answer-vs-gold comparison at Ryan's request (the
    freeze commit's message says "six"; seven is right).
- **Frozen labels (headline), commit 624e716** (`results/2026-11-19_p1_judge_agreement/`):
  agreement 0.50, Cohen's kappa 0.25. Human labels: 22 correct, 4 partially_correct,
  4 incorrect.
  - In all 15 disagreements the judge was stricter than Ryan, never more lenient: the
    opposite of self-preference. The risk for the report is that judged accuracy understates,
    not overstates.
  - 12 of the 15 were conflict or multihop golds with two parts (a conclusion plus the reason):
    the judge required the reason; Ryan had credited the conclusion.
  - Ryan's unanswerable labels were inconsistent: J05 and J08 (C3) correct, J11 and J29 (C1)
    incorrect, although all four give specific names or figures.
- **Rubric reading (Ryan, 2026-11-19):** the reason is a required key fact. For conflict
  questions it is the doc/data conflict being tested, so a bare conclusion gets partial credit.
  `judge_v1` already reads it this way and is unchanged; nothing is re-judged.
- **Devil's-advocate review:** a read-only Claude reviewer (personal agent, not in the repo)
  argued the neighbouring verdict for each frozen label and rated the case strong / plausible /
  weak, without giving verdicts. It did not open run outputs, but it read the then-unnumbered
  D20 entry, whose lines on hallucinations hint at the judge's verdicts on NH-046 and NH-049
  (J05, J08, J11, J29). Result: 10 strong, 8 plausible, 12 weak.
- **Post-review labels (secondary), commit 242499e**
  (`results/2026-11-19_p1_judge_agreement_post_review/`): Ryan accepted the 10 strong
  challenges (J02, J05, J08, J15, J17, J18, J20, J21, J27, J30) and kept his frozen labels on
  the 8 plausible ones (J03, J06, J09, J12, J14, J23, J24, J26; the commit message says 7).
  Agreement 0.80, kappa 0.70.
  Human labels: 14 correct, 8 partially_correct, 8 incorrect. In all 6 remaining
  disagreements the judge is still the stricter one.
  - This number is biased toward the judge: the changes were made by accepting a same-model
    reviewer's arguments, and all 10 accepted changes were on items where the judge had
    disagreed. Report the frozen number as the validation result and this one as a sensitivity
    check.
- **Gold-note ambiguities found by the review** (recorded only; gold is frozen, D11): MI-028
  "the same link" reads as provenance rather than an accepted alternative; CR-012 "allow
  alternatives" scope; NH-037 whether "join on SEQN" is required; NH-042 whether the storage
  artifact is required; CR-016 trimming alone matches 3,833 of 16,441 rows; MI-005 note is a
  leftover drafting instruction.
- **Limitations:** one annotator, 30 items (one item moves agreement by 3.3 points), the
  reviewer is the same model family as the judge, and labels cover dev runs only.
- **Revisit if:** a second human annotator (e.g. Skylar on the SME sample) becomes available,
  or the judge prompt changes (re-validate on the same sheet).

## D-next - PROPOSED (Ryan, 2026-11-27): condition 4 (RAG + SQL verification) design
- **Pipeline (fixed, no open agent loop):** C3 retrieval unchanged (hybrid + structure, k = 5),
  then one planning call (`verify_plan_v1`) writes up to `verify.max_queries` = 3 read-only
  SELECT queries; `sql_tool.run_sql` runs each once (row cap 50, 10 s timeout); each result is
  appended as a passage `[sql:N]`; the answer call uses the frozen `answer_v2` prompt. Code:
  `medrag/verify/checks.py`, `configs/c4_rag_verify.yaml`.
- **Why fixed:** the `claude_cli` backend makes single tool-less calls (D20), and a fixed
  pipeline makes C4 differ from C3 in one thing, access to the data, so a C3 vs C4 gap can be
  attributed to it. An agent loop (retry failed SQL, search again) is future work.
- **Planner hints:** the planner sees the tables and columns behind the retrieved passages, in
  every schema that has them (e.g. both `mimic_demo_v1_0_hosp.prescriptions` and the v2.2
  one), derived from the doc name only. Nothing question-specific is given; the prompt names
  generic checks (existence, value counts, join matches).
- **Why `[sql:N]` passages:** results reach the frozen answer prompt without editing it, and
  answers can cite them. A cited `sql:N` is valid (not an invalid citation) but never counts
  as a gold citation hit.
- **Cost:** two model calls per question; `usage` and `cost_usd` sum both, latency covers both.
  A failed planning call fails the item (redone by `--resume`).
- **Smoke run** (`results/2026-11-27_p1_c4_rag_verify_smoke5`, dirty tree, first 5 dev rows):
  5 answers, 0 errors, 2-3 queries per question, all answers cite at least one `[sql:N]`.
- **Dev run** (`results/2026-11-27_p1_c4_rag_verify`, commit dd485f2, clean, judged with
  `judge_v1`), against the hybrid + structure C3 re-run (`2026-11-18_p1_c3_rag`):

| run | acc (all) | acc (answerable) | wrong abstain | hallucination | conflict | multihop | lookup | mean input tokens | mean latency s |
|---|---|---|---|---|---|---|---|---|---|
| C3 re-run | 0.857 | 0.862 | 0.046 | 0.167 | 0.500 | 0.846 | 1.000 | 3621 | 6.5 |
| C4 | 0.922 | 0.954 | 0.015 | 0.250 | 0.929 | 0.923 | 0.974 | 8378 | 13.4 |

  - By `needs_data`: yes 0.556 -> 1.000 (n = 9), no 0.897 -> 0.912 (n = 68). By source: cross
    0.600 -> 1.000 (n = 10), nhanes 0.900 -> 0.833 (n = 30).
  - 199 queries, 0 SQL errors, every item ran at least one; 76 of 77 answers cite a `[sql:N]`.
  - Per question vs C3: 8 gains (CR-005, CR-012, CR-016, CR-017, MI-028, MI-034, NH-042,
    OM-014), 3 losses (NH-026, NH-035, NH-052), net +5. The two identical C3 runs differ on 1
    question (ablation entry), so the gain is above that noise; #17's repeats will measure it.
  - **Failure modes (all three losses):**
    - NH-026: the data was used to override the codebook. The answer reports the codebook's
      "End of Section" but concludes BPQ080 from the query results.
    - NH-035: the stored ~5.4e-79 zeros (D10) made `WTMEC2YR = 0` match no rows, so the
      answer claims there are none; the data artifact misled the check.
    - NH-052 (unanswerable): the queries computed a median income bracket, so the answer gives
      one; this is the one extra hallucination (3 of 12 vs 2 of 12).
  - Cost: about 2.3x the input tokens and 2x the latency of C3 (two calls per question).
- **Revisit if:** most queries fail (then add one retry round with the error text), or the
  test-split run doesn't fit the seat's limits.
