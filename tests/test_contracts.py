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
    record = corpus_record(text="The core module has been removed.")
    assert contracts.matches_gold(record, "nhanes/x.htm", "a")
    assert contracts.matches_gold(record, "nhanes/x.htm", "core module has  been removed")
    assert not contracts.matches_gold(record, "nhanes/y.htm", "A")
    assert not contracts.matches_gold(record, "nhanes/x.htm", "hosp module")


def test_load_prompt_checks_name_and_hashes(tmp_path, monkeypatch):
    from medrag import generation

    monkeypatch.setattr(generation, "PROMPT_DIR", tmp_path)
    (tmp_path / "p1_answer_v1.txt").write_bytes(b"Answer from the context.\n")
    text, sha = generation.load_prompt("p1_answer_v1")
    assert text == "Answer from the context.\n" and len(sha) == 64
    with pytest.raises(ValueError, match="must look like"):
        generation.load_prompt("answer")
    with pytest.raises(FileNotFoundError):
        generation.load_prompt("p1_answer_v2")
