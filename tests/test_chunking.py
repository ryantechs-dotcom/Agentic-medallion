"""Chunking: contract-3 chunks, line-boundary splits, fixed windows."""

import pytest

from medrag import contracts
from medrag.corpus.chunking import (chunk_fixed, chunk_structured, make_chunks, n_tokens,
                                    split_lines)


def record(rid, text, order=0, doc="nhanes/2017-2018_DIQ_J.htm", section="DIQ010"):
    return {"id": rid, "doc": doc, "section": section, "source": "nhanes",
            "kind": "nhanes_variable", "title": text.split("\n")[0], "text": text,
            "order": order, "metadata": {"component": "DIQ_J"}}


LONG = "DIQ010 - Doctor told\n" + "\n".join(f"{i} | code row {i} | 5 | " for i in range(40))


def test_short_record_is_one_chunk_with_record_id():
    chunks = chunk_structured([record("a#X", "X - title\nbody text")], max_tokens=50)
    assert [c["chunk_id"] for c in chunks] == ["a#X"]
    assert chunks[0]["record_id"] == "a#X"
    assert chunks[0]["strategy"] == "structure"
    assert chunks[0]["metadata"]["component"] == "DIQ_J"
    assert chunks[0]["metadata"]["chunk_tokens"] == 5      # X - title body text


def test_long_record_splits_on_lines_and_repeats_title():
    chunks = chunk_structured([record("d#DIQ010", LONG)], max_tokens=30)
    assert len(chunks) > 1
    assert [c["chunk_id"] for c in chunks][:2] == ["d#DIQ010#part1", "d#DIQ010#part2"]
    for chunk in chunks:
        assert chunk["text"].startswith("DIQ010 - Doctor told\n")
        assert n_tokens(chunk["text"]) <= 30
        assert chunk["record_id"] == "d#DIQ010"
    body = [line for c in chunks for line in c["text"].split("\n")[1:]]
    assert body == LONG.split("\n")[1:]          # every code row kept whole, in order


def test_single_overlong_line_is_cut_between_words():
    parts = split_lines("T\n" + " ".join(["w"] * 25), max_tokens=10)
    assert all(n_tokens(p) <= 10 for p in parts)
    assert sum(n_tokens(p) - 1 for p in parts) == 25


def test_fixed_windows_overlap_and_stay_within_doc():
    records = [record("d#A", " ".join(f"a{i}" for i in range(30)), order=0, section="A"),
               record("d#B", " ".join(f"b{i}" for i in range(30)), order=1, section="B"),
               record("e#C", "c0 c1", order=2, doc="other.htm", section="C")]
    chunks = chunk_fixed(records, tokens=20, overlap=5)
    ids = [c["chunk_id"] for c in chunks]
    assert ids[:2] == ["nhanes/2017-2018_DIQ_J.htm@1", "nhanes/2017-2018_DIQ_J.htm@2"]
    first, second = chunks[0]["text"].split(), chunks[1]["text"].split()
    assert first[-5:] == second[:5]
    assert chunks[1]["record_id"] == "d#A"        # window starts inside record A
    assert chunks[-1]["text"] == "c0 c1" and chunks[-1]["doc"] == "other.htm"
    assert all(c["metadata"]["overlap"] == 5 for c in chunks)


def test_fixed_rejects_bad_overlap():
    with pytest.raises(ValueError):
        chunk_fixed([record("a#X", "x y")], tokens=10, overlap=10)


def test_make_chunks_uses_config_and_validates():
    settings = {"chunking": "structure", "max_chunk_tokens": 30, "fixed_chunk_tokens": 20,
                "fixed_chunk_overlap": 5}
    chunks = make_chunks([record("d#DIQ010", LONG)], settings)
    contracts.validate_all(chunks, "chunk")
    with pytest.raises(ValueError):
        make_chunks([], {**settings, "chunking": "semantic"})
