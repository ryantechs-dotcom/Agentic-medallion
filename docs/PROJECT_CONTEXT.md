# Project context

## Course and deliverable
- Course: ADSP 32018 - NLP and Agentic AI (graduate)
- Team: Ryan, Jack, Skylar, Nikhil
- Final deliverable due **December 6, 2026**; full report draft compiled by **November 24**
- Team schedule started October 26 (six weeks). Task tracking lives in a single-sheet,
  32-task tracker (7 tasks per person + 4 shared, each with a "done when" criterion).

## Research framing
Many organizations have a "system of record" that is badly structured: overloaded tables, logic
that only makes sense if you read scattered documentation, codes that changed meaning over time.
A medallion architecture cleans this up in layers:

- **Bronze** - land the source unchanged (auditability)
- **Silver** - standardize, deduplicate, map codes; answers that any consuming team would agree on
- **Gold** - business-specific rules, thresholds, and definitions that depend on one team's judgment

The project asks whether LLMs can help build these layers, and specifically whether
**retrieving documentation and then verifying it against the actual data** beats either
documentation alone or the model's own knowledge.

## The three required comparisons
| # | Comparison | Owner | Ground truth |
|---|---|---|---|
| 1 | RAG vs. non-RAG for answering documentation questions | Ryan | Gold Q&A set built from the docs (+ SQL checks) |
| 2 | Schema mapping: single-agent vs. multi-agent | Skylar | MIMIC-IV demo -> OMOP CDM conversion + OHDSI ETL mappings |
| 3 | Conflict classification | Jack | Labeled conflicts surfaced in 1 and 2 |

Nikhil runs EDA and is evaluation lead / project manager. Skylar is the subject-matter expert who
independently validates a sample of gold answers (report inter-annotator agreement).

Conflicts can be framed by where they originate: how data is **entered** (questionnaire, charting),
how it is **stored** (raw tables), or how it is **reported** (OMOP / analytic definitions). That
framing helps route each conflict to the right human reviewer.

## Datasets
**MIMIC-IV Clinical Database Demo (PhysioNet), v1.0 and v2.2** - 100 de-identified ICU patients
from Beth Israel Deaconess. `hosp` (admissions, labs, prescriptions, diagnoses) and `icu`
(chartevents, inputevents...) modules; v1.0 also has `core`. Local item IDs, mixed text/numeric
values, units split across columns. License: ODbL v1.0. Plays the messy source system.

**MIMIC-IV Demo in the OMOP CDM v0.9 (PhysioNet)** - the same patients after the OHDSI ETL into
OMOP CDM 5.3.1 (person, visit_occurrence, measurement, drug_exposure, condition_occurrence...)
with standard vocabularies. Known limitation per the authors: inputevents/outputevents were not
fully incorporated. Plays the answer key - but reflects one ETL's choices.

**OHDSI/MIMIC ETL repo** - the SQL and `custom_mapping_csv/gcpt_*.csv` concept mappings behind
the OMOP conversion. Finer-grained ground truth than the OMOP output alone (shows which source
field and code went where). Uses MIMIC v1.0 staging (`st_core.sql`).

**NHANES 2017-2018 (CDC)** - survey + exam + lab data with per-file HTML codebooks: variable
definitions, skip patterns, special codes. Public domain. Plays the documentation-heavy source;
no OMOP ground truth, so it is used mainly for Problem 1 Q&A and conflict examples.

**OMOP CDM v5.3 table/field specs and MIMIC-IV docs** - part of the RAG corpus.

## Known limitations to state in the report
- 100 patients limits distribution-based validation.
- OMOP mappings are defensible choices, not the only correct answer.
- Docs describe MIMIC v2.x while the OMOP-aligned data is v1.0 (used deliberately as a test case).
- NHANES limited to one cycle to avoid cross-cycle naming changes.
