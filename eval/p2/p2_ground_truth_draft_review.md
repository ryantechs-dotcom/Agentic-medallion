# P2 ground truth check: p2_ground_truth_draft.csv

33 rows, 0 with problems.

## Rows

| gt_id | source | target | type | primary | data check |
|---|---|---|---|---|---|
| P2-001 | patients.subject_id | person.person_source_value | transform | Y | ok, 100 rows |
| P2-002 | patients.gender | person.gender_concept_id | concept_lookup | Y | ok, 100 rows |
| P2-003 | patients.gender | person.gender_source_value | direct | N | ok, 100 rows |
| P2-004 | patients.anchor_age | person.year_of_birth | derived | Y | ok, 100 rows |
| P2-005 | patients.anchor_year | person.year_of_birth | derived | Y | ok, 100 rows |
| P2-006 | patients.anchor_year_group | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
| P2-007 | patients.dod | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
| P2-008 | admissions.subject_id | visit_occurrence.person_id | derived | Y | ok, 275 rows |
| P2-009 | admissions.hadm_id | visit_occurrence.visit_source_value | transform | Y | ok, 275 rows |
| P2-010 | admissions.admittime | visit_occurrence.visit_start_datetime | transform | Y | ok, 275 rows |
| P2-011 | admissions.admittime | visit_occurrence.visit_start_date | transform | N | ok, 275 rows |
| P2-012 | admissions.admittime | observation.observation_datetime | derived | N | ok, 275 rows |
| P2-013 | admissions.dischtime | visit_occurrence.visit_end_datetime | direct | Y | ok, 275 rows |
| P2-014 | admissions.dischtime | visit_occurrence.visit_end_date | transform | N | ok, 275 rows |
| P2-015 | admissions.deathtime | death.death_datetime | transform | Y | ok, 15 rows |
| P2-016 | admissions.deathtime | death.death_date | transform | N | ok, 15 rows |
| P2-017 | admissions.dischtime | death.death_datetime | transform | N | ok, 15 rows |
| P2-018 | admissions.admission_type | visit_occurrence.visit_concept_id | concept_lookup | Y | ok, 275 rows |
| P2-019 | admissions.admission_location | visit_occurrence.admitting_source_value | direct | Y | ok, 275 rows |
| P2-020 | admissions.admission_location | visit_occurrence.admitting_source_concept_id | concept_lookup | N | ok, 275 rows |
| P2-021 | admissions.discharge_location | visit_occurrence.discharge_to_source_value | direct | Y | ok, 275 rows |
| P2-022 | admissions.discharge_location | visit_occurrence.discharge_to_concept_id | concept_lookup | N | ok, 275 rows |
| P2-023 | admissions.insurance | observation.value_as_string | transform | Y | ok, 275 rows |
| P2-024 | admissions.marital_status | observation.value_as_string | transform | Y | ok, 263 rows |
| P2-025 | admissions.language | observation.value_as_string | transform | Y | ok, 275 rows |
| P2-026 | admissions.ethnicity | person.race_source_value | transform | Y | ok, 100 rows |
| P2-027 | admissions.ethnicity | person.race_concept_id | concept_lookup | N | ok, 100 rows |
| P2-028 | admissions.ethnicity | person.ethnicity_source_value | transform | N | ok, 100 rows |
| P2-029 | admissions.ethnicity | person.ethnicity_concept_id | concept_lookup | N | ok, 100 rows |
| P2-030 | admissions.edregtime | visit_occurrence.visit_start_datetime | transform | Y | ok, 275 rows |
| P2-031 | admissions.edregtime | visit_detail.visit_detail_start_datetime | derived | N | ok, 102 rows |
| P2-032 | admissions.edouttime | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
| P2-033 | admissions.hospital_expire_flag | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
