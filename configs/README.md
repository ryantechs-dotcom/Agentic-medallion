# configs/

`base.yaml` holds shared defaults. Each experimental condition gets its own small file that only
overrides what differs, e.g. `c1_closed_book.yaml`, `c3_bm25.yaml`, `c4_rag_verify.yaml`.
Thresholds and parameters live here, never hardcoded in `src/`. The run's merged config is copied
into `results/<date>_<pN>_<condition>/config.json`.
