#!/usr/bin/env python3
"""
draft_eval_questions.py - Build a DRAFT P1 evaluation set for human review.

Lookup questions are generated from the parsed corpus (NHANES codebooks, MIMIC column docs,
OMOP field-level spec) by seeded sampling. Multihop, conflict and unanswerable questions (and a
few lookups) are hand-written in eval/handwritten_draft.csv; variables and sections used there
are excluded from generation to avoid near-duplicates. Every row is checked:
  - gold_doc/gold_section, and each `doc#section` in gold_evidence, must be found in data/docs
    (excerpts shown in the review file)
  - verify_sql runs read-only against data/project.duckdb; `expect` must appear in the result
  - unanswerable rows: `check_terms` (`;`-separated, optional `folder/` prefix) are grepped
    across the corpus and must not be found

Tags (see docs/PROBLEM1_PLAN.md "Evaluation set"): subtype (conflict / unanswerable kind),
needs_data (gold needs SQL, not just docs), guessable (answerable closed-book from naming
conventions), cluster (related questions that must share a split).

Outputs (never touches eval/questions.csv, which the reviewer creates):
  eval/questions_draft.csv    template schema, author = "Claude (draft)"
  eval/qa_eval_draft.jsonl    question / answer / source format from tracker task 11
  eval/review_draft.md        evidence per question; failed checks listed first

Usage:  python scripts/draft_eval_questions.py
"""

from __future__ import annotations

import csv
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

from medrag import db
from medrag.config import PROJECT_ROOT, data_dir

SEED = 0
DEV_SHARE = 0.6
AUTHOR = "Claude (draft)"
N_NHANES = {"code_meaning": 10, "special_codes": 4, "label": 5, "target": 3, "skip": 5}
N_MIMIC = {"hosp": 6, "icu": 6}
N_OMOP = {"required_yes": 3, "required_no": 2, "fk_table": 3, "fk_concept": 1}
# NHANES-wide meanings (guessable closed-book) and non-response codes outside SPECIAL
GENERIC_CODES = {"yes", "no", "refused", "don't know", "unknown", "missing"}
GUESSABLE_TEMPLATES = {"special_codes", "omop"}
OMOP_TABLES = ("person", "visit_occurrence", "visit_detail", "measurement",
               "condition_occurrence", "drug_exposure", "observation_period", "death")
SPECIAL = {(7, 9), (77, 99), (777, 999), (7777, 9999)}
NHANES_SCHEMA = "nhanes_2017_2018"
COLUMNS = ["qid", "split", "source", "qtype", "subtype", "question", "gold_answer", "gold_doc",
           "gold_section", "gold_evidence", "verify_sql", "needs_data", "guessable", "cluster",
           "author", "reviewed_by", "notes"]
PREFIX = {"nhanes": "NH", "mimic": "MI", "omop": "OM", "cross": "CR"}
EVAL_DIR = PROJECT_ROOT / "eval"


# ---------------------------------------------------------------- corpus parsing

def parse_nhanes(docs: Path) -> list[dict]:
    """Return one record per codebook variable: name, label, text, target, code rows."""
    out = []
    for path in sorted((docs / "nhanes").glob("*.htm")):
        comp = re.sub(r"^2017-2018_|\.htm$", "", path.name)
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        order = 0
        for block in soup.select("div.pagebreak"):
            dl = block.find("dl")
            if not dl:
                continue
            meta = {dt.get_text(strip=True).rstrip(":"): dd.get_text(" ", strip=True)
                    for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd"))}
            if "Variable Name" not in meta:
                continue
            rows = []
            table = block.find("table")
            for tr in table.find_all("tr")[1:] if table else []:
                tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                if len(tds) >= 3:
                    rows.append({"code": tds[0], "desc": tds[1],
                                 "count": tds[2].replace(",", ""),
                                 "skip": tds[4] if len(tds) > 4 else ""})
            out.append({"comp": comp, "doc": f"nhanes/{path.name}", "order": order,
                        "var": meta["Variable Name"], "label": meta.get("SAS Label", ""),
                        "text": meta.get("English Text", ""),
                        "target": " ".join(meta.get("Target", "").split()), "rows": rows})
            order += 1
    return out


def mimic_sections(docs: Path) -> list[dict]:
    """Return single-column sections from the MIMIC table docs.

    hosp docs use '### `col`' headings, icu docs use '## `col`'.
    """
    out = []
    for path in sorted((docs / "mimic").glob("*__*.md")):
        module, table = path.stem.split("__")
        if module == "about" or table == "index":
            continue
        text = path.read_text(encoding="utf-8")
        pattern = r"^#{2,3} `([a-z0-9_]+)`\s*\n(.*?)(?=^#{1,3} |\Z)"
        for m in re.finditer(pattern, text, re.M | re.S):
            body = " ".join(m.group(2).split())
            if body:
                out.append({"module": module, "table": table, "col": m.group(1),
                            "doc": f"mimic/{path.name}", "body": body})
    return out


def omop_fields(docs: Path) -> list[dict]:
    with (docs / "omop" / "OMOP_CDMv5.3_Field_Level.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def excerpt(docs: Path, gold_doc: str, section: str, width: int = 420) -> str | None:
    """Return text around `section` in `gold_doc`, or None if either is not found."""
    path = docs / gold_doc
    if not gold_doc or not path.is_file():
        return None
    if path.suffix == ".csv":                 # OMOP spec: match the table (and field) row
        table, _, field = section.lower().partition(".")
        with path.open(encoding="utf-8") as f:
            for rec in csv.DictReader(f):
                if (rec["cdmTableName"].lower() == table
                        and (not field or rec.get("cdmFieldName", "").lower() == field)):
                    return " | ".join(" ".join(v.split()) for v in rec.values() if v)[:width]
        return None
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".htm":
        raw = BeautifulSoup(raw, "html.parser").get_text(" ")
    text = " ".join(raw.split())
    hits = [m.start() for m in re.finditer(re.escape(section), text, re.I)]
    if path.suffix == ".htm":                 # skip the table of contents: anchor on the block
        anchor = r"Variable Name: " + re.escape(section) + r"\b"
        hits = [m.start() for m in re.finditer(anchor, text)] or hits
    else:                                     # prefer the column's heading over the column list
        anchor = r"#+ [^#]*?`" + re.escape(section) + "`"
        hits = [m.start() for m in re.finditer(anchor, text)] or hits
    if not hits:
        return None
    start = hits[0]
    return text[max(0, start - 40):start + width]


# ---------------------------------------------------------------- generated lookups

def _codes(rec: dict) -> list[tuple[int, str, int, str]]:
    return [(int(r["code"]), r["desc"], int(r["count"]), r["skip"])
            for r in rec["rows"] if r["code"].isdigit() and r["count"].isdigit()]


def _row(base: dict, question: str, answer: str, sql: str, expect: str, notes: str) -> dict:
    return {**base, "question": question, "gold_answer": answer, "verify_sql": sql,
            "expect": expect, "notes": notes}


def nhanes_lookups(recs: list[dict], data_cols: dict, exclude: set,
                   rng: random.Random) -> list[dict]:
    pools = defaultdict(list)
    for rec in recs:
        table = rec["comp"].lower()
        if (rec["var"].upper() not in data_cols.get(table, set()) or rec["var"] == "SEQN"
                or rec["var"].upper() in exclude):
            continue
        codes = _codes(rec)
        nums = {c for c, *_ in codes}
        ref = f'{NHANES_SCHEMA}.{table}'
        name = f'{rec["var"]} ({rec["label"]})'
        base = {"source": "nhanes", "qtype": "lookup", "gold_doc": rec["doc"],
                "gold_section": rec["var"]}
        regular = [c for c in codes if c[0] != 0 and not any(c[0] in s for s in SPECIAL)
                   and c[2] > 0 and c[1].lower() not in rec["label"].lower()
                   and c[1].lower() not in GENERIC_CODES]
        if len(codes) >= 2 and regular:
            code, desc, count, _ = rng.choice(regular)
            pools["code_meaning"].append(_row(
                base,
                f"In the NHANES 2017-2018 {rec['comp']} file, what does the value {code} mean "
                f"for {name}?",
                desc,
                f'SELECT COUNT(*) FROM {ref} WHERE TRY_CAST("{rec["var"]}" AS DOUBLE) = {code}',
                str(count), f"codebook count for code {code} = {count}"))
            pools["code_meaning"][-1]["_key"] = desc.lower()     # no repeated answers
        for a, b in SPECIAL:
            if a in nums and b in nums:
                descs = {c: d for c, d, *_ in codes}
                total = sum(n for c, _, n, _ in codes if c in (a, b))
                pools["special_codes"].append(_row(
                    base,
                    f"In NHANES 2017-2018 {rec['comp']}, what do the values {a} and {b} of "
                    f"{name} mean, and should they be analyzed as numbers?",
                    f"{a} = {descs[a]}, {b} = {descs[b]}; they are non-response codes and must "
                    "be treated as missing, not as values",
                    f'SELECT COUNT(*) FROM {ref} '
                    f'WHERE TRY_CAST("{rec["var"]}" AS DOUBLE) IN ({a}, {b})',
                    str(total), "tests special-code handling"))
                pools["special_codes"][-1]["_key"] = (a, b)   # one question per code pair
                break
        missing = sum(int(r["count"]) for r in rec["rows"]
                      if r["code"] == "." and r["count"].isdigit())
        total_rows = sum(int(r["count"]) for r in rec["rows"] if r["count"].isdigit())
        # a single code row marks a "code all that apply" item: the label is one answer
        # option, not what the variable records
        if rec["label"] and rec["rows"] and len(codes) != 1:
            pools["label"].append(_row(
                base,
                f"What does the NHANES 2017-2018 variable {rec['var']} in the {rec['comp']} "
                "file record?",
                rec["label"],
                f'SELECT COUNT("{rec["var"]}") FROM {ref}',
                str(total_rows - missing), "expect = codebook non-missing count"))
        if rec["target"] and table != "demo_j":
            pools["target"].append(_row(
                base,
                f"What target group (sex and age range) does the NHANES 2017-2018 codebook "
                f"list for {name}?",
                rec["target"],
                f"SELECT MIN(d.RIDAGEYR), MAX(d.RIDAGEYR) FROM {ref} t JOIN "
                f'{NHANES_SCHEMA}.demo_j d USING (SEQN) WHERE t."{rec["var"]}" IS NOT NULL',
                "", "SQL shows the observed age range for comparison (no auto-check); skip "
                "logic can narrow who is actually asked"))
        nxt = next((r for r in recs if r["comp"] == rec["comp"]
                    and r["order"] == rec["order"] + 1), None)
        for code, desc, count, skip in codes:
            if (skip and count > 0 and desc in ("Yes", "No") and nxt and nxt["var"] != skip
                    and nxt["var"].upper() in data_cols.get(table, set())):
                pools["skip"].append(_row(
                    base,
                    f"In NHANES 2017-2018 {rec['comp']}, if a participant answers '{desc}' to "
                    f"{name}, which item are they routed to next?",
                    f"{skip} (items in between, such as {nxt['var']}, are skipped)",
                    f"SELECT COUNT(NULLIF(CAST(\"{nxt['var']}\" AS VARCHAR), '')) "
                    f"FROM {ref} WHERE TRY_CAST(\"{rec['var']}\" AS DOUBLE) = {code}",
                    "0", f"skipped item {nxt['var']} should be empty (NULL or '') "
                    "for these respondents"))
                break
    picked = []
    for template, n in N_NHANES.items():
        pool = pools[template]
        rng.shuffle(pool)
        seen, keys, taken = Counter(), set(), 0
        for row in pool:                      # spread picks across component files
            if taken >= n:
                break
            key = row.pop("_key", None)
            if seen[row["gold_doc"]] >= 2 or (key is not None and key in keys):
                continue
            seen[row["gold_doc"]] += 1
            if key is not None:
                keys.add(key)
            taken += 1
            picked.append({**row, "_t": template})
    return picked


def mimic_lookups(sections: list[dict], v1_cols: set, exclude: set,
                  rng: random.Random) -> list[dict]:
    skip_cols = {"subject_id", "hadm_id", "stay_id", "itemid", "label"}   # IDs; circular
    pool = [s for s in sections if (s["table"], s["col"]) in v1_cols
            and s["col"] not in skip_cols and not s["body"].startswith("{%")
            and (s["doc"], s["col"]) not in exclude]
    rng.shuffle(pool)
    out, tables, modules = [], Counter(), Counter()
    for s in pool:
        if modules[s["module"]] >= N_MIMIC.get(s["module"], 0) or tables[s["table"]] >= 1:
            continue
        tables[s["table"]] += 1
        modules[s["module"]] += 1
        first = re.split(r"(?<=\.)\s", s["body"])
        answer = " ".join(first[:2])[:350]
        out.append({"source": "mimic", "qtype": "lookup", "_t": f"mimic_{s['module']}",
                    "question": f"In MIMIC-IV, what does the column {s['col']} in the "
                                f"{s['table']} table represent?",
                    "gold_answer": answer, "gold_doc": s["doc"], "gold_section": s["col"],
                    "verify_sql": "SELECT COUNT(*) FROM information_schema.columns WHERE "
                                  f"table_schema LIKE 'mimic_demo_v1_0%' AND "
                                  f"table_name = '{s['table']}' AND column_name = '{s['col']}'",
                    "expect": "1",
                    "notes": "answer = first sentences of the doc section; trim on review"})
    return out


def omop_lookups(fields: list[dict], omop_cols: set, rng: random.Random) -> list[dict]:
    """Required yes/no and foreign-key questions, balanced across answer types."""
    rows = [f for f in fields if f["cdmTableName"] in OMOP_TABLES
            and (f["cdmTableName"], f["cdmFieldName"]) in omop_cols
            and f["isPrimaryKey"] != "Yes"]
    rng.shuffle(rows)
    doc = "omop/OMOP_CDMv5.3_Field_Level.csv"
    out, used, fk_cols, taken = [], set(), set(), Counter()
    for f in rows:
        t, c = f["cdmTableName"], f["cdmFieldName"]
        req = f["isRequired"] == "Yes"
        kind = "required_yes" if req else "required_no"
        if (t, c) not in used and taken[kind] < N_OMOP[kind]:
            used.add((t, c))
            taken[kind] += 1
            out.append({"source": "omop", "qtype": "lookup", "_t": "omop",
                        "question": f"In the OMOP CDM v5.3 specification, is the field {c} in "
                                    f"the {t.upper()} table required?",
                        "gold_answer": "Yes" if req else "No",
                        "gold_doc": doc, "gold_section": f"{t}.{c}",
                        "verify_sql": f"SELECT COUNT(*) FILTER (WHERE {c} IS NULL), COUNT(*) "
                                      f"FROM omop_demo_v0_9.{t}",
                        "expect": "(0," if req else "",
                        "notes": "required fields should have no NULLs in the demo data"})
            continue
        if f["isForeignKey"] != "Yes" or f["fkTableName"] in ("NA", ""):
            continue
        kind = "fk_concept" if f["fkTableName"].upper() == "CONCEPT" else "fk_table"
        if (t, c) not in used and c not in fk_cols and taken[kind] < N_OMOP[kind]:
            used.add((t, c))
            fk_cols.add(c)                    # e.g. person_id only once, not per table
            taken[kind] += 1
            out.append({"source": "omop", "qtype": "lookup", "_t": "omop",
                        "question": f"In OMOP CDM v5.3, which table does {t.upper()}.{c} "
                                    f"reference as a foreign key?",
                        "gold_answer": f"{f['fkTableName']} ({f['fkFieldName']})",
                        "gold_doc": doc, "gold_section": f"{t}.{c}",
                        "verify_sql": "SELECT COUNT(*) FROM information_schema.columns WHERE "
                                      f"table_schema = 'omop_demo_v0_9' AND table_name = '{t}' "
                                      f"AND column_name = '{c}'",
                        "expect": "1", "notes": "column exists in the OMOP demo"})
    return out


# ---------------------------------------------------------------- checks and output

def run_sql(con, sql: str) -> str:
    if not sql:
        return ""
    try:
        rows = con.execute(sql).fetchmany(5)
        return "; ".join(str(r) for r in rows) or "(no rows)"
    except Exception as exc:                  # noqa: BLE001 - report any SQL failure
        return f"SQL ERROR: {exc}".splitlines()[0]


def corpus_hits(docs: Path, terms: str, cache: dict) -> list[str]:
    if "text" not in cache:
        parts = {}
        for p in docs.rglob("*"):
            if p.is_file():
                raw = p.read_text(encoding="utf-8", errors="replace")
                if p.suffix == ".htm":
                    raw = BeautifulSoup(raw, "html.parser").get_text(" ")
                parts[str(p.relative_to(docs))] = raw.lower()
        cache["text"] = parts
    hits = []
    for term in [t.strip().lower() for t in terms.split(";") if t.strip()]:
        folder, _, word = term.rpartition("/")      # "mimic/zip code" searches mimic/ only
        hits += [f"'{word}' in {name}" for name, txt in cache["text"].items()
                 if word in txt and Path(name).parts[0].startswith(folder)]
    return hits


def check(row: dict, con, docs: Path, cache: dict) -> dict:
    problems = []
    row["sql_result"] = run_sql(con, row.get("verify_sql", ""))
    if row["sql_result"].startswith("SQL ERROR"):
        problems.append("verify_sql failed")
    elif row.get("expect") and row["expect"] not in row["sql_result"]:
        problems.append(f"expected '{row['expect']}' in SQL result")
    if row["qtype"] == "unanswerable":
        row["excerpt"] = ""
        hits = corpus_hits(docs, row.get("check_terms", ""), cache)
        if hits:
            problems.append("corpus mentions: " + ", ".join(hits[:3]))
    else:
        row["excerpt"] = excerpt(docs, row["gold_doc"], row["gold_section"]) or ""
        if not row["excerpt"]:
            problems.append("gold_doc/gold_section not found")
    row["evidence"] = []
    for item in [e.strip() for e in row.get("gold_evidence", "").split(";") if e.strip()]:
        doc, _, section = item.partition("#")
        text = excerpt(docs, doc, section, width=240)
        row["evidence"].append((item, text or ""))
        if not text:
            problems.append(f"gold_evidence '{item}' not found")
    row["problems"] = problems
    return row


def tag_generated(row: dict) -> dict:
    """Default tags for generated lookups (hand-written rows carry their own)."""
    template = row.get("_t", "")
    row.setdefault("needs_data", "no")
    row.setdefault("guessable", "yes" if template in GUESSABLE_TEMPLATES else "no")
    return row


def apply_overrides(rows: list[dict]) -> list[dict]:
    """Apply reviewed fixes from eval/generated_overrides.csv (question, field, value).

    field `drop` removes the row. Every override must match a generated question, so a stale
    override (e.g. after a sampling change) fails loudly instead of being ignored.
    """
    path = EVAL_DIR / "generated_overrides.csv"
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as f:
        overrides = list(csv.DictReader(f))
    by_question = {r["question"]: r for r in rows}
    stale = [o["question"] for o in overrides if o["question"] not in by_question]
    if stale:
        raise SystemExit(f"overrides match no generated question: {stale[:3]}")
    dropped = set()
    for o in overrides:
        if o["field"] == "drop":
            dropped.add(o["question"])
        else:
            by_question[o["question"]][o["field"]] = o["value"]
    return [r for r in rows if r["question"] not in dropped]


def assign_ids_and_split(rows: list[dict]) -> None:
    """Seeded ~60/40 split, balanced in every qtype x source x template cell.

    Rows sharing a `cluster` form one unit and always go to the same split. Units are taken
    largest first (seeded order within a size) and each goes to whichever split keeps the
    dev share of the cells it touches closest to DEV_SHARE.
    """
    rng = random.Random(SEED)

    def cell(row: dict) -> tuple:
        return row["qtype"], row["source"], row.get("_t", "")

    units = defaultdict(list)
    for i, row in enumerate(rows):
        units[row.get("cluster") or f"_row{i}"].append(row)
    order = list(units.values())
    rng.shuffle(order)
    order.sort(key=len, reverse=True)
    n_dev, n_seen = Counter(), Counter()
    for unit in order:
        sizes = Counter(cell(r) for r in unit)

        def cost(to_dev: bool) -> float:
            return sum((n_dev[c] + n * to_dev - DEV_SHARE * (n_seen[c] + n)) ** 2
                       for c, n in sizes.items())

        dev_cost, test_cost = cost(True), cost(False)
        to_dev = dev_cost < test_cost or (dev_cost == test_cost and rng.random() < DEV_SHARE)
        for c, n in sizes.items():
            n_seen[c] += n
            n_dev[c] += n * to_dev
        for row in unit:
            row["split"] = "dev" if to_dev else "test"
    order = {"lookup": 0, "multihop": 1, "conflict": 2, "unanswerable": 3}
    counters = Counter()
    for row in sorted(rows, key=lambda r: (r["source"], order[r["qtype"]])):
        counters[row["source"]] += 1
        row["qid"] = f"{PREFIX[row['source']]}-{counters[row['source']]:03d}"


def write_outputs(rows: list[dict]) -> None:
    rows.sort(key=lambda r: r["qid"])
    with (EVAL_DIR / "questions_draft.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows({**r, "author": AUTHOR, "reviewed_by": ""} for r in rows)
    with (EVAL_DIR / "qa_eval_draft.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"qid": r["qid"], "split": r["split"], "question": r["question"],
                                "answer": r["gold_answer"], "source": r["source"],
                                "qtype": r["qtype"], "subtype": r.get("subtype", ""),
                                "gold_doc": r["gold_doc"], "gold_section": r["gold_section"],
                                "gold_evidence": r.get("gold_evidence", ""),
                                "needs_data": r["needs_data"], "guessable": r["guessable"]})
                    + "\n")

    counts = Counter((r["qtype"], r["source"]) for r in rows)
    sources = ["nhanes", "mimic", "omop", "cross"]
    lines = ["# P1 evaluation set - DRAFT for review", "",
             "Generated by `scripts/draft_eval_questions.py` (seed 0). **Nothing here is final.**",
             "Review each question, fix or drop it, fill `reviewed_by`, then save the kept rows "
             "as `eval/questions.csv`. The dev/test split is a *proposal* (60/40, stratified by "
             "qtype x source x generator template; each `cluster` of related questions stays "
             "in one split); freeze it before any results exist.", "",
             "| qtype | " + " | ".join(sources) + " | total |",
             "|---|" + "---|" * (len(sources) + 1)]
    for qt in ("lookup", "multihop", "conflict", "unanswerable"):
        cells = [counts[(qt, s)] for s in sources]
        lines.append(f"| {qt} | " + " | ".join(map(str, cells)) + f" | {sum(cells)} |")
    split = Counter(r["split"] for r in rows)
    test = Counter((r["qtype"], r["source"]) for r in rows if r["split"] == "test")
    lines += ["", "Test split only:", "",
              "| qtype | " + " | ".join(sources) + " | total |",
              "|---|" + "---|" * (len(sources) + 1)]
    for qt in ("lookup", "multihop", "conflict", "unanswerable"):
        cells = [test[(qt, s)] for s in sources]
        lines.append(f"| {qt} | " + " | ".join(map(str, cells)) + f" | {sum(cells)} |")
    tags = Counter(r.get("subtype") for r in rows if r.get("subtype"))
    lines += ["", f"Total {len(rows)} questions; dev {split['dev']}, test {split['test']}. "
              f"needs_data = yes: {sum(r['needs_data'] == 'yes' for r in rows)}; "
              f"guessable = yes: {sum(r['guessable'] == 'yes' for r in rows)}.",
              "Subtypes: " + ", ".join(f"{k} {v}" for k, v in sorted(tags.items())) + ".", ""]
    flagged = [r for r in rows if r["problems"]]
    lines += [f"## Failed checks ({len(flagged)})", ""]
    lines += [f"- **{r['qid']}**: {'; '.join(r['problems'])}" for r in flagged] or ["None."]
    lines += ["", "## Questions", ""]
    for r in rows:
        status = "CHECK FAILED" if r["problems"] else "checks passed"
        qtype = r["qtype"] + (f" ({r['subtype']})" if r.get("subtype") else "")
        flags = [f"needs_data={r['needs_data']}", f"guessable={r['guessable']}"]
        flags += [f"cluster={r['cluster']}"] if r.get("cluster") else []
        lines += [f"### {r['qid']} - {qtype} / {r['source']} / {r['split']} ({status})",
                  f"**Q:** {r['question']}  ",
                  f"**Gold:** {r['gold_answer'] or '(abstain - not in corpus)'}  ",
                  f"**Source:** `{r['gold_doc']}` -> `{r['gold_section']}`  ",
                  f"**Tags:** {', '.join(flags)}  "]
        if r["excerpt"]:
            lines.append(f"**Doc excerpt:** {r['excerpt']}  ")
        for item, text in r["evidence"]:
            lines.append(f"**Also needs** `{item}`: {text}  ")
        if r.get("verify_sql"):
            lines += [f"**SQL:** `{r['verify_sql']}`  ",
                      f"**Result:** `{r['sql_result']}`"
                      + (f" (expected to contain `{r['expect']}`)" if r.get("expect") else "")
                      + "  "]
        if r.get("notes"):
            lines.append(f"**Notes:** {r['notes']}  ")
        if r["problems"]:
            lines.append(f"**Problems:** {'; '.join(r['problems'])}  ")
        lines.append("")
    (EVAL_DIR / "review_draft.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    docs = data_dir() / "docs"
    con = db.connect()
    rng = random.Random(SEED)

    data_cols = defaultdict(set)
    for t, c in con.execute("SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema = ?", [NHANES_SCHEMA]).fetchall():
        data_cols[t].add(c.upper())
    v1_cols = set(con.execute("SELECT table_name, column_name FROM information_schema.columns "
                              "WHERE table_schema LIKE 'mimic_demo_v1_0%'").fetchall())
    omop_cols = set(con.execute("SELECT table_name, column_name FROM information_schema.columns "
                                "WHERE table_schema = 'omop_demo_v0_9'").fetchall())

    with (EVAL_DIR / "handwritten_draft.csv").open(encoding="utf-8") as f:
        handwritten = list(csv.DictReader(f))
    used = {(r["gold_doc"], r["gold_section"]) for r in handwritten}
    for r in handwritten:
        used |= {tuple(e.strip().split("#", 1)) for e in r["gold_evidence"].split(";") if "#" in e}
    used_vars = {s.upper() for d, s in used if d.startswith("nhanes/")}

    generated = (nhanes_lookups(parse_nhanes(docs), data_cols, used_vars, rng)
                 + mimic_lookups(mimic_sections(docs), v1_cols, used, rng)
                 + omop_lookups(omop_fields(docs), omop_cols, rng))
    generated = apply_overrides([tag_generated(r) for r in generated])
    rows = generated + handwritten

    cache: dict = {}
    rows = [check(r, con, docs, cache) for r in rows]
    con.close()
    assign_ids_and_split(rows)
    write_outputs(rows)

    by_type = Counter(r["qtype"] for r in rows)
    print(f"{len(rows)} questions: {dict(by_type)}")
    print(f"sources: {dict(Counter(r['source'] for r in rows))}")
    print(f"split: {dict(Counter(r['split'] for r in rows))}")
    print(f"failed checks: {sum(bool(r['problems']) for r in rows)} (see eval/review_draft.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
