# src/medrag - code rules (loaded when working in this package)

Module map and data flow: `docs/ARCHITECTURE.md`. Methods and conditions: `docs/PROBLEM1_PLAN.md`.

- Only `db.py` opens DuckDB, always read-only. Other modules call `medrag.db.connect()`.
- Parameters and thresholds come from `medrag.config.load_config()`, never literals in code.
- Pure functions where possible (input -> output, no hidden state); I/O stays in `runner.py`
  and loaders.
- Validate shapes at layer boundaries (corpus -> chunks -> retrieval -> generation -> results):
  check required keys/columns and fail loudly.
- Keep the retriever contract in `retrieval/base.py` stable. Problem 2 (Skylar) calls it, so
  agree on changes with Skylar first.
- New behavior needs a test in `tests/`. Tests must not need an API key or network.
- PEP 8, 99-character lines. Prefer simple over clever: one function per rule, few classes.
- Shared formats are in `docs/contracts.md`; check them with `medrag.contracts.validate`.
  Changing a format means changing contracts.md (and agreeing with its owner) first.
- The eval set is frozen (D11) and the corpus is built (`corpus/`, D13). Chunking, retrieval,
  the SQL/profile tools and retrieval metrics are implemented (task 9); generation, the runner
  and the judge are still stubs (task 13).
- Corpus loaders only parse and normalize whitespace. Never clean, rewrite or drop source text
  to make a question easier; the gold-coverage test (`tests/test_corpus_snapshot.py`) must
  keep passing.
