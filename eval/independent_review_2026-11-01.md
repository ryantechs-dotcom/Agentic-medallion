# Independent review of the P1 draft eval set (`eval/questions_draft.csv`, 122 rows)

Reviewer: Claude (independent pass, 2026-11-01). These are recommendations only. Ryan decides what to keep.
Nothing under eval/, data/, src/, scripts/ or docs/ was modified.

**How I checked**
- I re-ran every `verify_sql` read-only through `medrag.db.connect()` (script `runsql.py` in this
  scratchpad). All 107 queries ran, and each result matched what review_draft.md shows.
- I opened the cited docs directly: NHANES codebook blocks parsed with `nhvar.py`, plus the MIMIC
  `.md` files and the OMOP CSVs.
- I grepped the stripped-text corpus for synonyms of every unanswerable question (`grepc.py`).
- I compared all 1,232 NHANES codebook code/missing counts with the loaded data (`cbcheck.py`).
  Every one matched, except for the known zero artifact and the string-typed RXQ_RX columns.
- All 72 hand-written rows were checked one by one: 3 lookups, 29 multihop, 20 conflict and
  20 unanswerable. The handwritten CSV has 72 data rows, not 70.
- For the 50 generated lookups, I checked doc text and SQL for all 32 NHANES rows, all 10 MIMIC
  rows and all 10 OMOP rows. That is 52 lookups in total, counting the 3 hand-written ones.

---

## 1. Summary

**Verdict:** the set is a solid base. Almost every gold answer agrees with the cited doc text, and
every verify_sql returns what the answer says. I found **2 high-severity problems** (one gold is
wrong, and one "unanswerable" question is answered in the corpus). The bigger risks are at the set
level:
- the qtype labels are loose;
- many gold answers can only be produced with SQL or general knowledge, not with the docs;
- near-duplicate questions are split across dev and test;
- the templated lookups can be guessed without the docs, which inflates the closed-book baseline.

**Proposed disposition: keep 79, edit 36, drop 7.** Rows that only need a split regrouping count
as keep; see section 3.

**Top 5 issues**
1. **MI-024: the gold answer is wrong.** In v1.0 a prescription *can* be linked to POE orders.
   `prescriptions.pharmacy_id -> pharmacy.poe_id -> poe` reaches a poe row for 17,950 of 18,154
   v1.0 prescriptions. Only the direct `prescriptions.poe_id` column is missing.
2. **MI-035 is not unanswerable.** `mimic/about__schema-overview.md` ("Note module") names the
   `radiology` table in the Note module ("De-identified free-text clinical notes").
3. **Many qtype labels don't match the plan's definitions.**
   - Multihop rows that one "Links to" chunk answers: MI-012, MI-013, MI-014, MI-017, NH-035.
   - Conflict rows where the docs are *right* and only a naive SQL query is wrong: NH-041, NH-042,
     NH-043.
   - Conflict rows where the docs are silent or contradict themselves: MI-021, MI-022.
   - Per-qtype metrics, the core of the conflict claim, will be hard to defend unless these are
     relabelled or given a subtype.
4. **Many gold answers can't be produced from the corpus.**
   - The corpus has no MIMIC-to-OMOP mapping docs: no "omop" or "ohdsi" in any MIMIC doc, no
     "mimic" in either OMOP CSV, and none of 8507, 8532, 8527, 8516, 38003563, 3016723 or 2160-0
     appears anywhere in data/docs.
   - So the ETL-specific parts of the cross questions, and every demo count inside a gold answer,
     can only come from SQL (condition 4) or prior knowledge. Conditions 1-3 fail these by
     construction unless they are tagged and reported separately.
5. **Near-duplicates leak across the split, and the test set is thin.**
   - Leaking pairs, dev then test: NH-028 vs NH-034; CR-017 vs MI-011 and CR-002; CR-007/MI-023 vs
     CR-015/MI-016; NH-040 vs NH-044; MI-019 vs MI-020; MI-018 vs MI-012.
   - Several test cells hold a single question: cross-conflict and OMOP-unanswerable each have 1,
     and OMOP has 5 test questions in total.
   - Regroup the clusters before freezing the split. This is still allowed, since no results exist.

---

## 2. Flagged questions

Severity: **high** = the gold is wrong, or an "unanswerable" question is actually answered;
**medium** = ambiguous, mislabelled, weak, or leaks across the split; **low** = wording or notes.

### 2a. High

| qid | sev | problem | evidence | recommended action |
|---|---|---|---|---|
| MI-024 | high | Gold says "No" to "can v1.0 prescriptions be linked to provider orders using poe_id". v1.0 `pharmacy` has `poe_id`, so prescriptions reach POE through pharmacy. Only the direct column is missing. | `information_schema.columns`: `poe_id` exists in mimic_demo_v1_0_hosp.{emar, pharmacy, poe, poe_detail}, not prescriptions. `prescriptions JOIN pharmacy USING (pharmacy_id) JOIN poe ON poe.poe_id = pharmacy.poe_id` gives **17,950** of 18,154 rows. Doc hosp__prescriptions.md "`poe_id`, `poe_seq`: These columns allow linking prescriptions to associated orders in the poe table". | **Edit gold:** "Not directly: v1.0 prescriptions has no poe_id/poe_seq (documented for v2.x). Link via pharmacy_id -> pharmacy.poe_id -> poe (17,950 of 18,154 rows in the demo)." Add the join count to verify_sql. |
| MI-035 | high | The "unanswerable" question is answered in the corpus. | mimic/about__schema-overview.md, "### Note module": "Purpose: De-identified free-text clinical notes - Key tables: `discharge`, `radiology`". check_terms ("radiology report", "report text") missed it. | **Edit:** relabel as lookup (gold: the `radiology` table of the MIMIC-IV Note module) or conflict (documented, but neither demo snapshot has it), or drop. Replace it with a truly absent item; the ED/CXR/ECG modules are also named there, so avoid those. |

### 2b. Medium

| qid | sev | problem | evidence | recommended action |
|---|---|---|---|---|
| MI-023 | medium | The count (0) is right, but the rationale contradicts the v1.0 changelog. The corpus says v1.0 `dod` *should* hold in-hospital deaths, and the docs disagree with each other about out-of-hospital dod. | about__changelog.md "MIMIC-IV v1.0 > patients": "`dod` is now populated using the patient's `deathtime` from their latest hospitalization... out-of-hospital mortality is **not** captured". about__whatsnew.md: "DOD no longer available outside of the hospital". hosp__patients.md: out-of-hospital deaths up to one year. Data: v1.0 dod has 0 non-null of 100 (also 0 in raw `core/patients.csv.gz`, so this is not an ingestion bug); v2.2 has 31; the 15 v1.0 deathtime patients all have v2.2 dod. | **Edit gold/notes:** "0. Even the v1.0 changelog says dod = deathtime of the latest hospitalization (which would give 15), but the demo v1.0 dod column is empty; use admissions.deathtime (15)." This makes it a stronger conflict. |
| CR-006 | medium | Gold is incomplete and verify_sql doesn't test it. Only about 3.8k of condition_occurrence's 16,441 rows come from diagnoses_icd (4,506 rows), and some diagnoses go to OBSERVATION. | `condition_type_concept_id`: 32821 = 3,833 rows, 32817 = 12,608. Approximate trace (person + trimmed code match, ignoring icd_version): about 3,640 diagnoses_icd rows found in condition_occurrence and about 851 in observation. Current verify_sql is only `COUNT(*)` = 16441. | **Edit:** gold "Mostly CONDITION_OCCURRENCE (condition_source_value = ICD code, padded); some codes land in OBSERVATION per domain mapping". Allow an acceptable alternative (OMOP truth is one ETL's choice). Replace verify_sql with the trimmed-code join. |
| MI-021 | medium | Weak conflict: the corpus doc contradicts itself. Its column table says `race`, but the only descriptive heading is `### insurance, language, marital_status, ethnicity`, and there is no `race` section. A docs-only system can say "ethnicity" and be right for the wrong reason. gold_section "race" is not a section. | hosp__admissions.md, the "Table columns" list vs the "Detailed description" heading. `grep -n "\brace\b"` hits only line 38 (the column list). | **Edit notes:** record the doc inconsistency, set gold_section to "Table columns" plus that heading, and keep it as a version conflict. Same split as MI-022. |
| MI-022 | medium | The docs say nothing about category sets (no race/ethnicity value list), so this is data-only, not docs-misleading. It overlaps MI-021 and CR-012. | Data: v1.0 ethnicity has 6 distinct values; v2.2 race has 14 (e.g. 'HISPANIC/LATINO - CUBAN' 9 rows). Corpus: only "Values changed for many columns (e.g. language, ethnicity)" in about__whatsnew.md, which describes the MIMIC-III to IV change. | **Edit:** tag `needs_data`, or merge into MI-021. |
| MI-019 | medium | The premise "data the OMOP ETL was built on" can't be resolved from the corpus (no doc links OMOP to v1.0). It is also a near-duplicate of MI-020 (same changelog line), with MI-019 in dev and MI-020 in test. | Corpus grep: no "omop/ohdsi" in mimic docs, no "mimic" in omop docs. about__changelog.md v2.0: "The core module has been removed... admissions, patients, transfers are now in hosp". | **Edit:** reword to "In MIMIC-IV v1.0, which module..." or drop one of MI-019/MI-020. Same applies to the wording of MI-025 and MI-030. |
| MI-025 | medium | "Nowhere in v1.0" is too strong. Inpatient height and weight exist in v1.0 ICU chartevents; only an *outpatient* source (omr) is missing. | v1.0 chartevents: 224639 Daily Weight 441 rows, 226512 Admission Weight (Kg) 129, 226730 Height (cm) 71. hosp__omr.md: "outpatient measurements such as blood pressure, weight, height, and body mass index". | **Edit gold:** "No outpatient source in v1.0 (omr is v2.x only); only ICU-charted inpatient weight/height in chartevents." |
| MI-012, MI-013, MI-014, MI-017 | medium | Labelled multihop, but one "Links to" line in a single doc answers each. | hosp__d_icd_diagnoses.md / hosp__diagnoses_icd.md: "Links to ... ON `icd_code` and `icd_version`". icu__chartevents.md: "d_items on `itemid`". icu__icustays.md: "admissions on `hadm_id`". hosp__prescriptions.md: "*pharmacy* on `pharmacy_id`". SQL results all as stated (4506/4594, 667703/667703, 140/140, 18154/18087). | **Edit:** relabel as lookup. If you want real multihop, require a second hop (e.g. "label of the most frequent chartevents itemid"). |
| NH-035 | medium | Labelled multihop, but one chunk answers it. verify_sql (`COUNT(*)` = 3036) doesn't test the claim. | GLU_J component description: "Specific sample weights (WTSAF2YR) for this subsample are included in this data file and should be used". | **Edit:** relabel as lookup, and drop verify_sql or make it check that WTSAF2YR exists in glu_j. |
| MI-016 | medium | Near-duplicate of MI-007 (hospital_expire_flag; both test). The "15" also leaks from dev CR-007 and MI-023. Not really multihop. | hosp__admissions.md `hospital_expire_flag`. SQL (15, 15). | **Drop**, or merge the count into a `needs_data` variant of MI-007. |
| NH-028 / NH-034 | medium | The same SMQ020 skip rule is tested twice (NH-028 dev lookup, NH-034 test multihop). NH-034 is also really one chunk (the SMQ020 skip column). | SMQ_J SMQ020: 2 No / 7 Refused / 9 Don't know -> SMQ890. SQL: SMQ040 non-null only for SMQ020 = 1 (2,359). | **Drop NH-028** (keep the hand-written NH-034), or put both in the same split. |
| NH-041, NH-043 (and NH-042) | medium | Conflict in the wrong direction: the codebook gives the right answer (6,183 / 550 / 178) and only a naive `= 0` SQL fails. That tests the verification condition's robustness, not "docs alone are misleading". It depends on D10, which is still PROPOSED: a v2 snapshot fix would invalidate the gold. Three of the 5 NHANES conflicts share this one artifact. NH-042 duplicates NH-036 (both 550 WTMEC2YR = 0). | SQL: (0, 6183), (0, 550), (0, 178). docs/DECISIONS.md D10 "PROPOSED (Ryan to confirm)". Artifact present in 27 of 303 DOUBLE NHANES columns (incl. RIDAGEYR = 0 for 357 infants, BPXDI1-4). The gold calls it a "SAS transport-file artifact"; ingestion uses `pd.read_sas(format="xport")`, so it is more precisely a reader-conversion artifact (I did not verify the exact mechanism). | **Edit:** keep one (NH-041) with a conflict subtype such as "data-as-loaded". **Drop NH-042.** Keep NH-043 only if you want 2. Freeze D10 first. |
| NH-045 | medium | Weak and leaky: the question names MCQ160a, so the answer (MCQ160A) is a case change. It holds for every lowercase-letter codebook variable. | SQL returns 'MCQ160A'. NH-001's own verify_sql (`"MCQ230b"`) works because DuckDB is case-insensitive. | **Drop**, or keep as low weight. |
| NH-040 / NH-044 | medium | NH-040's gold (dev) explains that DIQ159 is a CHECK ITEM, which answers NH-044 (test). | DIQ_J DIQ159 block: "BOX 4. CHECK ITEM DIQ.159: IF AGE <12 OR DIQ.010 = 1 ... GO TO DIQ.050. IF AGE >=12 AND DIQ.010 = 3, GO TO DIQ.170". SQL (0,) for the DIQ159 column. Both golds are correct. | Keep both, **same split**. |
| CR-017 / MI-011 / CR-002 | medium | CR-017's gold (dev) states both the anchor_age = 91 rule (MI-011, test) and the year_of_birth = anchor_year - anchor_age formula (CR-002, test). | hosp__patients.md `anchor_age`: "set to 91". SQL: (3, 91); (100, 100); (3,). All golds are correct. | Keep all, **same split**. |
| CR-007 / CR-015 | medium | CR-007 (dev) gives "DEATH; 15 deaths", which leaks the count in CR-015 (test). The count isn't in any doc. | SQL (15,). The OMOP death table matches v1.0 deathtime dates for 15 of 15 rows. | Same split. Tag the count part `needs_data`, or drop it from the gold. |
| CR-005 | medium | Data-only: neither 3016723 nor 2160-0 is in data/docs. The "LOINC 2160-0 creatinine concept" naming can't be checked inside the project, because `2b_concept` has only 3,885 custom concepts and the standard concept is absent. | SQL (3016723,). `2b_concept` lookup for 3016723 returns no rows. v1.0 d_labitems loinc_code for 50912 = '2160-0' (MI-029 SQL). | **Edit:** tag `needs_data`. Put the LOINC naming in notes, citing the d_labitems value rather than general knowledge. |
| CR-008 | medium | The gold includes counts (18,229 vs 18,154) that no doc contains, and the counts differ without explanation. | SQL (18154, 18229). | **Edit:** gold = "DRUG_EXPOSURE"; move the counts to notes. |
| NH-002, NH-003, NH-007, NH-008, NH-010 | medium | 5 of the 10 generated code-meaning lookups have answer "Yes" or "No" (1 = Yes, 2 = No is NHANES-wide). Closed-book will score near 100%, so they don't separate RAG from non-RAG. NH-010 and NH-016 both use DIQ070. | Codebook blocks: MIAINTRP 1 = Yes; MCQ160g 1 = Yes; BPQ040A 2 = No; BPAEN4 2 = No; DIQ070 2 = No. Counts match (146, 106, 192, 427, 955). | **Edit:** resample to codes with non-generic labels (like NH-001 Breast, NH-006 Camel, NH-009). Change the generator filter to exclude Yes/No. |
| NH-012, NH-013, NH-015, NH-016 | medium | Seven special-code lookups (NH-011 to NH-017) share a near-identical template answer that is guessable from NHANES convention. Five are in test, so test NHANES lookups are dominated by one easy template. | All codebook values and counts verified (5, 2, 40, 22, 6, 2, 3). | Keep NH-011 (777/999), NH-012 (7/9), NH-014 (77/99) and NH-017 (7777/9999). **Drop NH-016** (DIQ070 duplicate). **Convert NH-013 and NH-015** into data-anchored versions (e.g. "how many valid numeric responses"). |
| NH-023, NH-024, NH-025 | medium | "Which participants were eligible to be asked" has two defensible answers. Gold gives only the codebook *Target* age range, but skip logic restricts much further. MCQ230b is asked only of people with 2+ cancers, and DIQ175Q only of people who think they are at risk. | Codebook Target lines: MCQ230b 20-150; DIQ175Q 12-150; SMQ848 18-150. Observed ages: 32-80, 12-80, 18-80. | **Edit wording:** "What target age range does the codebook list for X?" |
| NH-046 | medium | The out-of-corpus question has a retrievable and probably still-correct answer. DMDEDUC2 is in the 2017-2018 DEMO_J doc, and I believe the 2021-2023 name is the same (general knowledge, not verified in the corpus). Scoring "DMDEDUC2" as a hallucination would be unfair. | Corpus: "DMDEDUC2 - Education level - Adults 20+" in DEMO_J. No "2021-2023" anywhere. | **Edit:** define correct behaviour as "corpus covers 2017-2018 only (DMDEDUC2 there); can't confirm for 2021-2023". Or replace it with a variable whose name is known to change. |
| NH-052 | medium | The question states the meaning ("vigorous work activity"), and PAQ605 is a real NHANES 2017-2018 variable (PAQ_J), so closed-book can answer correctly. | grep "PAQ|vigorous": 0 hits in the corpus. | **Edit:** remove the parenthetical and define the acceptable answer as "PAQ file not in corpus", or drop. |
| MI-003 | medium | Circular and trivially guessable ("label describes the concept represented by itemid"). | hosp__d_labitems.md `label`. | **Drop** and resample. |
| OM-010 | medium | Duplicate of OM-008 (person_id -> PERSON), both dev. All the FK lookups can be guessed from the column names. | OMOP_CDMv5.3_Field_Level.csv: condition_occurrence.person_id and measurement.person_id both FK PERSON.PERSON_ID. | **Drop OM-010.** |
| MI-018 / MI-012 | medium | MI-018's gold (dev) says icd_version distinguishes the coding systems, the key fact in MI-012 (test). | SQL (9, 2193); (10, 2313). | Same split. |
| NH-021 | medium (answer) | Gold "Frequent urination" is a label, not what the variable records. DIQ175T is a code-all-that-apply reason for "why do you think you are at risk for diabetes" (code 29). | DIQ_J DIQ175T block (English Text plus code 29, 116 rows). | **Edit gold:** "Whether the respondent cited frequent urination as a reason they think they are at risk for diabetes/prediabetes (code 29)." |

### 2c. Low

| qid | sev | problem | evidence | recommended action |
|---|---|---|---|---|
| CR-015 | low | Gold is correct, but the deciding evidence is the ETL code, which is not in the corpus. | data/raw/github/omop_etl/MIMIC-main/etl/etl/cdm_death.sql builds lk_death_adm_mapped from `src_admissions WHERE deathtime IS NOT NULL`. OMOP death dates match v1.0 deathtime for 15 of 15 rows; type concept 32817 for all 15. | Keep. Cite the ETL file in notes and tag `needs_data`. |
| CR-016 | low | Good conflict, but it is missing the strongest doc evidence. | about__changelog.md v1.0: "icd_code column is now trimmed... no trailing whitespaces (`850 ` -> `850`)". hosp__d_icd_diagnoses.md types icd_code as CHAR(7). Raw OMOP CSV has the same 3,763 padded values (not an ingestion bug). Untrimmed match = 70 rows, trimmed = 3,833. | Keep. Add the changelog section to gold_doc/notes. |
| CR-010 | low | verify_sql (count 14,479) doesn't test the claim. visit_detail is dominated by one concept (38004207: 13,393 rows), far more than 1,190 transfers or 140 icustays. | SQL as stated. | Keep the spec answer. Note that the demo ETL fills VISIT_DETAIL with more than ICU and ward segments. |
| CR-001, CR-011 | low | Concept IDs 8507/8532/8527/8516 are general OMOP knowledge, so closed-book can answer. | Not in data/docs (grep). SQL as stated. CR-011 custom IDs verified: OTHER 2000001402, UNABLE TO OBTAIN 2000001405, UNKNOWN 2000001401. | Keep. Tag `guessable` and `needs_data`. |
| CR-012 | low | Correct. Note that non-Hispanic persons get ethnicity_concept_id = 0, although the spec marks the field required and says "Do not attempt to infer Ethnicity from the race". This is an ETL choice; allow alternatives. | SQL: Hispanic (38003563, race 0, 5). All 95 others have ethnicity_concept_id 0. Field-level CSV person.ethnicity_concept_id, isRequired = Yes. | Keep. Possible new OMOP conflict question. |
| MI-004 | low | Doc-correct, but in v1.0 prescriptions has no poe_id, so the "orders in ... prescriptions" link via poe_id doesn't hold there. | See MI-024. | Keep. Add a note. |
| MI-005, MI-006 etc. (MIMIC lookups) | low | Gold answers are verbatim doc sentences (notes say "trim on review"), so scoring needs a rubric. "genotypical sex" vs "sex" will confuse an LLM judge. | Doc sections match the gold text exactly (checked all 10). | Keep. Write a 1-line key fact per gold. |
| NH-030 | low | The target DIQ295 is a CHECK ITEM, not a question. The answer is right per the codebook. | DIQ275: 2 No -> DIQ295. DIQ295: "CHECK ITEM... IF AGE <12, GO TO END OF SECTION". | Keep. Add a note. |
| NH-033 | low | SEQN is general NHANES knowledge. | DEMO_J SEQN. SQL (6724,). | Keep. Tag `guessable`. |
| NH-037, NH-038 | low | verify_sql has no expected value and doesn't test the claim (it only counts joinable rows). | SQL 813; 5601. BPXO_J component description: mercury sphygmomanometer and auscultatory protocol vs oscillometric. | Keep. Drop or relabel the SQL as "context". |
| MI-032, MI-038, OM-011 | low | Scoring ambiguity. MI-032: the docs say providers are deidentified (`admit_provider_id`), so "not available, only deidentified IDs" should count as correct. MI-038: the corpus mentions only BIDMC (icu__index.md, about__whatsnew.md); "none, single-centre" is world-true. OM-011: answerable from world knowledge. | grep results in my run (BIDMC: 2 MIMIC files; "5.4" only as an example cdm_version string). | Keep. Write explicit "acceptable answer" notes. |
| NH-050 | low | A proxy (8,704 examined of 9,254 interviewed) is computable from RIDSTATR, and a model may present it as a "response rate". | DEMO_J RIDSTATR counts. | Keep. Notes: that ratio is not a response rate. |

All other rows: keep. All golds match the docs and SQL as checked. This covers NH-001, 004-006, 009, 011, 012, 014,
017-020, 022, 026, 027, 029, 031, 032, 036, 039, 047-049, 051, 053; MI-001, 002, 006-011, 015, 020,
026-031, 033, 034, 036, 037, 039; OM-001-009, 012, 013; CR-002-004, 009, 013, 014, 017.

**Tally:** high 2 rows. The medium and low tables group some rows together, and the
leakage-only groups need no content change. Disposition: **drop 7** (MI-003, MI-016, NH-028, NH-042, NH-016, NH-045,
OM-010); **edit 36** (MI-035, MI-024, MI-023, MI-021, MI-022, MI-019, MI-025, MI-012, MI-013,
MI-014, MI-017, NH-035, NH-002, NH-003, NH-007, NH-008, NH-010, NH-013, NH-015, NH-021, NH-023,
NH-024, NH-025, NH-041, NH-043, NH-046, NH-052, CR-005, CR-006, CR-008, plus note-only edits on
CR-007, CR-015, CR-016, MI-004, MI-032, MI-038); **keep 79**.

---

## 3. Set-level issues and suggested additions

### 3.1 Schema and scoring
1. **One gold_doc/gold_section per row can't represent multihop evidence.** Recall@k and MRR "against
   gold_doc/gold_section" are undefined for 2-chunk questions. Several gold_sections are free-text
   anchors, not sections: "core module has been removed", "body mass index", "Ingredients",
   "d_items on `itemid`", "admissions on `hadm_id`", and "race", which has no section. Suggest a
   `gold_chunks` list (doc#section;doc#section), mapped to chunk IDs once the chunker exists.
   Also, review_draft.md excerpts for table-level CSV sections take the first string hit. For
   CR-004 the "MEASUREMENT" excerpt is OBSERVATION_PERIOD text, so the review evidence is
   unreliable for those rows.
2. **Separate doc knowledge from data knowledge.** Add a `needs_data` flag, or split gold into
   `gold_doc_part` and `gold_data_part`. Rows affected:
   - every cross row's ETL specifics: CR-001, CR-002, CR-005, CR-007-CR-009, CR-011-CR-013,
     CR-015-CR-017;
   - every count embedded in a gold answer: MI-016, MI-018, MI-023, NH-031, NH-032, CR-007,
     CR-008, CR-013.

   Without the flag, the comparison of conditions 1-3 against condition 4 is confounded by design.
   You should decide whether to put the ETL repo docs (data/raw/github/omop_etl/MIMIC-main
   README.md, usage_notes.md) into the corpus. This is a methodological choice: it would make the
   cross questions doc-answerable and change what "conflict" means.
3. **Conflict subtypes.** The draft mixes four kinds:
   - (a) v2.x docs vs v1.0 data (MI-019, MI-020, MI-024 to MI-030), the intended case;
   - (b) docs correct, data-as-loaded wrong (NH-041 to NH-043);
   - (c) docs that contradict each other (MI-021, MI-023);
   - (d) data-only facts (MI-022, CR-016).

   Add a `conflict_kind` column so the headline "conflicts are where condition 4 differs" result
   can be broken down.
4. **Unanswerable taxonomy and rubric.** False-premise questions are different from out-of-scope
   ones:
   - **False premise** (MI-031, MI-036, MI-037, NH-051, OM-012, MI-039): the corpus *does*
     support "no such column", because the column lists are complete.
   - **Out of scope, world-knowable** (NH-046, NH-052, OM-011, MI-038): the answer is outside the
     corpus but may be known from general knowledge.

   Decide before running whether a correct world-knowledge answer counts as a hallucination.
5. **Guessability.** About 25 rows are answerable closed-book from naming conventions:
   - the 5 Yes/No code lookups and 7 special-code templates;
   - all 10 OMOP lookups (5 are Yes/No "required", FK targets are named in the column);
   - SEQN, anchor_age 91, RIDAGEYR 80, and the OMOP gender/race concept IDs.

   Tag them `guessable`, so the closed-book baseline isn't misread as "RAG doesn't help".
6. The NHANES zero artifact (D10) is still **PROPOSED**. Freeze it before freezing gold answers,
   because NH-036, NH-041, NH-042 and NH-043 depend on it.

### 3.2 Split
- The current split is stratified by qtype x source only. Before freezing, regroup these
  near-duplicate or leaking clusters so each sits in one split:
  - {NH-028, NH-034}
  - {CR-017, MI-011, CR-002}
  - {CR-007, MI-023, CR-015, MI-016, MI-007}
  - {NH-040, NH-044}
  - {MI-019, MI-020}
  - {MI-018, MI-012}
  - {MI-021, MI-022, CR-012}
  - {CR-004, CR-005, CR-014, MI-029}: all creatinine 50912, a milder case
- Also stratify by generator template. Test NHANES lookups are 5 of 13 special-code rows, while
  dev has 2 of 19.
- Thin test cells: cross-conflict 1, OMOP-unanswerable 1, OMOP total 5, cross total 7.
  Per-source x qtype test metrics will be very noisy. Report pooled results with CIs, or grow
  these cells.

### 3.3 Coverage gaps
- **OMOP (13 rows):** there are no OMOP-only multihop or conflict rows, no table-level questions,
  and no questions on the etlConventions text. Every OMOP lookup comes from two templates.
- **MIMIC ICU: 0 lookups.** The generator regex `^### \`col\`` misses the ICU docs, which use
  `## \`col\`` headings (e.g. icu__inputevents.md has 13 such headings and 1 `###`). All 10
  MIMIC lookups are hosp.
- **NHANES files with no question:** HDL_J, TCHOL_J, RXQ_RX_J. BMX_J appears only in NH-039.
- **Cross** has no lookup or unanswerable rows.
- **Corpus caveat:** many MIMIC docs contain unresolved Jekyll `{% include ... %}` stubs, so
  definitions such as subject_id, provider_id and caregiver_id are missing from the corpus. I
  counted these stubs in 30 files.

### 3.4 Suggested additions
Numbers are given only where I verified them.
- **NHANES RXQ_RX special codes stored as strings.** RXDDRUG has 55555 = Unknown (13), 77777 =
  Refused (30) and 99999 = Don't know (91). Missing values are stored as the empty string `''`
  (5,209 rows), not NULL, so `COUNT(RXDDRUG)` = 19,643, while the codebook shows 14,300 recorded
  values. This gives a real data-as-loaded conflict plus a special-code lookup that is not 7/9,
  and covers a new file. (Verified in the codebook and with SQL.)
- **NHANES 5-digit and odd special codes:**
  - MCQ025 (age first had asthma): 77777 = Refused, 99999 = Don't know (21); 80 = "80 years or
    older" top-code.
  - DID320: 5555 = Never heard of LDL (24), 6666 = Never had cholesterol test (31) inside a
    continuous LDL field.
  - DIQ280: 777 / 999 (2 / 255) inside an A1C range of 2.3-14.

  All verified in the codebook. Each could ask "what is the mean of X" so that treating special
  codes as values gives a visibly wrong answer. I did not compute those means.
- **MIMIC ICU lookups from the ICU docs:**
  - icu__chartevents.md: "In cases where there is disagreement between measurements, *labevents*
    should be taken as the ground truth".
  - icu__icustays.md: icustays is derived from transfers and excludes non-ICU wards; stays
    without a heart-rate measurement (~5%) are dropped.
- **MIMIC dod three-way doc inconsistency.** Fold it into MI-023, or write a second conflict
  (see the MI-023 row).
- **OMOP etlConventions lookups:**
  - year_of_birth: "If no year of birth is available all the person's data should be dropped from
    the CDM instance" (field-level CSV, as quoted in the CR-002 review excerpt).
  - ethnicity_concept_id: "Do not attempt to infer Ethnicity from the race or ethnic background".
  - person_source_value: "not required but strongly recommended".
- **OMOP ETL-choice conflicts or checks:**
  - condition_occurrence.visit_detail_id is NULL in all 16,441 rows (OM-003 SQL).
  - visit_detail_parent_id is NULL in all 14,479 rows (OM-004 SQL).
  - The COST table is in the spec, but the demo `cost` table has 0 rows.
  - Non-Hispanic persons get ethnicity_concept_id 0 although the field is required.

  Mark these as "acceptable alternative" judgments, since OMOP ground truth is one ETL team's
  choice.
- **Cross unanswerable:** for example, a mapping for a MIMIC itemid that does not occur in the
  demo. Verify with SQL before adding.

---

Scratch scripts used, all in this scratchpad folder: `runsql.py` (all verify_sql), `nhvar.py`
(codebook blocks), `grepc.py` (corpus grep), `cbcheck.py` (codebook vs data counts).
