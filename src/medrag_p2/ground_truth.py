"""Check the Problem 2 ground truth (MIMIC-IV v1.0 -> OMOP CDM field mappings).

One row per (source column, target field) pair. A source column can feed several target fields
(is_primary marks the main one); `not_mapped` rows have no target and record columns the ETL
drops, so precision can penalize invented mappings.

Every row is checked three ways:
1. shape: required columns, allowed mapping_type, target present iff the row is mapped;
2. evidence: each `etl_evidence` ref (file[:line or start-end]) exists in the snapshot's copy of
   the OHDSI/MIMIC ETL, and for mapped rows at least one cited range mentions the source column;
3. data: `verify_sql` returns one row (n_checked, n_mismatch); it passes when n_checked > 0 and
   n_mismatch = 0. not_mapped rows may have no SQL check.

Run: python -m medrag_p2.ground_truth  (writes the review report next to the CSV)
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from medrag import db
from medrag.config import PROJECT_ROOT, data_dir

REQUIRED_COLUMNS = (
    "gt_id", "source_schema", "source_table", "source_column", "target_table",
    "target_field", "is_primary", "mapping_type", "transform_rule", "concept_ref",
    "acceptable_alternatives", "etl_evidence", "verify_sql", "split", "author",
    "reviewed_by", "notes",
)
MAPPING_TYPES = frozenset({"direct", "transform", "concept_lookup", "derived", "not_mapped"})
SPLITS = frozenset({"dev", "test"})
TARGET_SCHEMA = "omop_demo_v0_9"
DEFAULT_CSV = PROJECT_ROOT / "eval" / "p2" / "p2_ground_truth_draft.csv"
_REF = re.compile(r"^(?P<path>[^:]+?)(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?$")


def etl_root() -> Path:
    """Return the snapshot's copy of the OHDSI/MIMIC ETL repo."""
    return data_dir() / "raw" / "github" / "omop_etl" / "MIMIC-main"


def parse_refs(evidence: str) -> list[tuple[str, int | None, int | None]]:
    """Split 'a.sql:3-5; b.csv' into [(path, start, end), ...]; raise on a malformed ref."""
    refs = []
    for part in filter(None, (p.strip() for p in evidence.split(";"))):
        match = _REF.match(part)
        if not match:
            raise ValueError(f"malformed evidence ref: {part!r}")
        start = int(match["start"]) if match["start"] else None
        end = int(match["end"]) if match["end"] else start
        refs.append((match["path"], start, end))
    return refs


def shape_problems(row: dict) -> list[str]:
    """Return problems with a row's fields that need no data or files to detect."""
    problems = [f"missing column {c}" for c in REQUIRED_COLUMNS if c not in row]
    if problems:
        return problems
    mapped = row["mapping_type"] != "not_mapped"
    if row["mapping_type"] not in MAPPING_TYPES:
        problems.append(f"unknown mapping_type {row['mapping_type']!r}")
    if row["is_primary"] not in ("Y", "N"):
        problems.append("is_primary must be Y or N")
    if row["split"] not in SPLITS:
        problems.append(f"split must be one of {sorted(SPLITS)}")
    if mapped != bool(row["target_table"] and row["target_field"]):
        problems.append("target_table/target_field must be set iff the row is mapped")
    if not row["etl_evidence"].strip():
        problems.append("no etl_evidence")
    if mapped and not row["verify_sql"].strip():
        problems.append("mapped row has no verify_sql")
    try:
        parse_refs(row["etl_evidence"])
    except ValueError as err:
        problems.append(str(err))
    return problems


def evidence_problems(row: dict, root: Path) -> list[str]:
    """Check each cited file/line range exists; mapped rows must cite the source column."""
    problems, cited = [], []
    for path, start, end in parse_refs(row["etl_evidence"]):
        file = root / path
        if not file.is_file():
            problems.append(f"evidence file not found: {path}")
            continue
        lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        if start is None:
            cited.append("\n".join(lines))
        elif not 1 <= start <= end <= len(lines):
            problems.append(f"lines {start}-{end} out of range in {path} ({len(lines)} lines)")
        else:
            cited.append("\n".join(lines[start - 1:end]))
    token = re.compile(rf"\b{re.escape(row['source_column'])}\b", re.IGNORECASE)
    if row["mapping_type"] != "not_mapped" and cited and not any(map(token.search, cited)):
        problems.append(f"no cited range mentions {row['source_column']}")
    return problems


def column_problems(row: dict, con) -> list[str]:
    """Check the source column and (if mapped) target field exist in the database."""
    def exists(schema: str, table: str, column: str) -> bool:
        return con.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? AND column_name = ?",
            [schema, table, column],
        ).fetchone()[0] > 0

    problems = []
    if not exists(row["source_schema"], row["source_table"], row["source_column"]):
        problems.append("source column not in database")
    if row["target_table"] and not exists(TARGET_SCHEMA, row["target_table"],
                                          row["target_field"]):
        problems.append(f"target field not in {TARGET_SCHEMA}")
    for alt in filter(None, (a.strip() for a in row["acceptable_alternatives"].split(";"))):
        table, _, field = alt.partition(".")
        if not exists(TARGET_SCHEMA, table, field):
            problems.append(f"acceptable alternative {alt} not in {TARGET_SCHEMA}")
    return problems


def data_verdict(n_checked, n_mismatch) -> str | None:
    """Return None if a verify_sql result passes, else the reason it fails."""
    if not n_checked:
        return "verify_sql checked 0 rows (join or filter matched nothing)"
    if n_mismatch:
        return f"verify_sql found {n_mismatch} mismatches in {n_checked} rows"
    return None


def run_verify(row: dict, con) -> tuple[int | None, int | None, str | None]:
    """Run a row's verify_sql; return (n_checked, n_mismatch, problem)."""
    sql = row["verify_sql"].strip()
    if not sql:
        return None, None, None
    try:
        cur = con.execute(sql)
        names = [d[0] for d in cur.description]
        result = cur.fetchall()
    except Exception as err:  # duckdb raises many error types; report any as a failed check
        return None, None, f"verify_sql error: {err}"
    if names != ["n_checked", "n_mismatch"] or len(result) != 1:
        return None, None, "verify_sql must return one row with columns n_checked, n_mismatch"
    n_checked, n_mismatch = result[0]
    return n_checked, n_mismatch, data_verdict(n_checked, n_mismatch)


def check(rows: list[dict], con, root: Path) -> list[dict]:
    """Check every row; return one result dict per row."""
    seen, results = set(), []
    for row in rows:
        problems = shape_problems(row)
        if not problems:
            problems += evidence_problems(row, root) + column_problems(row, con)
        key = (row.get("source_table"), row.get("source_column"),
               row.get("target_table"), row.get("target_field"))
        if key in seen:
            problems.append("duplicate (source, target) pair")
        seen.add(key)
        n_checked = n_mismatch = None
        if not problems:
            n_checked, n_mismatch, problem = run_verify(row, con)
            problems += [problem] if problem else []
        results.append({"row": row, "problems": problems,
                        "n_checked": n_checked, "n_mismatch": n_mismatch})
    return results


def report(results: list[dict], csv_path: Path) -> str:
    """Render a markdown review report: failures first, then every row."""
    failed = [r for r in results if r["problems"]]
    lines = [f"# P2 ground truth check: {csv_path.name}", "",
             f"{len(results)} rows, {len(failed)} with problems.", ""]
    if failed:
        lines += ["## Problems", ""]
        lines += [f"- {r['row'].get('gt_id')}: {'; '.join(r['problems'])}" for r in failed]
        lines.append("")
    lines += ["## Rows", "",
              "| gt_id | source | target | type | primary | data check |",
              "|---|---|---|---|---|---|"]
    for r in results:
        row = r["row"]
        target = (f"{row['target_table']}.{row['target_field']}"
                  if row.get("target_table") else "(not mapped)")
        if r["problems"]:
            data = "FAIL"
        elif r["n_checked"] is None:
            data = "no SQL (not_mapped)"
        else:
            data = f"ok, {r['n_checked']} rows"
        source = f"{row.get('source_table')}.{row.get('source_column')}"
        lines.append(f"| {row.get('gt_id')} | {source} | {target} | {row.get('mapping_type')}"
                     f" | {row.get('is_primary')} | {data} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", nargs="?", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args(argv)
    with args.csv.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    results = check(rows, db.connect(), etl_root())
    out = args.csv.with_name(args.csv.stem + "_review.md")
    out.write_text(report(results, args.csv), encoding="utf-8")
    n_failed = sum(bool(r["problems"]) for r in results)
    print(f"{len(results)} rows checked, {n_failed} with problems -> {out}")
    return 1 if n_failed else 0


if __name__ == "__main__":
    sys.exit(main())
