"""Column profile tool (docs/contracts.md section 11).

A minimal profiler built in task 9 so agents (P1 condition 4, P2 #14/#15) have real profiles
now. Jack's Bronze profiler (#7) can reuse it or replace it behind the same interface.

NHANES special codes (refused / don't know) are taken from the column's **codebook record** in
the corpus, not guessed from the values: 7 can be a real value in one variable and "Refused"
in another. Codes listed there are reported in `special_codes` and left out of `n_distinct`,
`top_values`, `min` and `max`. MIMIC and OMOP columns have no such codes.
"""

from __future__ import annotations

import re

import duckdb

from medrag import db
from medrag.verify.sql_tool import json_safe, lock_down

NHANES_SCHEMA = "nhanes_2017_2018"
SPECIAL_LABEL = re.compile(r"refused|don'?t know", re.IGNORECASE)
NUMERIC_TYPES = re.compile(r"^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|UTINYINT|USMALLINT|"
                           r"UINTEGER|UBIGINT|FLOAT|REAL|DOUBLE|DECIMAL.*|NUMERIC.*)$")
TEMPORAL_TYPES = re.compile(r"^(DATE|TIME.*|TIMESTAMP.*)$")


def codebook_special_codes(records: list[dict], table: str, column: str) -> dict[float, str]:
    """Return {code: label} for refused / don't-know rows in a column's NHANES codebook.

    Reads code lines of the form `code | description | count | skip to` from the
    `nhanes_variable` record whose component is `table` and whose section is `column`.
    """
    for record in records:
        if (record["kind"] == "nhanes_variable"
                and record["metadata"].get("component", "").lower() == table.lower()
                and record["section"].lower() == column.lower()):
            codes = {}
            for line in record["text"].split("\n"):
                cells = [cell.strip() for cell in line.split("|")]
                if len(cells) >= 2 and SPECIAL_LABEL.search(cells[1]):
                    try:
                        codes[float(cells[0])] = cells[1]
                    except ValueError:
                        continue        # e.g. a range like "7 to 9"
            return codes
    return {}


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def column_type(con: duckdb.DuckDBPyConnection, schema: str, table: str,
                column: str) -> tuple[str, str, str, str]:
    """Return (schema, table, column, data_type) with the database's spelling.

    Raises ValueError if the column doesn't exist, so only known identifiers reach SQL.
    """
    row = con.execute(
        "SELECT table_schema, table_name, column_name, data_type "
        "FROM information_schema.columns WHERE lower(table_schema) = lower(?) "
        "AND lower(table_name) = lower(?) AND lower(column_name) = lower(?)",
        [schema, table, column]).fetchone()
    if row is None:
        raise ValueError(f"column {schema}.{table}.{column} not found")
    return row


def profile_column(schema: str, table: str, column: str, top_k: int,
                   con: duckdb.DuckDBPyConnection | None = None,
                   codebook: list[dict] | None = None) -> dict:
    """Return the contract-11 profile of one column.

    `codebook` is the list of corpus records used to find NHANES special codes (pass the
    loaded corpus); `con` is for tests, otherwise the project database is opened read-only.
    """
    own = con is None
    if own:
        con = db.connect()
        lock_down(con)
    try:
        schema, table, column, dtype = column_type(con, schema, table, column)
        special = {}
        if schema.lower() == NHANES_SCHEMA and codebook:
            special = codebook_special_codes(codebook, table, column)
        source = f"{_quote(schema)}.{_quote(table)}"
        col = _quote(column)
        n_rows, n_null = con.execute(
            f"SELECT count(*), count(*) - count({col}) FROM {source}").fetchone()
        counts = con.execute(
            f"SELECT {col} AS value, count(*) AS n FROM {source} WHERE {col} IS NOT NULL "
            f"GROUP BY 1 ORDER BY n DESC, value").fetchall()
    finally:
        if own:
            con.close()
    special_found = [{"value": json_safe(value), "label": special[float(value)], "count": n}
                     for value, n in counts if _is_special(value, special)]
    regular = [(value, n) for value, n in counts if not _is_special(value, special)]
    ordered = NUMERIC_TYPES.match(dtype) or TEMPORAL_TYPES.match(dtype)
    values = [value for value, _ in regular]
    return {
        "dtype": dtype, "n_rows": n_rows, "n_null": n_null, "n_distinct": len(regular),
        "top_values": [{"value": json_safe(v), "count": n} for v, n in regular[:top_k]],
        "min": json_safe(min(values)) if ordered and values else None,
        "max": json_safe(max(values)) if ordered and values else None,
        "special_codes": special_found,
    }


def _is_special(value, special: dict[float, str]) -> bool:
    if not special or isinstance(value, bool):
        return False
    try:
        return float(value) in special
    except (TypeError, ValueError):
        return False
