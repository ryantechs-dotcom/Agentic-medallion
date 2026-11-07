"""Shared record formats and their validation (see docs/contracts.md).

Each format is a dict of required field -> allowed type(s). `validate` checks one record at a
layer boundary and fails loudly; `validate_all` also checks that ids are unique.
"""

from __future__ import annotations

from collections.abc import Iterable

CORPUS_VERSION = "corpus_v1"

SOURCES = ("nhanes", "mimic", "omop")
CORPUS_KINDS = ("nhanes_variable", "nhanes_narrative", "mimic_section", "omop_table",
                "omop_field")
CHUNK_STRATEGIES = ("structure", "fixed")

REQUIRED: dict[str, dict[str, type | tuple[type, ...]]] = {
    "corpus_record": {
        "id": str, "doc": str, "section": str, "source": str, "kind": str, "title": str,
        "text": str, "order": int, "metadata": dict,
    },
    "chunk": {
        "chunk_id": str, "record_id": str, "doc": str, "section": str, "source": str,
        "strategy": str, "text": str, "metadata": dict,
    },
    "retrieved_chunk": {
        "chunk_id": str, "doc": str, "section": str, "text": str, "score": (int, float),
    },
    "run_output": {
        "qid": str, "answer": (str, type(None)), "citations": list, "retrieved": list,
        "tool_calls": list, "usage": dict, "latency_s": (int, float), "error": (str, type(None)),
    },
}

ID_FIELD = {"corpus_record": "id", "chunk": "chunk_id", "run_output": "qid"}

ALLOWED_VALUES = {
    "corpus_record": {"source": SOURCES, "kind": CORPUS_KINDS},
    "chunk": {"source": SOURCES, "strategy": CHUNK_STRATEGIES},
}


def validate(record: dict, kind: str) -> dict:
    """Return `record` unchanged, or raise ValueError naming the first bad field."""
    if kind not in REQUIRED:
        raise ValueError(f"unknown format {kind!r}; expected one of {sorted(REQUIRED)}")
    if not isinstance(record, dict):
        raise ValueError(f"{kind}: expected a dict, got {type(record).__name__}")
    label = record.get(ID_FIELD.get(kind, ""), "?")
    for field, types in REQUIRED[kind].items():
        if field not in record:
            raise ValueError(f"{kind} {label}: missing field {field!r}")
        value = record[field]
        allowed_types = types if isinstance(types, tuple) else (types,)
        # bool is a subclass of int; don't accept True/False where a number is expected
        is_stray_bool = isinstance(value, bool) and bool not in allowed_types
        if not isinstance(value, allowed_types) or is_stray_bool:
            raise ValueError(f"{kind} {label}: field {field!r} has type "
                             f"{type(value).__name__}")
    for field, allowed in ALLOWED_VALUES.get(kind, {}).items():
        if record[field] not in allowed:
            raise ValueError(f"{kind} {label}: field {field!r} = {record[field]!r} "
                             f"not in {allowed}")
    return record


def validate_all(records: Iterable[dict], kind: str) -> list[dict]:
    """Validate every record and check that ids are unique; return them as a list."""
    records = [validate(record, kind) for record in records]
    id_field = ID_FIELD.get(kind)
    if id_field:
        seen: set[str] = set()
        for record in records:
            if record[id_field] in seen:
                raise ValueError(f"{kind}: duplicate {id_field} {record[id_field]!r}")
            seen.add(record[id_field])
    return records


def matches_gold(record: dict, gold_doc: str, gold_section: str) -> bool:
    """True if `record` supports a gold (doc, section) under the rule in docs/contracts.md."""
    if not gold_doc or record["doc"] != gold_doc:
        return False
    needle = _fold(gold_section)
    if not needle:
        return True
    return needle in _fold(record["section"]) or needle in _fold(record["text"])


def _fold(text: str) -> str:
    """Lowercase with whitespace collapsed, for case- and spacing-insensitive matching."""
    return " ".join(text.lower().split())
