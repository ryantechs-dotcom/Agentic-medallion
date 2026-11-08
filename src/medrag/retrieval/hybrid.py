"""Hybrid retrieval: reciprocal rank fusion of BM25 and dense rankings (condition 3c).

RRF (Cormack et al., 2009): score(chunk) = sum over rankings of 1 / (rrf_k + rank), rank
starting at 1. It uses ranks only, so BM25 and cosine scores never need calibrating and there
is no mixing weight to tune (DECISIONS D-next). `rrf_k` and `candidates` come from config.
"""

from __future__ import annotations

import numpy as np

from medrag.retrieval.base import filter_mask, top_k


def rrf(rankings: list[list[int]], rrf_k: int, n_items: int) -> np.ndarray:
    """Return fused scores for items 0..n_items-1 from ranked lists of item indices."""
    scores = np.zeros(n_items, dtype=float)
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            scores[item] += 1.0 / (rrf_k + rank)
    return scores


def ranking(scores: np.ndarray, mask: np.ndarray, depth: int) -> list[int]:
    """Indices of the `depth` best allowed items, best first (stable on ties)."""
    allowed = np.flatnonzero(mask)
    return allowed[np.argsort(-scores[allowed], kind="stable")][:depth].tolist()


class HybridRetriever:
    """Fuse the top `candidates` of each sub-retriever with RRF."""

    def __init__(self, retrievers: list, rrf_k: int, candidates: int):
        self.retrievers = retrievers
        self.chunks = retrievers[0].chunks
        self.rrf_k = rrf_k
        self.candidates = candidates

    def search(self, query: str, k: int, filters: dict | None = None) -> list[dict]:
        mask = filter_mask(self.chunks, filters)
        rankings = [ranking(r.scores(query), mask, max(self.candidates, k))
                    for r in self.retrievers]
        fused = rrf(rankings, self.rrf_k, len(self.chunks))
        return top_k(self.chunks, fused, mask & (fused > 0), k)
