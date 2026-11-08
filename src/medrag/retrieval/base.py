"""Shared pieces of the retriever tool contract (docs/contracts.md section 4).

Every retriever implements `search(query, k, filters=None) -> list[dict]` and returns
`retrieved_chunk` dicts `{chunk_id, doc, section, text, score}` sorted by descending score.
`search_docs` wraps any retriever in the contract-4 output that P1 and P2 agents call.
Problem 2 depends on this contract: agree changes with Skylar first.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from medrag import contracts

# filters["table"] is compared with the metadata key that names a "table" in each source
TABLE_KEYS = ("component", "page", "table")


class Retriever(Protocol):
    """Anything with a contract-4 `search` method."""

    def search(self, query: str, k: int, filters: dict | None = None) -> list[dict]:
        ...


def filter_mask(chunks: list[dict], filters: dict | None) -> np.ndarray:
    """Return a boolean mask of chunks matching `filters` ({source?, table?}).

    `table` matches `metadata.component` (NHANES), `metadata.page` (MIMIC) or
    `metadata.table` (OMOP), ignoring case. Unknown filter keys raise, so a typo can't
    silently return unfiltered results.
    """
    filters = {key: value for key, value in (filters or {}).items() if value}
    unknown = set(filters) - {"source", "table"}
    if unknown:
        raise ValueError(f"unknown filter keys {sorted(unknown)}; allowed: source, table")
    mask = np.ones(len(chunks), dtype=bool)
    if "source" in filters:
        mask &= np.array([c["source"] == filters["source"] for c in chunks], dtype=bool)
    if "table" in filters:
        wanted = str(filters["table"]).lower()
        mask &= np.array([
            any(str(c["metadata"].get(key, "")).lower() == wanted for key in TABLE_KEYS)
            for c in chunks
        ], dtype=bool)
    return mask


def top_k(chunks: list[dict], scores: np.ndarray, mask: np.ndarray, k: int) -> list[dict]:
    """Return the k best-scoring chunks allowed by `mask` as `retrieved_chunk` dicts.

    Ties keep corpus order (stable sort), so results are deterministic.
    """
    allowed = np.flatnonzero(mask)
    order = allowed[np.argsort(-scores[allowed], kind="stable")][:k]
    return [to_retrieved(chunks[i], float(scores[i])) for i in order]


def to_retrieved(chunk: dict, score: float) -> dict:
    """Project a chunk onto the `retrieved_chunk` fields."""
    return {"chunk_id": chunk["chunk_id"], "doc": chunk["doc"], "section": chunk["section"],
            "text": chunk["text"], "score": score}


def search_docs(retriever: Retriever, query: str, k: int,
                filters: dict | None = None) -> dict:
    """Run a retriever and return the contract-4 tool output."""
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    chunks = contracts.validate_all(retriever.search(query, k, filters), "retrieved_chunk")
    return {"chunks": chunks, "answer": None, "verified": None, "sql": None}
