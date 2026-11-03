# eval/ - research-integrity rules (loaded when working here)

- Never edit a gold answer to match system output. If a gold answer looks wrong, flag it to Ryan
  with evidence (doc section + SQL output) and let a human decide; record the change in `notes`.
- Never move a question between `dev` and `test` once any results exist. Don't read test
  outputs while tuning.
- Every gold answer cites `gold_doc` + `gold_section`. Data-verifiable answers include a
  `verify_sql` that runs against the read-only DuckDB.
- Run `verify_sql` through `medrag.db.connect()` to check it before adding a question.
- NHANES special codes (7/9, 77/99, 777/999) are refused/don't know, never values.
- MIMIC conflict questions: data is v1.0 (has `core`), docs describe v2.x.
- Schema and question types: `eval/README.md`.
