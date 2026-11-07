"""Tests for the P2 ground-truth checker. Pure checks need nothing; data checks need data/."""

import csv

import pytest

from medrag import db
from medrag.config import db_path
from medrag_p2 import ground_truth as gt

needs_data = pytest.mark.skipif(not db_path().exists(), reason="data snapshot not unzipped")


def make_row(**overrides):
    row = {c: "" for c in gt.REQUIRED_COLUMNS}
    row.update(gt_id="T-1", source_schema="mimic_demo_v1_0_core", source_table="patients",
               source_column="gender", target_table="person",
               target_field="gender_source_value", is_primary="Y", mapping_type="direct",
               etl_evidence="etl/etl/cdm_person.sql:132", split="dev",
               verify_sql="SELECT 1 AS n_checked, 0 AS n_mismatch")
    row.update(overrides)
    return row


def test_parse_refs():
    assert gt.parse_refs("a.sql:3-5; b.csv; c.sql:7") == [
        ("a.sql", 3, 5), ("b.csv", None, None), ("c.sql", 7, 7)]
    with pytest.raises(ValueError):
        gt.parse_refs("a.sql:x")


def test_shape_accepts_valid_rows():
    assert gt.shape_problems(make_row()) == []
    assert gt.shape_problems(make_row(mapping_type="not_mapped", target_table="",
                                      target_field="", verify_sql="")) == []


@pytest.mark.parametrize("overrides", [
    {"mapping_type": "guess"},
    {"is_primary": "yes"},
    {"split": "train"},
    {"mapping_type": "not_mapped"},          # not_mapped but has a target
    {"target_field": ""},                    # mapped but no target field
    {"verify_sql": ""},                      # mapped rows need a data check
    {"etl_evidence": ""},
])
def test_shape_rejects_bad_rows(overrides):
    assert gt.shape_problems(make_row(**overrides))


def test_data_verdict():
    assert gt.data_verdict(100, 0) is None
    assert gt.data_verdict(0, 0)             # empty join must not pass silently
    assert gt.data_verdict(100, 3)


@needs_data
def test_draft_rows_all_pass():
    with gt.DEFAULT_CSV.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    results = gt.check(rows, db.connect(), gt.etl_root())
    assert [r["row"]["gt_id"] for r in results if r["problems"]] == []


@needs_data
@pytest.mark.parametrize("overrides", [
    # wrong target field: the data check finds mismatches
    {"target_field": "race_source_value",
     "verify_sql": "SELECT COUNT(*) AS n_checked, SUM(CASE WHEN per.race_source_value "
                   "IS DISTINCT FROM p.gender THEN 1 ELSE 0 END) AS n_mismatch "
                   "FROM mimic_demo_v1_0_core.patients p JOIN omop_demo_v0_9.person per "
                   "ON per.person_source_value = CAST(p.subject_id AS VARCHAR)"},
    {"target_field": "no_such_field"},
    {"source_column": "no_such_column"},
    {"etl_evidence": "etl/etl/cdm_person.sql:113"},       # cited line doesn't mention gender
    {"etl_evidence": "etl/etl/cdm_person.sql:99999"},
    {"etl_evidence": "etl/etl/missing.sql"},
    {"acceptable_alternatives": "person.no_such_field"},
    {"verify_sql": "SELECT 0 AS n_checked, 0 AS n_mismatch"},
    {"verify_sql": "SELECT 1 AS n"},
])
def test_checker_catches_wrong_rows(overrides):
    results = gt.check([make_row(**overrides)], db.connect(), gt.etl_root())
    assert results[0]["problems"]
