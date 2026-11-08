"""Agent tools shared by P1 condition 4 and the P2 agents.

`TOOLS` holds one JSON schema per tool (`name`, `description`, `input_schema`, the shape the
Anthropic Messages API expects), and `call_tool` runs a tool call by name. Formats:
docs/contracts.md sections 4 (search_docs), 5 (run_sql) and 11 (profile_column).
"""

from __future__ import annotations

from dataclasses import dataclass

from medrag.retrieval.base import Retriever, search_docs
from medrag.verify.profile import profile_column
from medrag.verify.sql_tool import run_sql

TOOLS = [
    {
        "name": "search_docs",
        "description": (
            "Search the documentation corpus (NHANES 2017-2018 codebooks, MIMIC-IV docs, OMOP "
            "CDM 5.3 spec). Returns the best-matching chunks with doc, section and score; cite "
            "doc and section for every claim you take from them."),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "what to look for"},
                "k": {"type": "integer", "minimum": 1, "maximum": 20,
                      "description": "number of chunks (default from config)"},
                "filters": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "enum": ["nhanes", "mimic", "omop"]},
                        "table": {"type": "string",
                                  "description": "NHANES component (e.g. DIQ_J), MIMIC page "
                                                 "or OMOP table"},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "run_sql",
        "description": (
            "Run one read-only SELECT (or WITH ... SELECT) against the DuckDB snapshot. Schemas: "
            "mimic_demo_v1_0_{core,hosp,icu}, mimic_demo_v2_2_{hosp,icu}, omop_demo_v0_9, "
            "nhanes_2017_2018. Returns columns, capped rows, a truncated flag and any error."),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "a single SELECT statement"},
                "max_rows": {"type": "integer", "minimum": 1,
                             "description": "row cap (cannot exceed the configured maximum)"},
            },
            "required": ["sql"],
        },
    },
    {
        "name": "profile_column",
        "description": (
            "Profile one column: data type, row and null counts, distinct values, most frequent "
            "values, min/max, and NHANES refused/don't-know codes (reported separately, never "
            "counted as values)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "schema": {"type": "string"},
                "table": {"type": "string"},
                "column": {"type": "string"},
            },
            "required": ["schema", "table", "column"],
        },
    },
]

TOOL_NAMES = tuple(tool["name"] for tool in TOOLS)


@dataclass
class ToolContext:
    """What the tools need at run time: a retriever, the corpus records and the config."""

    retriever: Retriever
    records: list[dict]
    config: dict


def call_tool(name: str, args: dict, context: ToolContext) -> dict:
    """Run tool `name` with the model's `args`; limits always come from config."""
    config = context.config
    if name == "search_docs":
        return search_docs(context.retriever, args["query"],
                           int(args.get("k") or config["retrieval"]["k"]), args.get("filters"))
    if name == "run_sql":
        cap = config["verify"]["max_rows"]
        max_rows = min(int(args.get("max_rows") or cap), cap)
        return run_sql(args["sql"], max_rows, config["verify"]["timeout_s"])
    if name == "profile_column":
        return profile_column(args["schema"], args["table"], args["column"],
                              config["profile"]["top_k"], codebook=context.records)
    raise ValueError(f"unknown tool {name!r}; expected one of {TOOL_NAMES}")
