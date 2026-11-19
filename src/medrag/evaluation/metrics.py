"""Metrics from docs/PROBLEM1_PLAN.md, broken down by qtype and source.

Implemented: retrieval recall@k and MRR, using the gold matching rule in
`medrag.contracts.matches_gold`; answer metrics for runs (judge accuracy, citation correctness,
abstention vs. hallucination on unanswerable questions, errors, tokens and latency).
Undefined values (e.g. no judged items in a group) are None, so metrics.json stays valid JSON.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from medrag.contracts import matches_gold

GROUP_KEYS = ("qtype", "subtype", "source", "needs_data", "guessable")


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


def citation_check(citations: list[str], passages: list[dict], gold_doc: str,
                   gold_section: str) -> tuple[bool | None, list[str]]:
    """(hit, invalid) for one answer.

    `hit` is True if a cited passage supports the gold reference (same rule as retrieval
    recall), False if none does, and None when it can't be scored (no gold doc, or no passages
    were given, as in closed-book). `invalid` lists cited ids that were not in the context.
    """
    by_id = {p["id"]: p for p in passages}
    invalid = [c for c in citations if c not in by_id]
    if not gold_doc or not passages:
        return None, invalid
    hit = any(matches_gold(by_id[c], gold_doc, gold_section) for c in citations if c in by_id)
    return hit, invalid


def _share(items: list, test: Callable[[object], bool]) -> float | None:
    return sum(1 for item in items if test(item)) / len(items) if items else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def answer_metrics(items: list[dict]) -> dict:
    """Metrics for one group of `{row, output, judgment}` items (judgment may be None).

    - accuracy: share of judged items with verdict `correct`; partial_credit counts
      `partially_correct` as 0.5. Judged = answered or abstained, without error.
    - hallucination_rate: unanswerable items not judged correct (the model supplied an answer).
    - wrong_abstain_rate: answerable items where the model abstained.
    - citation_hit_rate: answered items with a gold doc and context whose citations support it.
    Skipped items (C2 unanswerable) are counted in `n_skipped` and left out of everything else.
    """
    skipped = [i for i in items if i["output"].get("skipped")]
    attempted = [i for i in items if not i["output"].get("skipped")]
    ok = [i for i in attempted if i["output"]["error"] is None]
    judged = [i for i in ok if i.get("judgment") and i["judgment"]["verdict"] is not None]
    verdict = [i["judgment"]["verdict"] for i in judged]
    unanswerable = [i for i in judged if i["row"]["qtype"] == "unanswerable"]
    answerable = [i for i in judged if i["row"]["qtype"] != "unanswerable"]
    cited = [i for i in ok if i["output"].get("citation_hit") is not None]
    return {
        "n": len(attempted), "n_skipped": len(skipped), "n_error": len(attempted) - len(ok),
        "n_judged": len(judged),
        "accuracy": _share(verdict, lambda v: v == "correct"),
        "partial_credit": (sum(1.0 if v == "correct" else 0.5 if v == "partially_correct"
                               else 0.0 for v in verdict) / len(verdict)) if verdict else None,
        "abstain_rate": _share(ok, lambda i: i["output"]["abstained"] is True),
        "hallucination_rate": _share(unanswerable,
                                     lambda i: i["judgment"]["verdict"] != "correct"),
        "wrong_abstain_rate": _share(answerable,
                                     lambda i: i["judgment"]["verdict"] == "abstained"),
        "citation_hit_rate": _share(cited, lambda i: i["output"]["citation_hit"] is True),
        "mean_input_tokens": _mean([i["output"]["usage"]["input_tokens"] for i in ok]),
        "mean_output_tokens": _mean([i["output"]["usage"]["output_tokens"] for i in ok]),
        "mean_latency_s": _mean([i["output"]["latency_s"] for i in ok]),
    }


def group_by(items: list[dict], keys: tuple[str, ...], metric_fn: Callable[[list], dict]
             ) -> dict:
    """Overall metrics plus one breakdown per eval column in `keys` (read from item["row"])."""
    result = {"overall": metric_fn(items)}
    for key in keys:
        groups: dict[str, list] = defaultdict(list)
        for item in items:
            groups[item["row"][key] or "(empty)"].append(item)
        result[f"by_{key}"] = {name: metric_fn(group) for name, group in sorted(groups.items())}
    return result
