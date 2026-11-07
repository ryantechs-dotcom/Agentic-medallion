import pytest

from medrag import contracts


def corpus_record(**overrides):
    record = {"id": "nhanes/x.htm#A", "doc": "nhanes/x.htm", "section": "A",
              "source": "nhanes", "kind": "nhanes_variable", "title": "A - thing",
              "text": "A - thing\n7 | Refused | 3", "order": 0, "metadata": {}}
    record.update(overrides)
    return record


def test_valid_record_passes():
    record = corpus_record()
    assert contracts.validate(record, "corpus_record") is record


def test_missing_field_is_named():
    record = corpus_record()
    del record["text"]
    with pytest.raises(ValueError, match="'text'"):
        contracts.validate(record, "corpus_record")


@pytest.mark.parametrize("field, value", [("order", "0"), ("order", True), ("metadata", [])])
def test_wrong_type_is_named(field, value):
    with pytest.raises(ValueError, match=f"'{field}'"):
        contracts.validate(corpus_record(**{field: value}), "corpus_record")


def test_unknown_source_rejected():
    with pytest.raises(ValueError, match="'source'"):
        contracts.validate(corpus_record(source="cdc"), "corpus_record")


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError, match="duplicate id"):
        contracts.validate_all([corpus_record(), corpus_record(order=1)], "corpus_record")


def test_unknown_format_rejected():
    with pytest.raises(ValueError, match="unknown format"):
        contracts.validate({}, "spec")


def test_score_accepts_int_and_float():
    chunk = {"chunk_id": "c1", "doc": "d", "section": "s", "text": "t", "score": 1}
    contracts.validate(chunk, "retrieved_chunk")
    contracts.validate(dict(chunk, score=0.5), "retrieved_chunk")


def test_matches_gold_by_section_or_text():
    record = corpus_record(text="The core\u00a0module has been removed.")
    assert contracts.matches_gold(record, "nhanes/x.htm", "a")
    assert contracts.matches_gold(record, "nhanes/x.htm", "core module has  been removed")
    assert not contracts.matches_gold(record, "nhanes/y.htm", "A")
    assert not contracts.matches_gold(record, "nhanes/x.htm", "hosp module")


def test_load_prompt_checks_name_and_hashes(tmp_path):
    from medrag import generation

    (tmp_path / "proposer_v1.txt").write_bytes(b"Propose a mapping.\n")
    prompt = generation.load_prompt("proposer_v1", tmp_path)
    assert prompt["text"] == "Propose a mapping.\n" and len(prompt["sha256"]) == 64
    assert prompt["file"].endswith("proposer_v1.txt")
    with pytest.raises(ValueError, match="must look like"):
        generation.load_prompt("proposer", tmp_path)
    with pytest.raises(FileNotFoundError):
        generation.load_prompt("proposer_v2", tmp_path)


def test_load_prompt_defaults_to_p1_folder():
    from medrag import generation

    assert generation.PROMPT_DIR.name == "prompts" and generation.PROMPT_DIR.is_dir()


def p2_spec(**overrides):
    spec = {"spec_id": "patients.gender", "source_schema": "mimic_demo_v1_0_core",
            "source_table": "patients", "source_column": "gender", "target_table": "person",
            "target_field": "gender_concept_id", "mapping_type": "concept_lookup",
            "target_type": "integer", "transform_rule": "F -> 8532, M -> 8507",
            "evidence": [{"doc": "omop/OMOP_CDMv5.3_Field_Level.csv",
                          "section": "person.gender_concept_id"}],
            "confidence": 0.9, "status": "proposed", "agent": "single"}
    spec.update(overrides)
    return spec


def test_p2_spec_validates():
    contracts.validate(p2_spec(), "p2_spec")
    contracts.validate(p2_spec(target_table=None, target_field=None,
                               mapping_type="not_mapped"), "p2_spec")
    with pytest.raises(ValueError, match="'mapping_type'"):
        contracts.validate(p2_spec(mapping_type="guess"), "p2_spec")
    with pytest.raises(ValueError, match="'status'"):
        contracts.validate(p2_spec(status="done"), "p2_spec")


def test_p2_mapping_types_match_ground_truth():
    gt = pytest.importorskip("medrag_p2.ground_truth")
    assert set(contracts.P2_MAPPING_TYPES) == set(gt.MAPPING_TYPES)
