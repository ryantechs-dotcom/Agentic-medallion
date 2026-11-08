"""Chunking and tools on the real snapshot (skipped when data/ or the corpus is missing).

Gold coverage reads only gold metadata, never system output: if structure chunking ever
splits a record so that no chunk supports a gold reference, fix the chunking, not the gold.
"""

import csv

import pytest

from medrag.config import PROJECT_ROOT, load_config
from medrag.contracts import matches_gold
from medrag.retrieval import build_retriever, load_chunks, search_docs
from medrag.verify.profile import profile_column

CORPUS = PROJECT_ROOT / "corpus" / "corpus_v1.jsonl"


@pytest.fixture(scope="module")
def chunks():
    if not CORPUS.exists():
        pytest.skip("corpus not built")
    return load_chunks(load_config())


def gold_references():
    with (PROJECT_ROOT / "eval" / "questions.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    refs = [(r["qid"], r["gold_doc"], r["gold_section"]) for r in rows if r["gold_doc"]]
    for row in rows:
        for entry in filter(None, row["gold_evidence"].split(";")):
            doc, _, section = entry.partition("#")
            refs.append((row["qid"], doc, section))
    return refs


def test_structure_chunks_cover_every_gold_reference(chunks):
    missing = [(qid, doc, section) for qid, doc, section in gold_references()
               if not any(matches_gold(c, doc, section) for c in chunks)]
    assert not missing, f"{len(missing)} gold references not covered, e.g. {missing[:3]}"


def test_no_structure_chunk_exceeds_limit(chunks):
    limit = load_config()["retrieval"]["max_chunk_tokens"]
    assert max(c["metadata"]["chunk_tokens"] for c in chunks) <= limit


def test_bm25_finds_diq010_on_real_corpus(chunks):
    retriever = build_retriever(load_config(), "bm25", chunks=chunks)
    out = search_docs(retriever, "What does DIQ010 = 9 mean?", 5,
                      {"source": "nhanes", "table": "DIQ_J"})
    assert out["chunks"][0]["chunk_id"] == "nhanes/2017-2018_DIQ_J.htm#DIQ010"


def test_profile_matches_contract_example(snapshot_required):
    profile = profile_column("mimic_demo_v1_0_core", "patients", "gender", top_k=10)
    assert profile == {
        "dtype": "VARCHAR", "n_rows": 100, "n_null": 0, "n_distinct": 2,
        "top_values": [{"value": "M", "count": 57}, {"value": "F", "count": 43}],
        "min": None, "max": None, "special_codes": [],
    }
