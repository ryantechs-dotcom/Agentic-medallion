# Problem 1 plan - RAG vs. non-RAG for documentation Q&A (owner: Ryan)

## Hypothesis
Retrieval improves accuracy on documentation questions over closed-book answering, and adding a
data-verification step (querying DuckDB) further improves accuracy specifically on questions where
documentation and data disagree - at some cost in latency and tokens.

## Order of work (do not reorder)
1. Sanity-check the snapshot (manifest has no failures; OMOP/MIMIC patient alignment as expected).
2. **Build the evaluation set before any retrieval code** - otherwise questions drift toward what
   the system can answer.
3. Chunk + index the corpus.
4. Run conditions from simplest to most complex.
5. Final run on the held-out test split; write results into the report draft.

## Evaluation set (`eval/questions.csv`)
Target 100-150 questions. Columns (see `eval/questions_template.csv`):

| column | meaning |
|---|---|
| qid | stable id, e.g. `NH-001`, `MI-014`, `OM-007` |
| split | `dev` or `test` (decide once, ~60/40; never move a question after results exist) |
| source | `nhanes`, `mimic`, `omop`, or `cross` |
| qtype | `lookup`, `multihop`, `conflict`, `unanswerable` |
| subtype | conflict / unanswerable kind (below); empty otherwise |
| question | the question as a user would ask it |
| gold_answer | short canonical answer (empty for unanswerable) |
| gold_doc | file under `data/docs/` that supports the answer |
| gold_section | variable / table / heading within that doc |
| gold_evidence | extra evidence for multihop rows: `doc#section;doc#section` (for retrieval recall) |
| verify_sql | optional SQL against `data/project.duckdb` that confirms the answer |
| needs_data | `yes` if part of the gold (counts, concept IDs, ETL choices) is not in `data/docs` |
| guessable | `yes` if answerable closed-book from naming conventions (e.g. 7 = Refused) |
| cluster | related questions that must share a split (prevents dev -> test leakage) |
| author | who wrote it |
| reviewed_by | SME reviewer (Skylar) for the agreement sample |
| notes | ambiguity, acceptable alternatives, why it is a conflict |

Question types and what each tests:
- **lookup** - answer is in one chunk (basic retrieval)
- **multihop** - needs two or more chunks/sources (e.g., MIMIC field -> OMOP table/field)
- **conflict** - documentation alone is misleading; data shows otherwise (the novelty claim).
  Subtypes, so the conflict result can be broken down:
  - `version_mismatch` - v2.x docs vs the v1.0 data (the main intended case)
  - `doc_vs_data` - same version, but a documented item is absent or filled differently
  - `doc_inconsistent` - the docs contradict each other
  - `data_as_loaded` - docs are right, the loaded data differs (e.g. NHANES zeros, D10)
  - `data_only` - the docs are silent; only the data answers it
- **unanswerable** - not in the corpus; correct behavior is to say so (hallucination resistance).
  Subtypes: `false_premise` (the corpus shows the thing does not exist, e.g. a complete column
  list) and `out_of_scope` (outside the corpus but possibly world-knowable; `notes` say what
  answer is acceptable).

Report results per qtype, plus split by `needs_data` (conditions 1-3 cannot get the data part
by construction) and `guessable` (keeps the closed-book baseline from looking misleadingly
strong).

Aim for a rough balance across types and sources; conflicts are the hardest to write, so start
collecting them from anything surprising in the data. Skylar independently answers ~20 sampled
questions; report agreement.

## Chunking (one design decision + one ablation)
Structure-aware chunks matching each source's natural unit, with metadata
(source, table/file, variable, version/cycle):
- NHANES codebooks: one chunk per variable
- MIMIC docs: one chunk per table section / column description
- OMOP spec: one row of the field-level CSV per chunk (table-level rows as separate chunks)
Ablation: fixed-size chunks with overlap, same retriever.

## Conditions
1. Closed-book (no retrieval)
2. Long-context oracle-ish baseline: the relevant whole document pasted into the prompt
   (tests whether retrieval is needed at all)
3. RAG: BM25, dense embeddings, hybrid
4. RAG + verification: the model can also run read-only SQL against `data/project.duckdb`

Keep model, temperature, and prompt template fixed across conditions; record them per run.

## Metrics
- Answer accuracy (exact/normalized match where possible; rubric-based LLM judge otherwise,
  with a human-checked sample to validate the judge)
- Citation correctness (cited chunk actually supports the answer)
- Retrieval recall@k and MRR (against gold_doc/gold_section)
- Unanswerable handling: abstention rate vs. hallucination rate
- Cost (tokens) and latency
Break all metrics down by qtype and source; conflicts are where condition 4 should differ.

## Interface with Problem 2 (agree with Skylar early)
Skylar's mapping agents will likely call this retriever as a tool. Proposed contract:
input `{query, filters?: {source, table}, k}` -> output
`{answer?, chunks: [{doc, section, text, score}], verified?: bool, sql?: str}`.

## Timeline
| By | Milestone |
|---|---|
| Nov 3 | Snapshot checked, question set drafted, interface agreed with Skylar |
| Nov 10 | Question set reviewed (SME sample), index built, conditions 1-2 run on dev |
| Nov 17 | Condition 3 variants + chunking ablation on dev |
| Nov 24 | Condition 4, final test-split run, results written into the draft |
Reconcile with the team tracker; the tracker wins on conflicts (or gets updated).
