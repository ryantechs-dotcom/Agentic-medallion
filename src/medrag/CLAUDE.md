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
- Stubs here are docstring-only on purpose: don't implement retrieval before the eval set
  exists (PROBLEM1_PLAN, "Order of work").
