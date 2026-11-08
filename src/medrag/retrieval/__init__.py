"""Retrievers. All implement the contract in retrieval/base.py (docs/contracts.md section 4).

Typical use (P1 conditions 3/4 and P2 agents):

    from medrag.config import load_config
    from medrag.retrieval import build_retriever, search_docs
    retriever = build_retriever(load_config())
    search_docs(retriever, "What does DIQ010 = 9 mean?", k=5, filters={"source": "nhanes"})
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from medrag.config import PROJECT_ROOT
from medrag.corpus.chunking import load_records, make_chunks
from medrag.retrieval.base import Retriever, search_docs
from medrag.retrieval.bm25 import BM25Retriever
from medrag.retrieval.dense import DenseRetriever, EmbedFn, load_embedder
from medrag.retrieval.hybrid import HybridRetriever

__all__ = ["build_retriever", "load_chunks", "search_docs", "Retriever", "BM25Retriever",
           "DenseRetriever", "HybridRetriever"]

KINDS = ("bm25", "dense", "hybrid")


def load_chunks(config: dict) -> list[dict]:
    """Load the corpus named in config and chunk it with the configured strategy."""
    records = load_records(PROJECT_ROOT / config["paths"]["corpus_file"])
    return make_chunks(records, config["retrieval"])


def embedding_cache(config: dict, chunks: list[dict]) -> Path:
    """Cache path for chunk embeddings, keyed on model, strategy and the chunk texts.

    The key hashes every chunk id and text, so a changed corpus or chunking can't reuse a
    stale cache.
    """
    settings = config["retrieval"]
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(f"{chunk['chunk_id']}\n{chunk['text']}\n".encode("utf-8"))
    model = re.sub(r"[^A-Za-z0-9.-]+", "-", settings["embedding_model"])
    name = f"{model}_{settings['chunking']}_{digest.hexdigest()[:12]}.npy"
    return PROJECT_ROOT / settings["index_dir"] / name


def build_retriever(config: dict, kind: str | None = None, chunks: list[dict] | None = None,
                    embed_fn: EmbedFn | None = None) -> Retriever:
    """Build a bm25, dense or hybrid retriever (default `retrieval.kind`) from config.

    `chunks` and `embed_fn` can be passed in (tests, or to share one chunk list between
    retrievers); otherwise the corpus is loaded and the configured model is used.
    """
    settings = config["retrieval"]
    kind = kind or settings["kind"]
    if kind not in KINDS:
        raise ValueError(f"unknown retriever {kind!r}; expected one of {KINDS}")
    if chunks is None:
        chunks = load_chunks(config)
    stopwords = settings.get("bm25_stopwords", "none")
    if kind == "bm25":
        return BM25Retriever(chunks, stopwords)
    if embed_fn is None:
        embed_fn = load_embedder(settings["embedding_model"])
        cache = embedding_cache(config, chunks)
    else:
        cache = None                    # never cache a caller-supplied (e.g. fake) embedder
    dense = DenseRetriever(chunks, embed_fn, settings["query_prefix"], cache)
    if kind == "dense":
        return dense
    if settings["fusion"] != "rrf":
        raise ValueError(f"unknown fusion {settings['fusion']!r}; only rrf is implemented")
    return HybridRetriever([BM25Retriever(chunks, stopwords), dense], settings["rrf_k"],
                           settings["candidates"])
