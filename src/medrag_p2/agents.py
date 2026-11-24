"""Single-agent (#14) and multi-agent (#15) schema mapping over one source table.

Both architectures share one step loop (`run_agent`), one base prompt, the same model settings
and the same tools, so a difference in results comes from the architecture:

    single:  agent(search_docs, profile_column, run_sql)                    -> specs
    multi:   retriever(search_docs, profile_column) -> notes
             proposer(no tools)                     -> specs
             verifier(run_sql, profile_column)      -> verdicts
             rejected specs go back to the proposer (p2.multi.revision_rounds), then are
             verified again; still rejected at the end -> status needs_human (HITL, #19)

The model backend (medrag.generation.llm) makes one stateless call with no tools of its own, so
the loop is ours: each call returns one JSON step (call a tool, or finish), we run the tool and
send the whole transcript back in the next call. Specs leave as `p2_spec` records
(docs/contracts.md section 7) that join to the ground truth on (table, column, target).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from medrag import contracts
from medrag_p2.tools import ROLE_TOOLS, ToolCaller, summarize, timed

Backend = Callable[[str, str, dict, dict], dict]

EVIDENCE_ITEM = {
    "type": "object",
    "properties": {"doc": {"type": "string"}, "section": {"type": "string"},
                   "sql": {"type": "string"}, "result": {"type": "string"}},
    "required": ["doc", "section", "sql", "result"],
    "additionalProperties": False,
}
SPEC_ITEM = {
    "type": "object",
    "properties": {
        "source_column": {"type": "string"},
        "target_table": {"type": ["string", "null"]},
        "target_field": {"type": ["string", "null"]},
        "mapping_type": {"type": "string", "enum": list(contracts.P2_MAPPING_TYPES)},
        "target_type": {"type": ["string", "null"]},
        "transform_rule": {"type": "string"},
        "evidence": {"type": "array", "items": EVIDENCE_ITEM},
        "confidence": {"type": "number"},
    },
    "required": ["source_column", "target_table", "target_field", "mapping_type",
                 "target_type", "transform_rule", "evidence", "confidence"],
    "additionalProperties": False,
}
NOTE_ITEM = {
    "type": "object",
    "properties": {"source_column": {"type": "string"}, "findings": {"type": "string"},
                   "evidence": {"type": "array", "items": EVIDENCE_ITEM}},
    "required": ["source_column", "findings", "evidence"],
    "additionalProperties": False,
}
VERDICT_ITEM = {
    "type": "object",
    "properties": {"spec_id": {"type": "string"},
                   "status": {"type": "string", "enum": ["verified", "rejected", "needs_human"]},
                   "reason": {"type": "string"},
                   "evidence": {"type": "array", "items": EVIDENCE_ITEM}},
    "required": ["spec_id", "status", "reason", "evidence"],
    "additionalProperties": False,
}
OUTPUT_KEY = {"single": "specs", "proposer": "specs", "retriever": "notes",
              "verifier": "verdicts"}
OUTPUT_ITEM = {"specs": SPEC_ITEM, "notes": NOTE_ITEM, "verdicts": VERDICT_ITEM}


def step_schema(role: str) -> dict:
    """JSON schema for one step of `role`: a tool call, or finish with the role's output."""
    tools = list(ROLE_TOOLS[role])
    key = OUTPUT_KEY[role]
    items = {"type": "array", "items": OUTPUT_ITEM[key]}
    output = {"type": "object", "properties": {key: items},
              "required": [key], "additionalProperties": False}
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["tool", "finish"] if tools else ["finish"]},
            "tool": {"type": "string", "enum": tools + [""]},
            "tool_input_json": {"type": "string"},
            "output": output,
        },
        "required": ["action", "tool", "tool_input_json", "output"],
        "additionalProperties": False,
    }


def check_step(data: object, role: str) -> str | None:
    """Return why a step is unusable, or None."""
    if not isinstance(data, dict) or data.get("action") not in ("tool", "finish"):
        return "step must be a JSON object with action 'tool' or 'finish'"
    if data["action"] == "tool" and data.get("tool") not in ROLE_TOOLS[role]:
        return f"tool must be one of {list(ROLE_TOOLS[role])}"
    if data["action"] == "finish":
        output = data.get("output")
        if not isinstance(output, dict) or not isinstance(output.get(OUTPUT_KEY[role]), list):
            return f"finish needs output.{OUTPUT_KEY[role]} as a list"
    return None


def render_user(task: str, steps: list[dict], steps_left: int) -> str:
    """The user turn: the task, then every tool call so far with its (cut) result."""
    parts = [task]
    if steps:
        parts.append("Tool calls so far:")
        for i, step in enumerate(steps, 1):
            parts.append(f"[{i}] {step['tool']} {json.dumps(step['input'], sort_keys=True)}\n"
                         f"-> {step['result_text']}")
    parts.append(f"Steps left (including this one): {steps_left}." +
                 (" This is the last step: finish now." if steps_left == 1 else ""))
    return "\n\n".join(parts)


def add_usage(total: dict, usage: dict) -> None:
    for key in ("input_tokens", "output_tokens"):
        total[key] = total.get(key, 0) + int(usage.get(key) or 0)


def run_agent(role: str, system: str, task: str, backend: Backend, settings: dict,
              caller: ToolCaller, max_steps: int, max_chars: int) -> dict:
    """Run one agent until it finishes or the step budget runs out.

    Returns {output, tool_calls, usage, model_calls, cost_usd, latency_s, error}. A malformed
    step or tool input is fed back to the model as an error and uses up a step; a backend
    failure (timeout, refusal, CLI error) stops the agent with `error` set.
    """
    start = time.perf_counter()
    steps: list[dict] = []
    usage: dict = {"input_tokens": 0, "output_tokens": 0}
    out = {"output": None, "tool_calls": [], "usage": usage, "model_calls": 0,
           "cost_usd": 0.0, "latency_s": 0.0, "error": None}
    schema = step_schema(role)
    for step in range(max_steps):
        result = backend(system, render_user(task, steps, max_steps - step), schema, settings)
        out["model_calls"] += 1
        add_usage(usage, result.get("usage") or {})
        out["cost_usd"] += result.get("cost_usd") or 0.0
        if result.get("error"):
            out["error"] = f"{role}: {result['error']}"
            break
        data = result.get("data")
        problem = check_step(data, role)
        if problem is None and data["action"] == "finish":
            out["output"] = data["output"]
            break
        if problem is None:
            try:
                args = json.loads(data["tool_input_json"] or "{}")
                if not isinstance(args, dict):
                    raise ValueError("not a JSON object")
            except ValueError as err:
                problem = f"tool_input_json is not a JSON object: {err}"
        if problem:
            steps.append({"tool": "(invalid step)", "input": {}, "result_text": problem})
            continue
        output, latency = timed(caller, data["tool"], args)
        steps.append({"tool": data["tool"], "input": args,
                      "result_text": summarize(output, max_chars)})
        out["tool_calls"].append({"tool": data["tool"], "input": args, "role": role,
                                  "output_summary": summarize(output, 300),
                                  "error": output.get("error"), "latency_s": latency,
                                  "retrieved": [{k: c.get(k) for k in
                                                 ("chunk_id", "doc", "section", "score")}
                                                for c in output.get("chunks", [])]})
    else:
        out["error"] = f"{role}: step budget ({max_steps}) ran out before finish"
    out["latency_s"] = round(time.perf_counter() - start, 3)
    return out


def table_task(table: dict) -> str:
    """The task text every role starts from: the table and its columns (from the database)."""
    cols = "\n".join(f"- {c['name']} ({c['dtype']})" for c in table["columns"])
    return (f"Source table: {table['schema']}.{table['table']} "
            f"({table['n_rows']} rows)\nColumns:\n{cols}")


def clean_evidence(items: list) -> list[dict]:
    """Keep the non-empty fields of each evidence item; drop empty items."""
    kept = []
    for item in items or []:
        if isinstance(item, dict):
            entry = {k: str(v) for k, v in item.items()
                     if k in ("doc", "section", "sql", "result") and v not in ("", None)}
            if entry:
                kept.append(entry)
    return kept


def to_specs(raw: list, table: dict, status: str, agent: str) -> tuple[list[dict], int]:
    """Agent spec items -> validated `p2_spec` records; returns (specs, n_dropped).
    Items naming a column the table doesn't have, or not matching the schema, are dropped."""
    columns = {c["name"] for c in table["columns"]}
    specs, seen, dropped = [], {}, 0
    for item in raw or []:
        col = item.get("source_column") if isinstance(item, dict) else None
        if col not in columns:
            dropped += 1
            continue
        n = seen[col] = seen.get(col, 0) + 1
        target_table, target_field = item.get("target_table"), item.get("target_field")
        if item.get("mapping_type") == "not_mapped" or not (target_table and target_field):
            target_table = target_field = None
        spec = {
            "spec_id": f"{table['table']}.{col}" + (f"#{n}" if n > 1 else ""),
            "source_schema": table["schema"], "source_table": table["table"],
            "source_column": col,
            "target_table": target_table.lower() if target_table else None,
            "target_field": target_field.lower() if target_field else None,
            "mapping_type": item.get("mapping_type") if target_table else "not_mapped",
            "target_type": item.get("target_type"),
            "transform_rule": str(item.get("transform_rule") or ""),
            "evidence": clean_evidence(item.get("evidence")),
            "confidence": float(item.get("confidence") or 0.0),
            "status": status, "agent": agent,
        }
        try:
            specs.append(contracts.validate(spec, "p2_spec"))
        except ValueError:
            dropped += 1
    return specs, dropped


def merge_cost(total: dict, part: dict) -> None:
    """Add one agent's calls, usage, cost and tool calls to the table total."""
    total["model_calls"] += part["model_calls"]
    total["cost_usd"] += part["cost_usd"]
    add_usage(total["usage"], part["usage"])
    total["tool_calls"].extend(part["tool_calls"])
    if part["error"] and not total["error"]:
        total["error"] = part["error"]


def empty_result(architecture: str) -> dict:
    return {"architecture": architecture, "specs": [], "n_dropped_specs": 0,
            "tool_calls": [], "usage": {"input_tokens": 0, "output_tokens": 0},
            "model_calls": 0, "cost_usd": 0.0, "error": None}


def run_single(table: dict, prompts: dict, backend: Backend, settings: dict,
               caller: ToolCaller, p2: dict) -> dict:
    """#14: one agent with all tools maps the whole table."""
    result = empty_result("single")
    system = prompts["base"]["text"] + "\n\n" + prompts["single"]["text"]
    agent = run_agent("single", system, table_task(table), backend, settings, caller,
                      p2["single"]["max_steps"], p2["max_tool_result_chars"])
    merge_cost(result, agent)
    result["specs"], result["n_dropped_specs"] = to_specs(
        (agent["output"] or {}).get("specs"), table, "proposed", "single")
    return result


def apply_verdicts(specs: list[dict], verdicts: list, round_no: int) -> list[dict]:
    """Set each spec's status from its verdict; a spec with no verdict stays `proposed`.
    Returns the verdict log entries for this round."""
    by_id = {v.get("spec_id"): v for v in verdicts or [] if isinstance(v, dict)}
    log = []
    for spec in specs:
        verdict = by_id.get(spec["spec_id"])
        if verdict is None or spec["status"] != "proposed":
            continue
        spec["status"] = verdict["status"]
        spec["evidence"] = spec["evidence"] + clean_evidence(verdict.get("evidence"))
        log.append({"round": round_no, "spec_id": spec["spec_id"],
                    "status": verdict["status"], "reason": verdict.get("reason", ""),
                    "spec": {k: spec[k] for k in ("source_column", "target_table",
                                                  "target_field", "mapping_type")}})
    return log


def run_multi(table: dict, prompts: dict, backend: Backend, settings: dict,
              caller: ToolCaller, p2: dict) -> dict:
    """#15: retriever -> proposer -> verifier, with bounded revision of rejected specs."""
    result = empty_result("multi")
    result.update(initial_specs=[], verdicts=[], notes=[])
    multi, chars, task = p2["multi"], p2["max_tool_result_chars"], table_task(table)

    def system(role: str) -> str:
        return prompts["base"]["text"] + "\n\n" + prompts[role]["text"]

    research = run_agent("retriever", system("retriever"), task, backend, settings, caller,
                         multi["retriever_max_steps"], chars)
    merge_cost(result, research)
    result["notes"] = (research["output"] or {}).get("notes", [])
    notes_text = "Researcher notes:\n" + json.dumps(result["notes"], indent=1, sort_keys=True)

    proposal = run_agent("proposer", system("proposer"), f"{task}\n\n{notes_text}", backend,
                         settings, caller, 1, chars)
    merge_cost(result, proposal)
    specs, dropped = to_specs((proposal["output"] or {}).get("specs"), table, "proposed",
                              "multi:proposer")
    result["n_dropped_specs"] += dropped
    result["initial_specs"] = [dict(s) for s in specs]

    for round_no in range(1, multi["revision_rounds"] + 2):
        to_check = [s for s in specs if s["status"] == "proposed"]
        if not to_check or result["error"]:
            break
        check_text = "Specs to verify:\n" + json.dumps(to_check, indent=1, sort_keys=True)
        review = run_agent("verifier", system("verifier"), f"{task}\n\n{check_text}", backend,
                           settings, caller, multi["verifier_max_steps"], chars)
        merge_cost(result, review)
        result["verdicts"] += apply_verdicts(specs, (review["output"] or {}).get("verdicts"),
                                             round_no)
        rejected = [s for s in specs if s["status"] == "rejected"]
        if not rejected or round_no > multi["revision_rounds"]:
            break
        reasons = [v for v in result["verdicts"]
                   if v["round"] == round_no and v["status"] == "rejected"]
        revise_text = ("Rejected specs and the verifier's reasons (replace these columns' "
                       "specs):\n" + json.dumps(reasons, indent=1, sort_keys=True))
        revision = run_agent("proposer", system("proposer"),
                             f"{task}\n\n{notes_text}\n\n{revise_text}", backend, settings,
                             caller, 1, chars)
        merge_cost(result, revision)
        redo_cols = {s["source_column"] for s in rejected}
        new, dropped = to_specs([i for i in (revision["output"] or {}).get("specs", [])
                                 if isinstance(i, dict) and i.get("source_column") in redo_cols],
                                table, "proposed", "multi:proposer")
        result["n_dropped_specs"] += dropped
        if not new:          # no replacement written: keep the rejected specs as they are
            break
        new_cols = {s["source_column"] for s in new}
        specs = [s for s in specs if s["source_column"] not in new_cols] + new
        renumber(specs, table)
    for spec in specs:          # rejected after the last round: a person decides (#19)
        if spec["status"] == "rejected":
            spec["status"] = "needs_human"
    result["specs"] = specs
    return result


def renumber(specs: list[dict], table: dict) -> None:
    """Give spec_ids back their `<table>.<column>[#n]` order after replacements."""
    seen: dict[str, int] = {}
    for spec in specs:
        n = seen[spec["source_column"]] = seen.get(spec["source_column"], 0) + 1
        suffix = f"#{n}" if n > 1 else ""
        spec["spec_id"] = f"{table['table']}.{spec['source_column']}{suffix}"


ARCHITECTURES = {"single": run_single, "multi": run_multi}
