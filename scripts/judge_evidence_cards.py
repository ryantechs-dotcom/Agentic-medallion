#!/usr/bin/env python
"""Evidence cards for hand-labelling the judge-validation sheet (no model involved).

    python scripts/judge_evidence_cards.py --out <file.md>

For each row of eval/judge_label_sample.csv, a card shows the question, gold answer and notes,
the corpus text of the sections the gold cites (gold_doc#gold_section and gold_evidence), the
result of the gold's verify_sql on the read-only database, and the model's answer. It reads
only the sheet, eval/questions.csv, the corpus and the database: never results/ or
judgments.jsonl, so the cards carry no judge verdicts and the labels stay blind (D20).
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from medrag.config import PROJECT_ROOT, load_config
from medrag.contracts import matches_gold
from medrag.corpus.chunking import load_records
from medrag.db import connect

SHEET = PROJECT_ROOT / "eval" / "judge_label_sample.csv"
QUESTIONS = PROJECT_ROOT / "eval" / "questions.csv"
MAX_SECTIONS = 3
MAX_SQL_ROWS = 10
UNANSWERABLE_RULE = ("Gold is empty: the information is not in the documentation. Per judge_v1, "
                     "saying it is not available is correct; giving a specific value, name or "
                     "column anyway is incorrect.")


def gold_refs(question: dict) -> list[tuple[str, str]]:
    """(doc, section) pairs the gold cites: gold_doc#gold_section, then each gold_evidence."""
    refs = [(question["gold_doc"], question["gold_section"])] if question["gold_doc"] else []
    for entry in filter(None, question["gold_evidence"].split(";")):
        doc, _, section = entry.strip().partition("#")
        refs.append((doc, section))
    return refs


def find_sections(records: list[dict], doc: str, section: str) -> list[dict]:
    """Records supporting one ref; records whose section heading matches come first."""
    hits = [r for r in records if matches_gold(r, doc, section)]
    needle = " ".join(section.lower().split())
    return sorted(hits, key=lambda r: (needle not in " ".join(r["section"].lower().split()),
                                       r["order"]))


def sql_text(result: list[tuple] | str | None) -> str:
    """A verify_sql result (rows, or an error message) as card text."""
    if result is None:
        return "(no verify_sql for this question)"
    if isinstance(result, str):
        return f"ERROR: {result}"
    lines = [" | ".join(str(v) for v in row) for row in result[:MAX_SQL_ROWS]]
    if len(result) > MAX_SQL_ROWS:
        lines.append(f"... {len(result) - MAX_SQL_ROWS} more rows")
    return "\n".join(lines) or "(0 rows)"


def card(sample: dict, question: dict, sections: dict, sql_result) -> str:
    """Markdown card for one sheet row. `sections` maps (doc, section) -> matching records."""
    gold = sample["gold_answer"].strip()
    out = [f"## {sample['sample_id']} - {sample['qid']} ({sample['qtype']}), run {sample['run']}",
           "", f"**Question:** {sample['question']}", "",
           f"**Gold:** {gold or '(empty)'}", "", f"**Notes:** {sample['notes'] or '(none)'}", ""]
    if not gold:
        out += [f"_{UNANSWERABLE_RULE}_", ""]
    out.append("**Evidence (corpus text the gold cites):**")
    refs = gold_refs(question)
    if not refs:
        out.append("(the gold cites no document)")
    for ref in refs:
        hits = sections.get(ref, [])
        out += ["", f"`{ref[0]}#{ref[1]}`"]
        if not hits:
            out.append("not found in the corpus")
        for record in hits[:MAX_SECTIONS]:
            out.append(f"> [{record['section']}]")
            out += [f"> {line}" for line in record["text"].splitlines()]
        if len(hits) > MAX_SECTIONS:
            out.append(f"({len(hits) - MAX_SECTIONS} more matching sections not shown)")
    out += ["", "**Data check (verify_sql):**"]
    if question["verify_sql"].strip():
        out += ["```sql", question["verify_sql"].strip(), "```"]
    out += ["```", sql_text(sql_result), "```", "", f"**Answer:** {sample['answer']}", ""]
    return "\n".join(out)


def run_sql(con, sql: str):
    """Rows of a verify_sql, or the error text; None when the question has no SQL."""
    if not sql.strip():
        return None
    try:
        return con.execute(sql).fetchall()
    except Exception as err:  # show any SQL failure on the card instead of stopping
        return f"{type(err).__name__}: {err}"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="write the cards here (default: print)")
    args = parser.parse_args()

    config = load_config()
    records = load_records(PROJECT_ROOT / config["paths"]["corpus_file"])
    questions = {q["qid"]: q for q in read_csv(QUESTIONS)}
    con = connect()
    cards = []
    for sample in read_csv(SHEET):
        question = questions[sample["qid"]]
        sections = {ref: find_sections(records, *ref) for ref in gold_refs(question)}
        cards.append(card(sample, question, sections, run_sql(con, question["verify_sql"])))
    text = "\n---\n\n".join(cards)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"{len(cards)} cards -> {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
