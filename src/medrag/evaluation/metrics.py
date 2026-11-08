"""Metrics from docs/PROBLEM1_PLAN.md, broken down by qtype and source.

Implemented: retrieval recall@k and MRR, using the gold matching rule in
`medrag.contracts.matches_gold`. Planned: normalized exact match, citation correctness,
abstention vs. hallucination rate on unanswerable questions, tokens and latency.
"""

from __future__ import annotations

from collections import defaultdict

from medrag.contracts import matches_gold


def first_hit_rank(retrieved: list[dict], gold_doc: str, gold_section: str) -> int | None:
    """1-based rank of the first retrieved chunk that supports the gold reference, or None."""
    for rank, chunk in enumerate(retrieved, 1):
        if matches_gold(chunk, gold_doc, gold_section):
            return rank
    return None


def recall_at_k(ranks: list[int | None], k: int) -> float:
    """Share of questions whose first hit is within the top k."""
    if not ranks:
        return float("nan")
    return sum(1 for rank in ranks if rank is not None and rank <= k) / len(ranks)


def mrr(ranks: list[int | None]) -> float:
    """Mean reciprocal rank (a miss counts as 0)."""
    if not ranks:
        return float("nan")
    return sum(1 / rank for rank in ranks if rank is not None) / len(ranks)


def retrieval_metrics(ranks: list[int | None], ks: tuple[int, ...]) -> dict:
    """`{n, recall@k..., mrr}` for one group of questions."""
    out = {"n": len(ranks)}
    out.update({f"recall@{k}": recall_at_k(ranks, k) for k in ks})
    out["mrr"] = mrr(ranks)
    return out


def by_group(rows: list[dict], ranks: list[int | None], keys: tuple[str, ...],
             ks: tuple[int, ...]) -> dict:
    """Overall metrics plus one breakdown per key (e.g. qtype, source)."""
    result = {"overall": retrieval_metrics(ranks, ks)}
    for key in keys:
        groups: dict[str, list] = defaultdict(list)
        for row, rank in zip(rows, ranks):
            groups[row[key]].append(rank)
        result[f"by_{key}"] = {name: retrieval_metrics(group, ks)
                               for name, group in sorted(groups.items())}
    return result
