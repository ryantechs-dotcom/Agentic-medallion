# src/medrag_p2 - Problem 2 rules (loaded when working in this package)

Owner: **Skylar**. Problem 2 = schema mapping and Silver spec generation, single-agent vs.
multi-agent. Code conventions from `src/medrag/CLAUDE.md` apply here too (pure functions,
config over literals, validation at boundaries, tests without an API key or network).

## The comparison
- **Champion, multi-agent:** retriever -> proposer -> verifier. The verifier checks the
  proposer's claims against the data with SQL and can send a spec back.
- **Challenger, single agent:** one agent with all tools (`search_docs`, `profile_column`,
  `run_sql`).
- Both use the same LLM, temperature and base prompt text, so the result reflects the
  architecture, not the wording. Prompts live in `prompts/` as `<role>_vN.txt` and load with
  `medrag.generation.load_prompt(name, PROMPT_DIR)` (docs/contracts.md section 10); never edit
  a version after a run has used it, copy it to `_vN+1` instead.
- Parameters come from config (proposed: `configs/p2_single.yaml`, `configs/p2_multi.yaml`),
  never literals in code.

## Output
- One JSON spec per source column: target table/field, type, cleaning rule, evidence (doc
  section and/or SQL result), confidence.
- The spec format is docs/contracts.md section 7 (PROPOSED until #14 starts; its field names
  match the ground truth). Validate every spec with `medrag.contracts.validate(spec,
  "p2_spec")`, so the format can't drift between conditions. Change the format there first.

## Ground truth (`eval/p2/`, design in docs/DECISIONS.md D16)
- One row per (MIMIC v1.0 source column, OMOP target field). `is_primary` marks the main target;
  `not_mapped` rows record columns the ETL drops. Field level only, no concept values.
- Score against MIMIC **v1.0**. The snapshot's ETL code is the v2.x version, so rows follow the
  OMOP demo data, with the ETL lines cited as evidence. Code/data disagreements go in `notes`.
- Every row must pass `python -m medrag_p2.ground_truth` (cited ETL lines exist and mention the
  column; `verify_sql` returns n_checked > 0 and n_mismatch = 0).
- Acceptable alternatives are written before any agent output exists. Never edit a gold row,
  alternative or split to match system output. After the first agent run, any change needs a
  new version and a reason in DECISIONS.md.
- Drafted rows say `author = Claude (draft)`; Skylar reviews, then Nikhil. The frozen
  `p2_ground_truth.csv` gets its sha256 logged in DECISIONS.md.
- Split by source table. Test tables are untouched until final runs.
- NHANES is excluded (no external expert mapping).

## Runs and metrics
- Each run writes `results/<date>_p2_<condition>/` (config, inputs, retrieved chunks, tool
  calls, outputs, scores); synced to Drive `04_results/p2/`. Report numbers come only from there.
- At least 3 runs per condition; report the mean and the spread.
- Metrics: mapping precision/recall/F1 and top-k accuracy, cleaning-rule correctness, share of
  specs with valid evidence, verifier catch rate, tool calls, latency, cost.

## Dependencies (don't modify; agree changes with the owner)
- `medrag.db` (read-only data) and `medrag.retrieval` (docs/contracts.md sections 4-5): Ryan.
- `profile_column` comes from Jack's Bronze profiler (#7). If a dependency isn't ready, put a
  stub behind the same interface and log that in the run config.

## Human in the loop (#19)
- A conflict card shows: the question, doc evidence, data evidence, impact, a proposed default,
  and 2-3 options. Approving a card applies the rule.
- The precedent store (reusing past decisions) is the first thing to cut if time runs short.
