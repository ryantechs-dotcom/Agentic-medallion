"""P2 agent tools: Ryan's shared tools (medrag.tools) behind a source-only guard.

The OMOP demo (`omop_demo_v0_9`) sits in the same database as the source, and it is the answer
key the ground truth was checked against. In a real Silver build the target is empty, so an
agent that reads it would be grading itself. `guard_problem` rejects, before anything runs:
- `run_sql` text that mentions a blocked term (`p2.blocked_sql_terms`: the OMOP, v2.2 and
  NHANES schemas, and `query_table` / `query(`, which take a table name as a string);
- `profile_column` on a schema outside `p2.source_schemas`.
File access is already off in the SQL tool (medrag.verify.sql_tool). The guard is a substring
check, written against honest mistakes rather than an adversary, so every SQL call is also
logged in the run and `scoring.leak_audit` counts blocked attempts.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

ROLE_TOOLS = {
    "single": ("search_docs", "profile_column", "run_sql"),
    "retriever": ("search_docs", "profile_column"),
    "proposer": (),
    "verifier": ("run_sql", "profile_column"),
}

ToolCaller = Callable[[str, dict], dict]


def guard_problem(name: str, args: dict, p2: dict) -> str | None:
    """Return why a tool call is refused, or None if it may run."""
    if name == "run_sql":
        text = str(args.get("sql", "")).lower()
        hits = [term for term in p2["blocked_sql_terms"] if term.lower() in text]
        if hits:
            return (f"rejected: only the source schemas {p2['source_schemas']} can be queried "
                    f"(found {hits})")
    if name == "profile_column" and args.get("schema") not in p2["source_schemas"]:
        return f"rejected: profile_column works on {p2['source_schemas']} only"
    return None


def error_result(name: str, message: str) -> dict:
    """A tool result carrying only an error, in the shape of that tool's normal output."""
    if name == "run_sql":
        return {"columns": [], "rows": [], "truncated": False, "error": message}
    if name == "search_docs":
        return {"chunks": [], "error": message}
    return {"error": message}


def make_caller(call: Callable[[str, dict], dict], p2: dict) -> ToolCaller:
    """Wrap a raw tool runner (`medrag.tools.call_tool` bound to a context) with the guard.
    Tool exceptions become error results, because the model reads them and tries again."""
    def caller(name: str, args: dict) -> dict:
        problem = guard_problem(name, args, p2)
        if problem:
            return error_result(name, problem)
        try:
            return call(name, args)
        except Exception as err:   # bad arguments from the model, missing column, ...
            return error_result(name, f"{type(err).__name__}: {err}")
    return caller


def summarize(output: dict, max_chars: int) -> str:
    """A tool result as JSON text for the next prompt, cut to `max_chars`."""
    text = json.dumps(output, sort_keys=True, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f' ... [cut: {len(text) - max_chars} more characters]'


def timed(caller: ToolCaller, name: str, args: dict) -> tuple[dict, float]:
    start = time.perf_counter()
    output = caller(name, args)
    return output, round(time.perf_counter() - start, 3)
