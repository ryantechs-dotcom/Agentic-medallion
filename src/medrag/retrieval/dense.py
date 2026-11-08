"""Dense embedding retrieval (condition 3b).

Model: `retrieval.embedding_model` in config (BAAI/bge-small-en-v1.5, DECISIONS D-next).
Cosine similarity is a dot product of L2-normalized vectors; with about 1,300 chunks, brute
force is exact and fast, so there is no approximate index.

`embed_fn(texts) -> np.ndarray` is injected, so tests use a fake embedder with no model
download. sentence-transformers is an optional extra (`pip install -e ".[dense]"`) and is
imported only when the real model is loaded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

from medrag.retrieval.base import filter_mask, top_k

EmbedFn = Callable[[list[str]], np.ndarray]


def normalize(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize rows (zero rows stay zero)."""
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def load_embedder(model_name: str, batch_size: int = 64) -> EmbedFn:
    """Return an embed function backed by a sentence-transformers model."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as err:          # optional extra, not installed in CI
        raise ImportError('dense retrieval needs: pip install -e ".[dense]"') from err
    model = SentenceTransformer(model_name, device="cpu")

    def embed(texts: list[str]) -> np.ndarray:
        return model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                            show_progress_bar=False, convert_to_numpy=True)
    return embed


def cached_embeddings(texts: list[str], embed_fn: EmbedFn, cache: Path | None) -> np.ndarray:
    """Embed `texts`, reusing `cache` (.npy) when it exists with the right row count."""
    if cache is not None and cache.exists():
        vectors = np.load(cache)
        if len(vectors) == len(texts):
            return vectors
    vectors = normalize(embed_fn(texts))
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.save(cache, vectors)
    return vectors


class DenseRetriever:
    """Cosine similarity between the query embedding and every chunk embedding."""

    def __init__(self, chunks: list[dict], embed_fn: EmbedFn, query_prefix: str = "",
                 cache: Path | None = None):
        self.chunks = chunks
        self.embed_fn = embed_fn
        self.query_prefix = query_prefix
        self.vectors = cached_embeddings([c["text"] for c in chunks], embed_fn, cache)

    def scores(self, query: str) -> np.ndarray:
        """Return one cosine similarity per chunk."""
        query_vector = normalize(self.embed_fn([self.query_prefix + query]))[0]
        return self.vectors @ query_vector

    def search(self, query: str, k: int, filters: dict | None = None) -> list[dict]:
        return top_k(self.chunks, self.scores(query), filter_mask(self.chunks, filters), k)
