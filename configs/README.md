# configs/

`base.yaml` holds shared defaults. Each experimental condition gets its own small file that only
overrides what differs: `c1_closed_book.yaml`, `c2_long_context.yaml`, `c3_rag.yaml` (and
`c4_rag_verify.yaml` next). Retrieval ablations override `retrieval.*` via `run_p1.py --kind /
--chunking` instead of a new file.
Thresholds and parameters live here, never hardcoded in `src/`. The run's merged config is copied
into `results/<date>_<pN>_<condition>/config.json`.
