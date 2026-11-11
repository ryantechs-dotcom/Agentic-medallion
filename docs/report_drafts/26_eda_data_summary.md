<!-- Tracker task 26 (Jack). Draft for the EDA section of the shared report.
     Every number below comes from results/2026-11-10_p3_profile/ (column_profile.csv,
     tables/*.csv, config.json: git 980202f, snapshot v1) or corpus/corpus_v1.manifest.json.
     Regenerate with: python scripts/profile_tables.py --overwrite, then run
     notebooks/tabular_eda.ipynb. Text-statistics results are Nikhil's (task 10). -->

# Data summary

## Sources

The project uses one deliberately messy source of record (MIMIC-IV), the same patients after an
expert ETL into a standard model (OMOP), and a documentation-heavy survey (NHANES). All data is a
frozen snapshot (v1); nothing in it was edited.

| Source | Version | Role in the project | Tables | Columns | Rows |
|---|---|---|---|---|---|
| MIMIC-IV Clinical Database Demo | v1.0 (`core`, `hosp`, `icu`) | Messy source system; the version the OMOP ETL used | 27 | 311 | 1,307,744 |
| MIMIC-IV Clinical Database Demo | v2.2 (`hosp`, `icu`) | Matches current MIMIC documentation | 32 | 343 | 1,398,600 |
| MIMIC-IV demo in OMOP CDM | v0.9 (CDM 5.3.1) | Mapping ground truth (one ETL team's choices) | 32 | 367 | 467,840 |
| NHANES 2017-2018 (CDC) | cycle suffix `_J` | Survey data with per-file codebooks | 14 | 314 | 111,459 |
| **Total** | | | **105** | **1,335** | **3,285,643** |

*Table 1. Sources in the frozen snapshot.*

<!-- Table row counts per version are sums of tables/inventory_by_schema.csv rows
     (v1.0: core + hosp + icu; v2.2: demo_subject_id + hosp + icu). -->

Both MIMIC releases and the OMOP demo cover the same 100 patients. The largest table is ICU
`chartevents` (668,862 rows in v2.2). The retrieval corpus built from the documentation holds
1,270 section-level records: 432 from the NHANES codebooks, 405 from the MIMIC documentation and
433 from the OMOP specification (corpus_v1).

## What the data looks like

**The documentation and the data disagree on schema version.** The OMOP demo was built from MIMIC
v1.0, whereas current MIMIC documentation describes v2.x, where `core` is merged into `hosp`. Of
the 27 tables present in both releases, 12 changed columns. For example, `admissions` drops
`ethnicity` and gains `race` and `admit_provider_id`, `d_labitems` drops `loinc_code`, and
`procedureevents` drops five columns. Four tables exist only in v2.2 (`provider`, `omr`,
`caregiver`, `ingredientevents`). We keep this mismatch on purpose as a test case for Problem 1.

**Missing values vary widely by source.** Table 2 shows the share of columns that are fully
populated and fully null (tables with no rows are excluded).

| Schema | Columns | Fully populated | All null |
|---|---|---|---|
| MIMIC v1.0 `core` | 28 | 67.9% | 3.6% |
| MIMIC v1.0 `hosp` | 187 | 45.5% | 1.6% |
| MIMIC v1.0 `icu` | 96 | 83.3% | 4.2% |
| MIMIC v2.2 `hosp` | 229 | 48.9% | 1.3% |
| MIMIC v2.2 `icu` | 113 | 84.1% | 0.0% |
| OMOP v0.9 | 257 | 67.3% | 20.2% |
| NHANES 2017-2018 | 314 | 18.2% | 0.3% |

*Table 2. Column completeness by schema.* In total 64 columns are entirely null, 52 of them in
OMOP, and 10 of the 32 OMOP tables are empty (for example `note`, `cost` and `provider`). The
low NHANES completeness is mostly partial missingness: 46.2% of its columns are 50% to under
100% null, which fits questionnaire skip logic, though we have not verified this per variable.

**NHANES special codes must not be read as values.** In 122 of the 314 NHANES columns, 6,625
cells hold "Refused", "Don't know" or "Unknown" codes (Table 3). The same number can be a real
value in another variable (7 is "Refused" in DIQ010 but "7 or more people" in DMDHHSIZ), so we
take the codes from each variable's own codebook entry, not from the values. "Could not obtain"
is not counted: it only appears in body-measure comment columns, which record why a measurement
is missing (decision D-next). The worst case is DID320, where 684 of 885 non-null rows (77.3%)
are a code.

| Code | Meaning | Variables | Cells |
|---|---|---|---|
| 9999 | Don't know | 11 | 2,096 |
| 9 | Don't know | 69 | 1,965 |
| 99999 | Don't know | 19 | 961 |
| 99 | Don't know | 12 | 627 |
| 77 | Refused | 6 | 394 |
| 999 | Don't know | 9 | 363 |
| 55555 | Unknown | 2 | 97 |
| 7 | Refused | 20 | 50 |
| 77777 / 7777 / 777 | Refused | 3 / 6 / 2 | 39 / 30 / 3 |

*Table 3. NHANES refused, don't-know and unknown codes by code.* A variable can carry several
codes, so the Variables column does not sum to 122.

**NHANES zeros are not zeros.** Every value documented as 0 is stored as 5.4e-79 (the SAS
transport encoding of zero, read without rounding), so `WHERE x = 0` finds nothing. It affects
27 of 303 numeric columns and 23,897 cells; in `DMDHHSZA` it hits 6,183 of 9,254 rows (66.8%).
We keep the snapshot as is and treat this as a Silver-layer rule (decision D10).

**Patient identifiers join cleanly.** All 100 `person_source_value` values in OMOP match the MIMIC
`subject_id` values, and none of the 46 MIMIC tables with a `subject_id` holds a patient outside
the 100-patient demo list.

## Consequences for the medallion layers

- **Bronze** keeps every table unchanged and records a column profile (type, null count,
  distinct count, special codes) so that later layers can check claims against the data.
- **Silver** rules follow directly from the findings: map the renamed and dropped v1.0 columns,
  round the encoded NHANES zeros, and set refused, don't-know and unknown codes aside before
  computing anything. These are the places where documentation and data disagree, which is what our
  agents must detect.
- **Gold** definitions (for example what counts as "diabetes") depend on one team's judgment and
  are not decided by this profile.

## Limitations

- Only 100 patients, so distribution checks are weak and rare codes may appear once or never.
- The OMOP demo is one ETL team's set of choices, not universal truth; its empty tables and
  all-null columns reflect those choices.
- Completeness counts literal NULLs only. NHANES codes and encoded zeros are reported separately.
- Special codes come from the codebook text of the 2017-2018 cycle; variable names and codes
  change in other cycles.

## Reproducibility

Profile run `2026-11-10_p3_profile` (code commit `980202f`, data snapshot v1, corpus_v1 sha256
`6333aa6e...`), built by `scripts/profile_tables.py` and `notebooks/tabular_eda.ipynb`.
