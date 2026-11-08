"""Retrievers on a tiny chunk set; dense uses a fake embedder (no model download)."""

import numpy as np
import pytest

from medrag import contracts
from medrag.evaluation.metrics import by_group, first_hit_rank, mrr, recall_at_k
from medrag.retrieval import build_retriever, search_docs
from medrag.retrieval.base import filter_mask
from medrag.retrieval.bm25 import ENGLISH_STOPWORDS, BM25Retriever, tokenize
from medrag.retrieval.dense import DenseRetriever
from medrag.retrieval.hybrid import HybridRetriever, rrf

VOCAB = ("diabetes", "refused", "gender", "concept", "admission", "weight")


def chunk(cid, text, source, **metadata):
    return {"chunk_id": cid, "record_id": cid, "doc": cid.split("#")[0],
            "section": cid.split("#")[-1], "source": source, "strategy": "structure",
            "text": text, "metadata": metadata}


CHUNKS = [
    chunk("nhanes/DIQ.htm#DIQ010", "DIQ010 - Doctor told you have diabetes\n7 | Refused\n"
          "9 | Don't know", "nhanes", component="DIQ_J"),
    chunk("nhanes/BMX.htm#BMXWT", "BMXWT - Weight (kg)", "nhanes", component="BMX_J"),
    chunk("omop/fields.csv#person.gender_concept_id", "person.gender_concept_id - concept "
          "for the gender of the person", "omop", table="person"),
    chunk("mimic/admissions.md#admittime", "admittime - time of hospital admission", "mimic",
          page="admissions"),
]


def fake_embed(texts):
    """Bag-of-words over a tiny vocabulary: deterministic and dependency-free."""
    return np.array([[t.lower().count(word) for word in VOCAB] for t in texts], dtype=float)


def test_tokenize_keeps_identifiers_and_their_parts():
    assert tokenize("person.gender_concept_id DIQ010") == [
        "person", "gender_concept_id", "gender", "concept", "id", "diq010"]


def test_stopwords_are_dropped_only_when_asked():
    assert tokenize("What does DIQ010 mean", ENGLISH_STOPWORDS) == ["diq010", "mean"]
    assert "what" in tokenize("What does DIQ010 mean")
    question_label = chunk("nhanes/DIQ.htm#DIQ291", "DIQ291 - What does Dr say A1C should be",
                           "nhanes", component="DIQ_J")
    chunks = [question_label] + CHUNKS
    query = "What does DIQ010 = 9 mean?"
    assert BM25Retriever(chunks, "english").search(query, 1)[0]["section"] == "DIQ010"
    with pytest.raises(ValueError):
        BM25Retriever(chunks, "french")


def test_bm25_finds_exact_identifier_and_plain_english():
    bm25 = BM25Retriever(CHUNKS)
    assert bm25.search("What does DIQ010 = 9 mean?", 1)[0]["section"] == "DIQ010"
    assert bm25.search("gender concept", 1)[0]["section"] == "person.gender_concept_id"


def test_filters_restrict_before_ranking():
    bm25 = BM25Retriever(CHUNKS)
    hits = bm25.search("diabetes", 5, {"source": "omop"})
    assert [h["chunk_id"] for h in hits] == ["omop/fields.csv#person.gender_concept_id"]
    assert filter_mask(CHUNKS, {"table": "diq_j"}).tolist() == [True, False, False, False]
    assert filter_mask(CHUNKS, {"table": "admissions"}).tolist() == [False, False, False, True]
    assert filter_mask(CHUNKS, {"source": None}).all()
    with pytest.raises(ValueError):
        filter_mask(CHUNKS, {"sourc": "omop"})


def test_dense_ranks_by_cosine():
    dense = DenseRetriever(CHUNKS, fake_embed)
    hits = dense.search("weight", 2)
    assert hits[0]["section"] == "BMXWT"
    assert hits[0]["score"] == pytest.approx(1.0)
    assert hits[0]["score"] >= hits[1]["score"]


def test_rrf_arithmetic():
    scores = rrf([[0, 1], [1, 2]], rrf_k=60, n_items=4)
    assert scores[1] == pytest.approx(1 / 62 + 1 / 61)
    assert scores[0] == pytest.approx(1 / 61)
    assert scores[3] == 0


def test_hybrid_fuses_and_respects_filters():
    hybrid = HybridRetriever([BM25Retriever(CHUNKS), DenseRetriever(CHUNKS, fake_embed)],
                             rrf_k=60, candidates=10)
    assert hybrid.search("diabetes refused", 1)[0]["section"] == "DIQ010"
    hits = hybrid.search("diabetes", 4, {"source": "mimic"})
    assert {h["doc"] for h in hits} == {"mimic/admissions.md"}


def test_search_docs_output_matches_contract():
    config = {"retrieval": {"kind": "hybrid", "query_prefix": "", "fusion": "rrf",
                            "rrf_k": 60, "candidates": 10}}
    retriever = build_retriever(config, chunks=CHUNKS, embed_fn=fake_embed)
    out = search_docs(retriever, "diabetes", k=2)
    assert set(out) == {"chunks", "answer", "verified", "sql"}
    assert len(out["chunks"]) <= 2
    contracts.validate_all(out["chunks"], "retrieved_chunk")
    scores = [c["score"] for c in out["chunks"]]
    assert scores == sorted(scores, reverse=True)
    with pytest.raises(ValueError):
        search_docs(retriever, "  ", k=2)
    with pytest.raises(ValueError):
        build_retriever(config, kind="splade", chunks=CHUNKS)


def test_retrieval_metrics():
    retrieved = [CHUNKS[1], CHUNKS[0]]
    assert first_hit_rank(retrieved, "nhanes/DIQ.htm", "DIQ010") == 2
    assert first_hit_rank(retrieved, "nhanes/DIQ.htm", "don't know") == 2   # text match
    assert first_hit_rank(retrieved, "omop/fields.csv", "person") is None
    ranks = [1, 2, None, 4]
    assert recall_at_k(ranks, 1) == 0.25
    assert recall_at_k(ranks, 5) == 0.75
    assert mrr(ranks) == pytest.approx((1 + 0.5 + 0.25) / 4)
    grouped = by_group([{"qtype": "a"}, {"qtype": "a"}, {"qtype": "b"}, {"qtype": "b"}],
                       ranks, ("qtype",), (1,))
    assert grouped["by_qtype"]["a"]["recall@1"] == 0.5
    assert grouped["overall"]["n"] == 4
