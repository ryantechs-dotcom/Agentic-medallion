# Architecture (Problem 1 code)

## Data flow
```
data/docs/{mimic,omop,nhanes}
  -> corpus/loaders.py     section-level records -> corpus/corpus_v1.jsonl (build_corpus.py)
  -> corpus/chunking.py    chunks {chunk_id, record_id, doc, section, source, strategy, ...}
  -> retrieval/*.py        top-k chunks {doc, section, text, score}
  -> generation/llm.py     answer + citations (+ verify/sql_tool.py calls in condition 4)
  -> evaluation/runner.py  results/<date>_p1_<condition>/{config.json, outputs.jsonl, metrics.json}
  -> evaluation/metrics.py metrics by qtype and source
```
`data/project.duckdb` is reached only through `db.py` (read-only), and is used by
`verify/sql_tool.py` and by `verify_sql` checks on the eval set. Every format in this flow is
defined in `docs/contracts.md` and checked with `medrag.contracts.validate` at each boundary.

## Module map
| Module | Responsibility | Condition |
|---|---|---|
| `contracts.py` | required fields per shared format; `validate`, gold matching rule | all |
| `config.py` | merge `configs/base.yaml` + condition file; resolve data dir (`MEDRAG_DATA_DIR`) | all |
| `db.py` | read-only DuckDB connection, schema list | 4, eval |
| `corpus/` | load docs, structure-aware and fixed-size chunking | 3, 4 |
| `retrieval/` | BM25, dense, hybrid behind one contract (`base.py`) | 3, 4 |
| `verify/sql_tool.py` | SELECT-only SQL tool for the model | 4 |
| `generation/` | LLM wrapper, versioned prompts | all |
| `evaluation/` | runner, metrics, LLM judge | all |

Conditions: 1 closed-book, 2 long-context (whole gold doc in prompt), 3 RAG, 4 RAG +
verification. See `docs/PROBLEM1_PLAN.md`.

## Retriever tool contract (shared with Problem 2)
Defined in `docs/contracts.md` section 4 (with the SQL tool in section 5). **PROPOSED, not yet
agreed with Skylar**: agreement happens in the review of the PR that adds contracts.md.

## Other problems (not owned here)
Problem 2 (Skylar, schema mapping agents) and Problem 3 (Jack, conflict classification) keep
their own code. They consume `medrag.retrieval` and `medrag.db` and should not modify them
without agreement. Problem 2 lives in `src/medrag_p2/` (agents, tools, spec validation) with
its prompt templates in `src/medrag_p2/prompts/`; Problem 3 follows the same pattern in
`src/medrag_p3/`. Both are installed by the same `pip install -e .`. The per-problem layout
(code, prompts, eval, results, Drive) is in `docs/contracts.md` section 1.

## Scripts
| Script | Purpose |
|---|---|
| `scripts/ingest_data.py` | rebuild data/ from public sources, pinned commits (snapshot owner only) |
| `scripts/make_snapshot.py` | freeze data/ into a versioned zip; `--verify` a download |
| `scripts/build_corpus.py` | build `corpus/corpus_v1.jsonl` + manifest from `data/docs`; `--check` for determinism |
| `scripts/draft_eval_questions.py` | build the P1 eval draft (generated lookups + `eval/handwritten_draft.csv`), check every row |
| `scripts/sync_drive.py` | copy results/ and eval/ to the team Drive (`04_results/pN`, `03_eval/pN`) |
| `notebooks/00_colab_setup.ipynb` | Colab bootstrap: mount Drive, verify + unzip snapshot, run folder (copy in Drive `06_colab/`) |
| `scripts/legacy/ingest_v1_unpinned.py` | the script that actually built snapshot v1 (unpinned `main`); kept for provenance |
