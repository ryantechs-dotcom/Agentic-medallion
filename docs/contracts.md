# Shared formats (contracts)

Tracker task 4. These are the formats that cross an owner boundary or a pipeline layer. Code
checks them with `medrag.contracts.validate(record, kind)` at each boundary and fails loudly.

| # | Format | Owner | Status |
|---|---|---|---|
| 1 | Conventions | all | PROPOSED |
| 2 | Corpus record | Ryan (P1) | PROPOSED, implemented (`corpus/corpus_v1.jsonl`) |
| 3 | Chunk | Ryan (P1) | PROPOSED |
| 4 | Retriever tool | Ryan (P1) ↔ Skylar (P2) | PROPOSED, needs Skylar |
| 5 | SQL tool | Ryan (P1) ↔ Skylar (P2) | PROPOSED, needs Skylar |
| 6 | P1 eval set | Ryan (P1) | AGREED, frozen v1 (D11) |
| 7 | P2 column spec + ground truth | Skylar (P2) | Ground truth: Skylar's schema, AGREED when she approves; spec: PROPOSED until #14 starts |
| 8 | P3 conflict label | Jack (P3) | PROPOSED, draft for Jack |
| 9 | Run log | all | PROPOSED |
| 10 | Prompt versioning | all | PROPOSED |
| 11 | Column profile tool | Jack (P3, #7) ↔ Ryan (#9) ↔ Skylar (P2) | PROPOSED, needs Jack |

PROPOSED means "the owner accepts or edits it in review". A format becomes AGREED when the
owner approves the PR that changes it. After that, changes need a version bump and a line in
`docs/DECISIONS.md`.

## 1. Conventions
- JSONL files are UTF-8 with one JSON object per line, `\n` line endings and sorted keys.
  CSV files are UTF-8 with a header row.
- Every artifact records its format version, either in its name (`corpus_v1.jsonl`,
  `answer_v1.txt`) or in an accompanying manifest / `config.json`.
- **One layout per problem** (P1 is the shared `medrag` package):

  | | P1 (Ryan) | P2 (Skylar) | P3 (Jack) |
  |---|---|---|---|
  | code | `src/medrag/` | `src/medrag_p2/` | `src/medrag_p3/` |
  | prompts | `src/medrag/generation/prompts/` | `src/medrag_p2/prompts/` | `src/medrag_p3/prompts/` |
  | eval / ground truth | `eval/` (top level, frozen v1) | `eval/p2/` | `eval/p3/` |
  | runs | `results/<date>_p1_<condition>/` | `results/<date>_p2_<condition>/` | `results/<date>_p3_<condition>/` |
  | Drive | `03_eval/p1/`, `04_results/p1/` | `03_eval/p2/`, `04_results/p2/` | `03_eval/p3/`, `04_results/p3/` |

  `scripts/sync_drive.py` sends only your own problem's folders (`MEDRAG_PROBLEM` in `.env`).
- Ids are stable strings that never get reused. `doc` is always a path relative to `data/docs/`
  (e.g. `nhanes/2017-2018_DIQ_J.htm`), so it lines up with `gold_doc` in the eval set.
- `source` is one of `nhanes`, `mimic`, `omop` (plus `cross` in the eval set only).
- Optional fields are marked `?`. Absent and `null` mean the same thing.

## 2. Corpus record
Built by `scripts/build_corpus.py` from `data/docs` (loaders in `medrag/corpus/loaders.py`).
There is one record per natural unit of each source. See `docs/DECISIONS.md` D13.

| field | type | meaning |
|---|---|---|
| id | str | `<doc>#<section>`, with `~2`, `~3` for a repeated section name in one doc |
| doc | str | path under `data/docs/` |
| section | str | NHANES variable name or narrative heading; MIMIC heading (backticks removed); OMOP `table` or `table.field` (lowercase) |
| source | str | `nhanes` \| `mimic` \| `omop` |
| kind | str | `nhanes_variable`, `nhanes_narrative`, `mimic_section`, `omop_table`, `omop_field` |
| title | str | human-readable heading, e.g. `DIQ010 - Doctor told you have diabetes` |
| text | str | the title line, then the section text (whitespace normalized, nothing else changed) |
| order | int | position in the corpus; records of one `doc` are in document order |
| metadata | dict | NHANES `component`, `component_title`, `cycle`; MIMIC `module`, `page`, `description`, `doc_version` (`v2.x`); OMOP `table`, `field?`, `cdm_version` (`5.3`); all: `file`, `heading_path?` |

An NHANES variable record lists its header fields (Variable Name, SAS Label, English Text,
Target, ...) and then one line per code row: `code | description | count | skip to`. Special
codes such as `7 | Refused` and `9 | Don't know` are therefore part of the text.

**Gold matching rule:** a record supports a gold reference `(gold_doc, gold_section)` when
`doc == gold_doc` and `gold_section` appears in `section`, or else in `text`. The comparison
ignores case and whitespace (`contracts.matches_gold`). The rule allows for gold sections that
are phrases rather than headings, such as `core module has been removed`. Retrieval recall@k
and MRR use it.

Example (shortened):
```json
{"id": "nhanes/2017-2018_DIQ_J.htm#DIQ010", "doc": "nhanes/2017-2018_DIQ_J.htm",
 "section": "DIQ010", "source": "nhanes", "kind": "nhanes_variable",
 "title": "DIQ010 - Doctor told you have diabetes", "order": 158,
 "text": "DIQ010 - Doctor told you have diabetes\nVariable Name: DIQ010\n...\n7 | Refused | 0 | ",
 "metadata": {"component": "DIQ_J", "component_title": "Diabetes (DIQ_J)",
              "cycle": "2017-2018", "file": "2017-2018_DIQ_J.htm",
              "heading_path": ["Codebook and Frequencies", "DIQ010"]}}
```

## 3. Chunk
Made from corpus records by `medrag/corpus/chunking.py` (task 9). Structure chunking is about
one chunk per record, with long records split. Fixed chunking re-joins each `doc`'s records in
`order` and windows the text.

| field | type | meaning |
|---|---|---|
| chunk_id | str | `<record id>` (structure) or `<doc>@<n>` (fixed); `#part<n>` when split |
| record_id | str | the corpus record it came from (fixed chunks: the first record they overlap) |
| doc, section, source | str | copied from the record |
| strategy | str | `structure` \| `fixed` |
| text | str | chunk text |
| metadata | dict | record metadata plus `chunk_tokens`, `overlap?` |

## 4. Retriever tool (P1 ↔ P2)
P2's agents call this as a tool; P1 condition 3/4 uses the same function.

input:
```json
{"query": "What does DIQ010 = 9 mean?", "k": 5,
 "filters": {"source": "nhanes", "table": "DIQ_J"}}
```
`filters` is optional. `table` matches `metadata.component` (NHANES), `metadata.page` (MIMIC)
or `metadata.table` (OMOP).

output:
```json
{"chunks": [{"chunk_id": "nhanes/2017-2018_DIQ_J.htm#DIQ010", "doc": "...",
             "section": "DIQ010", "text": "...", "score": 12.3}],
 "answer": null, "verified": null, "sql": null}
```
`chunks` is sorted by descending score, with at most `k` entries. `answer`, `verified` and
`sql` are filled only when the tool is the full condition-4 pipeline instead of plain
retrieval. Each chunk validates as `retrieved_chunk`.

## 5. SQL tool (condition 4 and the P2 verifier)
input: `{"sql": "SELECT ...", "max_rows?": 50}`. Only one `SELECT` or `WITH` statement is
allowed; anything else is rejected before it runs. Queries run through `medrag.db.connect()`
(read-only).

output: `{"columns": [str], "rows": [[...]], "truncated": bool, "error": str | null}`. The row
cap and timeout come from `verify.max_rows` and `verify.timeout_s` in `configs/base.yaml`.

## 6. P1 eval set (frozen)
`eval/questions.csv`; the column definitions are in `docs/PROBLEM1_PLAN.md`, "Evaluation set".
`eval/qa_eval.jsonl` holds the same rows as `{qid, split, question, answer, source, qtype,
subtype, gold_doc, gold_section, gold_evidence, needs_data, guessable}`. This is frozen v1
(132 questions, 77 dev / 55 test, sha256 in D11). It is listed here so others can rely on it;
nothing in it changes without a new version.

## 7. P2 column spec and ground truth (Skylar)
**Ground truth** (`eval/p2/p2_ground_truth_draft.csv`, frozen later as `p2_ground_truth.csv`;
design in `docs/DECISIONS.md` D16). One row per (MIMIC v1.0 source column, OMOP target field).
The source of truth for the columns is `medrag_p2.ground_truth.REQUIRED_COLUMNS`, and
`python -m medrag_p2.ground_truth` checks every row (shape, ETL evidence, columns exist,
`verify_sql` returns 0 mismatches).

| field | meaning |
|---|---|
| gt_id | `P2-001`, ... |
| source_schema, source_table, source_column | e.g. `mimic_demo_v1_0_core`, `patients`, `gender` |
| target_table, target_field | OMOP target; empty for `not_mapped` |
| is_primary | `Y` for the column's main target (top-1 accuracy), else `N` |
| mapping_type | `direct`, `transform`, `concept_lookup`, `derived`, `not_mapped` |
| transform_rule | the rule in words or SQL, e.g. `F -> 8532, M -> 8507, else 0` |
| concept_ref | lookup file used (`custom_mapping_csv/gcpt_*.csv`), if any |
| acceptable_alternatives | `table.field;...` an agent may defensibly propose instead |
| etl_evidence | `file:line[-line]; ...` in the snapshot's OHDSI/MIMIC ETL copy |
| verify_sql | returns one row `(n_checked, n_mismatch)`; passes when `n_checked > 0`, `n_mismatch = 0` |
| split | `dev` \| `test`, by whole source table |
| author, reviewed_by, notes | provenance and caveats (code/data disagreements are P3 candidates) |

**Column spec** (PROPOSED until #14 starts): one JSON object per (source column, proposed
target) that the P2 agents write to `outputs.jsonl` (section 9). The field names match the
ground truth, so scoring is a join on `(source_table, source_column, target_table,
target_field)`. Validate with `medrag.contracts.validate(spec, "p2_spec")`.

| field | type | meaning |
|---|---|---|
| spec_id | str | `<source_table>.<source_column>[#n]` |
| source_schema, source_table, source_column | str | as in the ground truth |
| target_table, target_field | str \| null | null when the agent proposes `not_mapped` |
| mapping_type | str | same enum as the ground truth |
| target_type | str \| null | OMOP datatype (`integer`, `varchar(50)`, ...) |
| transform_rule | str | the proposed rule |
| evidence | list | `[{"doc", "section"}]` from the retriever and/or `[{"sql", "result"}]` from the SQL tool |
| confidence | number | 0-1, as the agent reports it |
| status | str | `proposed` \| `verified` \| `rejected` \| `needs_human` (goes to a HITL decision card) |
| agent | str | `single` \| `multi:<role>` |

The run id comes from the results folder name, so specs don't repeat it.

## 8. P3 conflict label (Jack - PROPOSED draft)
One row per labeled example (`p3_labels.csv` or JSONL):

| field | type | meaning |
|---|---|---|
| conflict_id | str | stable id, e.g. `P3-001`, or a P1 `qid` for seed examples |
| source | str | `nhanes` \| `mimic` \| `omop` \| `cross` |
| item | str | the variable / column / field the conflict is about |
| text | str | the input the classifier sees (doc excerpt + data observation) |
| conflict_type | str | `version_mismatch`, `doc_vs_data`, `doc_inconsistent`, `data_as_loaded`, `data_only`, `no_conflict` |
| origin | str | where the problem arises: `entered`, `stored` or `reported` (PROJECT_CONTEXT) |
| evidence | list | `[{"doc", "section"}]` and/or `[{"sql", "result"}]` |
| split | str | `train` \| `dev` \| `test` |
| labeled_by | str | who assigned the label |

`conflict_type` reuses the P1 conflict subtypes, so the 23 P1 conflict questions (14 dev /
9 test) can be seed labels. P1 test-split questions must stay out of P3 training data.

## 9. Run log (all problems)
Every run writes `results/<YYYY-MM-DD>_<pN>_<condition>/` (e.g.
`2026-11-10_p1_c1_closed_book/`), which `scripts/sync_drive.py` copies to
`04_results/<pN>/`. The folder holds three files:
- `config.json`: the merged config (`medrag.config.load_config`), plus `git_commit`,
  `prompts` (`{role: {"file", "sha256"}}` from `load_prompt`; P1 uses role `answer`, P2
  multi-agent has one entry per agent), `corpus_sha256` (from
  `corpus/corpus_v1.manifest.json`), `snapshot` (data snapshot version), `split` and
  `started_at`.
- `outputs.jsonl`: one line per eval item, which validates as `run_output`:

| field | type | meaning |
|---|---|---|
| qid | str | eval item id |
| answer | str \| null | model answer (null on error) |
| citations | list | chunk_ids the answer cites |
| retrieved | list | `[{chunk_id, doc, section, score}]`, in rank order (empty for closed-book) |
| tool_calls | list | `[{"tool", "input", "output_summary", "latency_s"}]` |
| usage | dict | `{"input_tokens", "output_tokens"}` |
| latency_s | number | wall-clock seconds for the item |
| error | str \| null | error message, if any |

  P2 and P3 add their own fields (the spec or the predicted label) next to these.
- `metrics.json`: metric -> value, overall and broken down (P1: by `qtype`, `source`,
  `needs_data`, `guessable`).

Numbers in the report come only from these files.

## 10. Prompt versioning
- Each problem keeps its prompts in its own package (table in section 1). One file per
  version, named `<purpose>_v<N>.txt`, e.g. `answer_v1.txt`, `proposer_v1.txt`.
- Load with `medrag.generation.load_prompt(name, prompts_dir)`. `prompts_dir` defaults to the
  P1 folder; P2 passes `medrag_p2.PROMPT_DIR`. It returns `{"file", "text", "sha256"}`, and
  `file` (repo-relative) plus `sha256` go into `config.json` under `prompts`.
- Never edit a version that has results; copy it to `_v<N+1>` and change the copy.
- Compared conditions use the same prompt version unless the prompt is the thing being
  compared. P2 single- and multi-agent share their base instructions.

## 11. Column profile tool (Jack's profiler #7; used by #9, #14, #15 - PROPOSED)
input: `{"schema": "mimic_demo_v1_0_core", "table": "patients", "column": "gender"}`

output:
```json
{"dtype": "VARCHAR", "n_rows": 100, "n_null": 0, "n_distinct": 2,
 "top_values": [{"value": "M", "count": 57}, {"value": "F", "count": 43}],
 "min": null, "max": null, "special_codes": []}
```
- `top_values` holds at most `profile.top_k` values (a config key to add with #7), most
  frequent first.
- `min` / `max` are set for numeric and date columns only.
- `special_codes` lists NHANES-style refused / don't-know codes (7/9, 77/99, ...) found in the
  column. They are reported separately and never counted as values.
- Read-only, through `medrag.db.connect()`. Until #7 lands, P2 can use a stub with this
  interface (and logs that in the run config).

The example shows the real profile of `patients.gender` in the v1.0 demo.
