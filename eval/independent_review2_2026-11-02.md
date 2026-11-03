# Review 2 of new/reworded rows in eval/questions_draft.csv (2026-11-02)

Scope: 67 rows (46 generated lookups + 21 hand-written). Recommend-only; no project file was edited.

How I checked:
- I ran every `verify_sql` read-only through `medrag.db.connect()` (scratch script `runsql.py` in
  this folder). All of them ran without errors.
- For NHANES I parsed the `div.pagebreak` block of every cited variable (`nh.py` in this folder)
  and compared the code tables, counts, targets and skip-to items.
- For OMOP I read the cited rows of the Field_Level and Table_Level CSVs.
- For MIMIC I read each cited section with awk/grep, then ran extra SQL where a claim went
  beyond the cited SQL.

## 1. Summary

**Verdict:** the set is in good shape. Every generated NHANES value, label, target and skip
gold matches its codebook block. Every NHANES count in the notes matches the data. Every OMOP
required/FK gold matches the spec CSV. Before freezing, fix one wrong clause (MI-029), close
three dev->test leaks (MI-022/MI-014, OM-013/CR-010, NH-020/NH-022) and correct a batch of
`guessable` tags on the generated MIMIC lookups.

| | count |
|---|---|
| keep as is | 39 |
| edit | 28 (1 high, 15 medium, 12 low) |
| drop | 0 (NH-017 is a "consider dropping", low) |

## 2. Flagged rows

| qid | severity | problem | evidence | recommended change |
|---|---|---|---|---|
| MI-029 | **high** (one clause wrong) | The gold says "v1.0 only has ICU-charted inpatient weight/height in chartevents". That is false: v1.0 `icu.inputevents.patientweight` has 20,404 non-null values, and chartevents also has Admission Weight (lbs.). The key evidence (the changelog saying omr was added in v2.0) is not cited. | SQL: `SELECT COUNT(patientweight) FROM mimic_demo_v1_0_icu.inputevents` -> 20404. chartevents labels in v1.0: 224639 Daily Weight 441, 226531 Admission Weight (lbs.) 236, 226512 Admission Weight (Kg) 129, 226730 Height (cm) 71, 226707 Height 71. `about__changelog.md` l.86-87: "_omr_ ... A new table has been added" under v2.0. `omr` exists only in `mimic_demo_v2_2_hosp`. | gold_answer: "Nowhere: the docs point to the omr table, but omr was added in v2.0 (only the v2.2 demo has it), so v1.0 has no outpatient height/weight/BMI; it only has inpatient ICU values (e.g. chartevents weight/height items, inputevents.patientweight)". gold_evidence: `mimic/about__changelog.md#omr`. Update notes with the counts above. |
| MI-022 | medium | Dev->test leak. The second half of the dev gold ("name comes from icu d_items.label joined on itemid") is exactly the gold of MI-014 (test: "How do you get the name of a charted ICU measurement in MIMIC-IV chartevents?" -> "Join chartevents.itemid to d_items.itemid ... read d_items.label"). The data part is correct. | SQL -> (227969, 'Safety Measures', 19330); runner-up Respiratory Rate / Heart Rate 13913. No chartevents itemid is missing from d_items (0). | Either (a) set cluster `d_items` on MI-022 and MI-014 and move MI-022 to test (allowed only because no results exist yet), or (b) keep MI-022 in dev and drop the second clause. For (b): question "Which item is charted most often in MIMIC-IV v1.0 chartevents?", gold "Safety Measures (itemid 227969, 19,330 rows)", and qtype stays multihop (it needs d_items for the name). |
| OM-013 | medium | Dev->test leak with CR-010 (test: "Which OMOP CDM table should hold MIMIC-IV ICU stays and ward transfers..." -> VISIT_DETAIL). OM-013 (dev) asks for the table that holds "finer-grained segments of a hospital visit (such as an ICU stay)" -> VISIT_DETAIL. The multihop label is also weak: Table_Level VISIT_DETAIL userGuidance already says "The Visit Detail record will have the VISIT_OCCURRENCE_ID it is associated to". Only "required" needs the Field_Level row. | Table_Level.csv row `visit_detail` (tableDescription + userGuidance). Field_Level `visit_detail.visit_occurrence_id` isRequired=Yes, FK VISIT_OCCURRENCE. SQL: (14479, 14479). | Put OM-013 and CR-010 in one cluster (`visit_detail`) and the same split, or reword OM-013 so it does not give away the table: "In OMOP CDM v5.3, which VISIT_DETAIL field links a visit-detail record to its parent visit, and is it required?" with gold "visit_detail.visit_occurrence_id; required (FK to VISIT_OCCURRENCE)" and qtype lookup. |
| NH-020 / NH-022 | medium | Near-duplicates across splits. DIQ175A (test) and DIQ175K (dev) are two check boxes of the same question ("Why do you think you are at risk for diabetes?") and have the same gold, "Both males and females 12 YEARS - 150 YEARS". | Both codebook blocks: Target "Both males and females 12 YEARS - 150 YEARS", same English Text. | Set a shared cluster (e.g. `diq175`) and the same split, or replace one of them with a target-group question from another file (e.g. one whose target is not 12-150). |
| OM-014 | medium | "all 95 non-Hispanic persons" is inexact. 16 of the 95 have MIMIC ethnicity UNKNOWN (13) or UNABLE TO OBTAIN (3), so they are not known non-Hispanic. The question premise ("non-Hispanic patients") has the same problem. The notes say "MIMIC has no separate ethnicity field", but the v1.0 column is literally named `ethnicity` (it mixes race and Hispanic origin). | SQL join of person to v1.0 admissions: WHITE 63, BLACK 10, OTHER 6, UNKNOWN 13, UNABLE TO OBTAIN 3 -> ethnicity_concept_id 0; HISPANIC/LATINO 5 -> 38003563. No row uses any other ethnicity concept (verify_sql: only 0 and 38003563). | question: "The OMOP CDM v5.3 spec marks person.ethnicity_concept_id as required. How does the MIMIC OMOP demo fill it for patients not recorded as HISPANIC/LATINO?" gold: "With 0 (no matching concept) for all 95 of them, including the 16 UNKNOWN/UNABLE TO OBTAIN; no 'Not Hispanic' concept is used. Only the 5 HISPANIC/LATINO persons get 38003563". notes: "MIMIC v1.0 has a single `ethnicity` column that mixes race and Hispanic origin". |
| MI-035 | medium | needs_data should be `yes`. "Neither demo snapshot includes the Note module" comes only from the data. The corpus names the Note tables but never says what the demo contains (grep for "demo" in the mimic docs finds no statement about module coverage). | `about__schema-overview.md` l.69-71 names `discharge`, `radiology`. verify_sql -> 0 tables. | needs_data: yes. |
| NH-041 | medium | Ambiguous: NHANES means are normally survey-weighted, but the gold is the unweighted mean, so a weighted answer would be marked wrong. A minor convention point: qtype is multihop with one doc chunk plus data (the same convention as CR-007). | Codebook DIQ280: 2.3 to 14 = 490, 777 = 2, 999 = 255. SQL -> (490, 7.19, 347.82); the 777/999 count is 257. | question: "What is the unweighted mean self-reported last A1C level (DIQ280) among NHANES 2017-2018 respondents who gave a value?" Leave the gold as is. |
| MI-021 | medium | "how many are there" could mean ICU stays (20), admissions (15) or patients (15). | SQL: 20 stays with hospital_expire_flag = 1, 20 with deathtime not null, 15 distinct hadm_id, 15 distinct subject_id. | gold: "...; 20 ICU stays (15 admissions / 15 patients)". Or reword the question to "how many ICU stays are there". |
| MI-001, MI-002, MI-003, MI-005, MI-008, MI-009, MI-011 | medium (tag) | `guessable` should be `yes`: a closed-book model can answer from the column name, which skews the closed-book baseline. MI-001, MI-002 and MI-003 are also circular ("long_title provides the meaning", "whether from an open bag", "source of dispensation"). | Doc sections, read verbatim: d_icd_diagnoses `long_title`, procedureevents `isopenbag`, pharmacy `dispensation`, prescriptions `doses_per_24_hrs`, emar `scheduletime`, inputevents `patientweight`, chartevents `valueuom`. | guessable: yes for all seven. Optional gold trims: MI-001 "Human-readable description of the ICD code (e.g. ICD-9 0010 = 'Cholera due to vibrio cholerae')". MI-005 "Doses per 24 h (daily = 1, BID = 2)". |
| MI-004 | low | Gold is long and verbatim. | `icu__d_items.md#unitname` | gold: "Unit of measurement for the itemid; often missing (units vary, don't apply, or weren't recorded)". Consider guessable: yes. |
| MI-007 | low | Gold is verbatim. The key fact is fine and not guessable. | `hosp__labevents.md#charttime` | gold: "Time the lab was charted, usually the specimen acquisition time, which is much earlier than when the result was available". |
| MI-017 | low | Two-option question, and "labs are ground truth" is a plausible prior. | `icu__chartevents.md` l.33 | Consider guessable: yes (the gold is correct). |
| MI-023 | low | Overlaps heavily with MI-024 (same cluster, both test, so no leak). Docs-only can also answer it: the changelog says core was removed in v2.0 and patients moved to hosp. | `about__changelog.md` l.55. SQL -> v1_0_core and v2_2_hosp. | Fine to keep. Optionally drop one of MI-023/MI-024 to avoid double-weighting one fact. Notes: replace "docs-only answer (hosp) is wrong" with "naive docs answer (hosp) is wrong; the changelog gives v1.0 = core". |
| OM-003 / OM-015 | low | Related pair across splits (condition_occurrence.visit_detail_id). The dev row gives the FK, the test row the data fact; the answers do not leak. | Field_Level row (FK VISIT_DETAIL, isRequired No). SQL -> (0, 16441, 16441). | Optional shared cluster. |
| OM-016 | low | "(MIMIC-IV has no cost data)" is not supported by a cited doc and is close to the answer of MI-039 (test, out_of_scope ICU-day cost). | Table_Level COST isRequired=No. SQL -> 0. | gold: "No: the cost table exists but has 0 rows (COST is an optional table)". |
| NH-017 | low | The answer appears verbatim in NH-005's question text ("DID330 (What does Dr say LDL should be)"). Both rows are dev, so this is not a leak, just redundant. | DIQ_J DID330 SAS Label. | Consider dropping NH-017 or swapping in a different variable. |
| NH-032 | low | guessable=no, while the sibling special-code rows NH-011 to NH-014 are guessable=yes. 77777/99999 follow the convention; 55555 = Unknown does not. | RXDDRUG block: 55555 Unknown 13, 77777 Refused 30, 99999 Don't know 91. SQL matches. | Leave guessable=no but add a note ("55555 not guessable"), or set yes for consistency. |
| NH-045 | low | needs_data=no although part of the gold (stored as '' not NULL) is data-only. This matches the set convention for data_as_loaded (NH-042 and NH-043 are also no). The key answer (14,300) is in the codebook. | Codebook: recorded 14300, 55555/77777/99999 = 13/30/91, blank 5209. SQL -> (19643, 14434, 14300); no NULLs. | Keep. Add to notes: "key fact = 14,300 (docs); the ''-storage remark is explanatory, not scored". |
| NH-013 | low | DID320 also has 5555 (Never heard of LDL) and 6666 (Never had cholesterol test). The gold is correct for the codes asked about. | DID320 block; SQL 684 = 12 + 672. | notes: "5555/6666 are also non-values; accept if mentioned". |
| NH-014 | low | DID040 also has 666 = Less than 1 year (not a 777/999 code, but also not a literal age). | DID040 block; SQL 10 = 0 + 10. | notes: "666 = <1 year is also a special code". |

Wording note (NH-011 to NH-014, no change required): "should they be analyzed as numbers?" hints
at the answer. That is acceptable because the rows are tagged guessable=yes.

## 3. Rows checked with no issues

- **MIMIC:** MI-006, MI-010, MI-018, MI-044.
  - MI-018: the SQL is context only (140 stays / 1,190 transfers), which is fine.
  - MI-044: no "allerg" string in data/docs/mimic. The only hits in the corpus are NHANES RXQ
    ICD-10 reason labels.
- **NHANES:** NH-001, NH-002, NH-003, NH-005, NH-006, NH-007, NH-008, NH-009, NH-010, NH-011,
  NH-012, NH-015, NH-016, NH-018, NH-019, NH-021, NH-023, NH-024, NH-025, NH-026, NH-027, NH-033,
  NH-034, NH-052.
  - Every SQL count equals the codebook count.
  - The skip-to items match the codebook, and the skipped items are empty in the data.
  - NH-027: BPQ070 is non-missing for people with BPQ060 missing because BPQ080 = 1 routes them
    past BPQ060. The gold is still right.
  - NH-052: no "PAQ" string in the corpus; guessable=yes matches the convention of the other
    out_of_scope rows.
- **OMOP:** OM-001, OM-002, OM-004, OM-005, OM-006, OM-007, OM-008, OM-009, OM-010, OM-011,
  OM-012. Each gold matches isRequired / fkTableName / etlConventions in the Field_Level CSV.
