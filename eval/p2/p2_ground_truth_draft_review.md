# P2 ground truth check: p2_ground_truth_draft.csv

77 rows, 0 with problems.

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
| P2-034 | transfers.subject_id | visit_detail.person_id | derived | Y | ok, 861 rows |
| P2-035 | transfers.hadm_id | visit_detail.visit_occurrence_id | derived | Y | ok, 861 rows |
| P2-036 | transfers.transfer_id | visit_detail.visit_detail_source_value | transform | Y | ok, 861 rows |
| P2-037 | transfers.eventtype | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
| P2-038 | transfers.careunit | visit_detail.care_site_id | derived | Y | ok, 825 rows |
| P2-039 | transfers.careunit | care_site.care_site_source_value | transform | N | ok, 31 rows |
| P2-040 | transfers.careunit | care_site.care_site_name | transform | N | ok, 31 rows |
| P2-041 | transfers.careunit | visit_detail.visit_detail_concept_id | concept_lookup | N | ok, 617 rows |
| P2-042 | transfers.intime | visit_detail.visit_detail_start_datetime | direct | Y | ok, 861 rows |
| P2-043 | transfers.intime | visit_detail.visit_detail_start_date | transform | N | ok, 861 rows |
| P2-044 | transfers.outtime | visit_detail.visit_detail_end_datetime | direct | Y | ok, 861 rows |
| P2-045 | transfers.outtime | visit_detail.visit_detail_end_date | transform | N | ok, 861 rows |
| P2-046 | diagnoses_icd.subject_id | condition_occurrence.person_id | derived | Y | ok, 3833 rows |
| P2-047 | diagnoses_icd.hadm_id | condition_occurrence.visit_occurrence_id | derived | Y | ok, 3833 rows |
| P2-048 | diagnoses_icd.icd_code | condition_occurrence.condition_source_value | transform | Y | ok, 3833 rows |
| P2-049 | diagnoses_icd.icd_code | observation.observation_source_value | transform | N | ok, 853 rows |
| P2-050 | diagnoses_icd.icd_version | condition_occurrence.condition_source_concept_id | concept_lookup | Y | ok, 3833 rows |
| P2-051 | diagnoses_icd.seq_num | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
| P2-052 | prescriptions.subject_id | drug_exposure.person_id | derived | Y | ok, 18229 rows |
| P2-053 | prescriptions.hadm_id | drug_exposure.visit_occurrence_id | derived | Y | ok, 18229 rows |
| P2-054 | prescriptions.pharmacy_id | drug_exposure.drug_source_value | derived | Y | ok, 2977 rows |
| P2-055 | prescriptions.starttime | drug_exposure.drug_exposure_start_datetime | direct | Y | ok, 18229 rows |
| P2-056 | prescriptions.starttime | drug_exposure.drug_exposure_start_date | transform | N | ok, 18229 rows |
| P2-057 | prescriptions.stoptime | drug_exposure.drug_exposure_end_datetime | transform | Y | ok, 18229 rows |
| P2-058 | prescriptions.drug_type | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
| P2-059 | prescriptions.drug | drug_exposure.drug_source_value | transform | Y | ok, 2977 rows |
| P2-060 | prescriptions.gsn | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
| P2-061 | prescriptions.ndc | drug_exposure.drug_source_value | transform | Y | ok, 15252 rows |
| P2-062 | prescriptions.ndc | drug_exposure.drug_source_concept_id | concept_lookup | N | ok, 15252 rows |
| P2-063 | prescriptions.prod_strength | drug_exposure.drug_source_value | transform | Y | ok, 2977 rows |
| P2-064 | prescriptions.form_rx | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
| P2-065 | prescriptions.dose_val_rx | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
| P2-066 | prescriptions.dose_unit_rx | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
| P2-067 | prescriptions.form_val_disp | drug_exposure.quantity | transform | Y | ok, 18229 rows |
| P2-068 | prescriptions.form_unit_disp | drug_exposure.dose_unit_source_value | direct | Y | ok, 18229 rows |
| P2-069 | prescriptions.doses_per_24_hrs | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
| P2-070 | prescriptions.route | drug_exposure.route_source_value | direct | Y | ok, 18229 rows |
| P2-071 | prescriptions.route | drug_exposure.route_concept_id | concept_lookup | N | ok, 18229 rows |
| P2-072 | procedures_icd.subject_id | procedure_occurrence.person_id | derived | Y | ok, 305 rows |
| P2-073 | procedures_icd.hadm_id | procedure_occurrence.visit_occurrence_id | derived | Y | ok, 305 rows |
| P2-074 | procedures_icd.icd_code | procedure_occurrence.procedure_source_value | transform | Y | ok, 305 rows |
| P2-075 | procedures_icd.icd_version | procedure_occurrence.procedure_source_concept_id | concept_lookup | Y | ok, 305 rows |
| P2-076 | procedures_icd.chartdate | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
| P2-077 | procedures_icd.seq_num | (not mapped) | not_mapped | Y | no SQL (not_mapped) |
