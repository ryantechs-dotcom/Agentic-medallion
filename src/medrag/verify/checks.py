"""Condition 4 data checks: plan read-only SQL from the retrieved passages, run it, and turn
the results into extra passages for the answer call (D23).

The pipeline is fixed, not an open agent loop: one planning call returns up to
`verify.max_queries` SELECT statements, `sql_tool.run_sql` runs each once, and each result
becomes a passage `[sql:N]` that the frozen answer prompt can cite like any other. To write
valid SQL the planner sees the tables (with columns) behind the retrieved passages, in every
schema that has them, so a v1.0 vs v2.2 difference is visible in the hints themselves.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable

from medrag.generation.llm import Backend, build_user_message, model_settings
from medrag.verify.sql_tool import run_sql

NHANES_DOC_RE = re.compile(r"^nhanes/\d{4}-\d{4}_(\w+)\.htm$")
MIMIC_DOC_RE = re.compile(r"^mimic/(?:hosp|icu)__(\w+)\.md$")
OMOP_DOCS = ("omop/OMOP_CDMv5.3_Field_Level.csv", "omop/OMOP_CDMv5.3_Table_Level.csv")
NHANES_SCHEMA = "nhanes_2017_2018"
OMOP_SCHEMA = "omop_demo_v0_9"
NO_TABLES = ("(no table matches the passages; query information_schema.columns if a check "
             "is still useful)")


def plan_schema(max_queries: int) -> dict:
    """JSON schema of the planning call: up to `max_queries` SQL strings (may be empty)."""
    return {
        "type": "object",
        "properties": {"queries": {"type": "array", "items": {"type": "string"},
                                   "maxItems": max_queries}},
        "required": ["queries"],
        "additionalProperties": False,
    }


def load_catalog(con) -> dict[tuple[str, str], list[str]]:
    """{(schema, table): [columns in order]} for every table in the database."""
    rows = con.execute("SELECT table_schema, table_name, column_name "
                       "FROM information_schema.columns "
                       "ORDER BY table_schema, table_name, ordinal_position").fetchall()
    catalog: dict[tuple[str, str], list[str]] = {}
    for schema, table, column in rows:
        catalog.setdefault((schema, table), []).append(column)
    return catalog


def doc_tables(doc: str, section: str, catalog: dict) -> list[tuple[str, str]]:
    """Database tables a passage's document describes (empty for narrative-only docs)."""
    match = NHANES_DOC_RE.match(doc)
    if match:
        key = (NHANES_SCHEMA, match.group(1).lower())
        return [key] if key in catalog else []
    match = MIMIC_DOC_RE.match(doc)
    if match:
        name = match.group(1).lower()
        return sorted(key for key in catalog
                      if key[0].startswith("mimic_demo_") and key[1] == name)
    if doc in OMOP_DOCS and section:
        key = (OMOP_SCHEMA, section.split(".", 1)[0].lower())
        return [key] if key in catalog else []
    return []


def table_hints(passages: list[dict], catalog: dict, max_columns: int) -> str:
    """`schema.table: col, col, ...` lines for the tables behind the passages, deduplicated."""
    keys: list[tuple[str, str]] = []
    for passage in passages:
        for key in doc_tables(passage["doc"], passage["section"], catalog):
            if key not in keys:
                keys.append(key)
    lines = []
    for schema, table in keys:
        columns = catalog[(schema, table)]
        more = f", ... ({len(columns) - max_columns} more)" if len(columns) > max_columns else ""
        lines.append(f"{schema}.{table}: {', '.join(columns[:max_columns])}{more}")
    return "\n".join(lines) or NO_TABLES


def plan_message(question: str, passages: list[dict], hints: str) -> str:
    """User turn of the planning call: the answer call's message plus the table hints."""
    return (f"{build_user_message(question, passages)}\n\n"
            f"Tables behind these passages (schema.table: columns):\n{hints}")


def check_plan(data: object, max_queries: int) -> str | None:
    """Return an error message if `data` is not a valid plan, else None."""
    if not isinstance(data, dict) or not isinstance(data.get("queries"), list):
        return "plan.queries is not a list"
    if not all(isinstance(q, str) for q in data["queries"]):
        return "plan.queries holds a non-string"
    if len(data["queries"]) > max_queries:
        return f"plan has {len(data['queries'])} queries, more than {max_queries}"
    return None


def plan_queries(question: str, passages: list[dict], hints: str, config: dict, prompt: dict,
                 backend: Backend) -> tuple[list[str], dict]:
    """(queries, completion) from one planning call; queries is empty on error."""
    limit = config["verify"]["max_queries"]
    result = backend(prompt["text"], plan_message(question, passages, hints),
                     plan_schema(limit), model_settings(config))
    error = result["error"] or check_plan(result["data"], limit)
    result = {**result, "error": error}
    return ([] if error else [q.strip() for q in result["data"]["queries"] if q.strip()],
            result)


def format_result(result: dict) -> str:
    """A run_sql result as text: header row, then one row per line."""
    if result["error"]:
        return f"Error: {result['error']}"
    lines = [" | ".join(result["columns"])]
    lines += [" | ".join(str(v) for v in row) for row in result["rows"]]
    if result["truncated"]:
        lines.append("(more rows not shown)")
    return "\n".join(lines) if result["rows"] else f"{lines[0]}\n(0 rows)"


def summary(result: dict) -> str:
    """One-line `output_summary` for tool_calls."""
    if result["error"]:
        return f"error: {result['error'][:200]}"
    more = "+" if result["truncated"] else ""
    return f"{len(result['rows'])}{more} rows x {len(result['columns'])} columns"


def run_checks(queries: list[str], config: dict,
               sql: Callable[[str, int, float], dict] = run_sql,
               clock: Callable[[], float] | None = None) -> tuple[list[dict], list[dict]]:
    """(passages, tool_calls) after running each query once with the configured limits."""
    clock = clock or time.perf_counter
    passages, calls = [], []
    for i, query in enumerate(queries, 1):
        start = clock()
        result = sql(query, config["verify"]["max_rows"], config["verify"]["timeout_s"])
        calls.append({"tool": "run_sql", "input": {"sql": query},
                      "output_summary": summary(result),
                      "latency_s": round(clock() - start, 3)})
        passages.append({"id": f"sql:{i}", "doc": "sql", "section": "",
                         "text": ("Data check (read-only SQL on the dataset snapshot)\n"
                                  f"Query: {query}\nResult:\n{format_result(result)}")})
    return passages, calls
