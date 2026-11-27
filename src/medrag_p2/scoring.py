"""Score P2 specs against the ground truth (docs/contracts.md section 7, D16).

Unit: a (source table, source column, target table, target field) pair; `not_mapped` is the
pair with no target. Per run, overall and per table:
- precision / recall / F1 over pairs, strict (exact gold pair) and lenient (a predicted
  target listed in the column's `acceptable_alternatives` also counts; recall then also credits
  the column's primary row when an acceptable alternative was proposed instead);
- top-1 and top-k accuracy: the column's primary gold target is the agent's most confident
  spec (top-1) or among its k most confident (`p2.top_k`), strict and lenient;
- mapping_type accuracy on strictly matched pairs;
- evidence validity: share of specs with at least one evidence item, all of whose doc
  citations exist in the corpus (doc + section) and whose SQL re-runs without error;
- multi only, verifier catch rate: of the proposer's first-round specs that are wrong
  (lenient), the share the verifier rejected or sent to a human; false alarm rate: of the
  right ones, the share it rejected or sent to a human;
- cost: model calls, tool calls, tokens, latency, CLI cost estimate; blocked tool calls.
Cleaning-rule correctness needs a judge and is scored separately (not here).
"""

from __future__ import annotations

from collections.abc import Callable

Pair = tuple[str, str, str | None, str | None]
BLOCKED_PREFIXES = ("rejected: only the source schemas", "rejected: profile_column works on")


def norm(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return value or None


def gold_index(rows: list[dict]) -> dict:
    """Per (table, column): gold pairs, primary targets and acceptable alternatives."""
    index: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["source_table"], row["source_column"])
        entry = index.setdefault(key, {"pairs": set(), "primary": set(), "alternatives": set(),
                                       "split": row["split"]})
        target = (norm(row["target_table"]), norm(row["target_field"]))
        entry["pairs"].add(target)
        if row["is_primary"] == "Y":
            entry["primary"].add(target)
        for alt in filter(None, (a.strip() for a in row["acceptable_alternatives"].split(";"))):
            table, _, field = alt.partition(".")
            entry["alternatives"].add((norm(table), norm(field)))
    return index


def target_of(spec: dict) -> tuple[str | None, str | None]:
    return norm(spec.get("target_table")), norm(spec.get("target_field"))


def ratio(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None:
        return None
    return round(2 * p * r / (p + r), 4) if p + r else 0.0


def pair_metrics(specs: list[dict], index: dict, columns: set[tuple[str, str]],
                 top_k: int) -> dict:
    """Pair-level and top-k metrics for the specs of `columns` (keys into `index`)."""
    predicted: dict[tuple[str, str], list[dict]] = {}
    for spec in specs:
        key = (spec["source_table"], spec["source_column"])
        if key in columns:
            predicted.setdefault(key, []).append(spec)
    n_pred = n_strict = n_lenient = n_type = 0
    n_gold = recalled_strict = recalled_lenient = 0
    top1 = {"strict": 0, "lenient": 0}
    topk = {"strict": 0, "lenient": 0}
    for key in columns:
        gold = index[key]
        own = predicted.get(key, [])
        targets = {target_of(s) for s in own}
        for spec in own:
            n_pred += 1
            target = target_of(spec)
            if target in gold["pairs"]:
                n_strict += 1
                n_lenient += 1
                gold_types = gold.get("types", {}).get(target)
                n_type += int(gold_types is None or spec["mapping_type"] in gold_types)
            elif target in gold["alternatives"]:
                n_lenient += 1
        n_gold += len(gold["pairs"])
        recalled_strict += len(gold["pairs"] & targets)
        alt_hit = bool(gold["alternatives"] & targets)
        recalled_lenient += len(gold["pairs"] & targets) + int(
            alt_hit and not (gold["primary"] & targets))
        ranked = [target_of(s) for s in sorted(own, key=lambda s: -s["confidence"])]
        for name, ok in (("strict", gold["primary"]),
                         ("lenient", gold["primary"] | gold["alternatives"])):
            top1[name] += int(bool(ranked) and ranked[0] in ok)
            topk[name] += int(bool(set(ranked[:top_k]) & ok))
    n_cols = len(columns)
    p_s, r_s = ratio(n_strict, n_pred), ratio(recalled_strict, n_gold)
    p_l, r_l = ratio(n_lenient, n_pred), ratio(recalled_lenient, n_gold)
    return {
        "n_columns": n_cols, "n_specs": n_pred, "n_gold_pairs": n_gold,
        "precision": p_s, "recall": r_s, "f1": f1(p_s, r_s),
        "precision_lenient": p_l, "recall_lenient": r_l, "f1_lenient": f1(p_l, r_l),
        "top1_accuracy": ratio(top1["strict"], n_cols),
        "top1_accuracy_lenient": ratio(top1["lenient"], n_cols),
        f"top{top_k}_accuracy": ratio(topk["strict"], n_cols),
        f"top{top_k}_accuracy_lenient": ratio(topk["lenient"], n_cols),
        "mapping_type_accuracy": ratio(n_type, n_strict),
        "columns_without_spec": sorted(f"{t}.{c}" for t, c in columns if (t, c) not in predicted),
    }


def add_types(index: dict, rows: list[dict]) -> None:
    """Record each gold pair's mapping_type(s) for mapping_type accuracy."""
    for row in rows:
        entry = index[(row["source_table"], row["source_column"])]
        target = (norm(row["target_table"]), norm(row["target_field"]))
        entry.setdefault("types", {}).setdefault(target, set()).add(row["mapping_type"])


def is_right(spec: dict, index: dict) -> bool:
    gold = index.get((spec["source_table"], spec["source_column"]))
    return bool(gold) and target_of(spec) in gold["pairs"] | gold["alternatives"]


def evidence_valid(spec: dict, doc_sections: set[tuple[str, str]],
                   sql_ok: Callable[[str], bool]) -> bool:
    """At least one evidence item; doc citations exist; SQL evidence re-runs cleanly."""
    items = spec.get("evidence") or []
    if not items:
        return False
    for item in items:
        if "doc" in item and (item["doc"], item.get("section", "")) not in doc_sections:
            return False
        if "sql" in item and not sql_ok(item["sql"]):
            return False
    return True


def catch_metrics(outputs: list[dict], index: dict) -> dict:
    """Verifier catch rate and false alarm rate on the proposer's first-round specs."""
    wrong = caught = right = alarmed = 0
    for out in outputs:
        first = {v["spec_id"]: v["status"] for v in out.get("verdicts", []) if v["round"] == 1}
        for spec in out.get("initial_specs", []):
            flagged = first.get(spec["spec_id"]) in ("rejected", "needs_human")
            if is_right(spec, index):
                right += 1
                alarmed += int(flagged)
            else:
                wrong += 1
                caught += int(flagged)
    return {"verifier_catch_rate": ratio(caught, wrong), "n_wrong_initial_specs": wrong,
            "verifier_false_alarm_rate": ratio(alarmed, right), "n_right_initial_specs": right}


def cost_metrics(outputs: list[dict]) -> dict:
    calls = [c for o in outputs for c in o.get("tool_calls", [])]
    return {
        "model_calls": sum(o.get("model_calls", 0) for o in outputs),
        "tool_calls": len(calls),
        "tool_calls_by_tool": {t: sum(c["tool"] == t for c in calls)
                               for t in sorted({c["tool"] for c in calls})},
        "blocked_tool_calls": sum(str(c.get("error") or "").startswith(BLOCKED_PREFIXES)
                                  for c in calls),
        "input_tokens": sum(o.get("usage", {}).get("input_tokens", 0) for o in outputs),
        "output_tokens": sum(o.get("usage", {}).get("output_tokens", 0) for o in outputs),
        "latency_s": round(sum(o.get("latency_s", 0) for o in outputs), 3),
        "cost_usd_estimate": round(sum(o.get("cost_usd", 0) for o in outputs), 4),
        "tables_with_error": sorted(o["qid"] for o in outputs if o.get("error")),
        "tables_with_warning": sorted(o["qid"] for o in outputs if o.get("warnings")),
        "needs_human_specs": sum(s["status"] == "needs_human"
                                 for o in outputs for s in o.get("specs", [])),
        "dropped_specs": sum(o.get("n_dropped_specs", 0) for o in outputs),
    }


def score_run(outputs: list[dict], gt_rows: list[dict], doc_sections: set[tuple[str, str]],
              sql_ok: Callable[[str], bool], top_k: int) -> dict:
    """metrics.json content for one run: overall (tables in the run) and per table."""
    index = gold_index(gt_rows)
    add_types(index, gt_rows)
    tables = {o["table"] for o in outputs}
    specs = [s for o in outputs for s in o.get("specs", [])]
    columns = {k for k in index if k[0] in tables}
    metrics = {"overall": pair_metrics(specs, index, columns, top_k)}
    metrics["by_table"] = {t: pair_metrics(specs, index, {k for k in columns if k[0] == t},
                                           top_k) for t in sorted(tables)}
    metrics["evidence_valid_share"] = ratio(
        sum(evidence_valid(s, doc_sections, sql_ok) for s in specs), len(specs))
    if any(o.get("architecture") == "multi" for o in outputs):
        metrics.update(catch_metrics(outputs, index))
    metrics["cost"] = cost_metrics(outputs)
    return metrics
