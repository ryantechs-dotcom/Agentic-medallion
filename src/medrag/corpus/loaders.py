"""Load the RAG corpus from data/docs into section-level records (docs/contracts.md).

One record per natural unit of each source:
- NHANES codebook (.htm): one record per narrative section (h2) and one per variable block
- MIMIC docs (.md): one record per heading with a body (plus the text before the first heading)
- OMOP CDM spec (.csv): one record per table row and one per field row

The loaders only parse and normalize whitespace; they never rewrite what a source says. `doc`
is the path relative to data/docs, so records line up with `gold_doc` in the eval set.
"""

from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path

import yaml
from bs4 import BeautifulSoup, Tag

NHANES_CYCLE = "2017-2018"
MIMIC_DOC_VERSION = "v2.x"
OMOP_CDM_VERSION = "5.3"
OMOP_TABLE_CSV = "OMOP_CDMv5.3_Table_Level.csv"
OMOP_FIELD_CSV = "OMOP_CDMv5.3_Field_Level.csv"
OMOP_EMPTY = {"", "NA"}           # the OMOP spec CSVs write missing values as NA
NHANES_CODEBOOK_HEADING = "Codebook and Frequencies"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
SPACE_RE = re.compile(r"[^\S\n]")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
INCLUDE_RE = re.compile(r"\{%\s*include\s+(\S+)\s*%\}")
# Jekyll `{% include x.md %}` snippets live in the frozen docs zip, not in data/docs/mimic
MIMIC_DOCS_ZIP = Path("raw/github/mimic_docs.zip")      # relative to the data dir


def squash(text: str) -> str:
    """Collapse runs of whitespace to single spaces."""
    return " ".join(text.split())


def _record(doc: str, section: str, source: str, kind: str, title: str, text: str,
            metadata: dict) -> dict:
    """Build a corpus record; `id` and `order` are assigned by `load_all`."""
    return {"id": "", "doc": doc, "section": section, "source": source, "kind": kind,
            "title": title, "text": text, "order": -1, "metadata": metadata}


# ---------------------------------------------------------------- NHANES

def _nhanes_narratives(soup: BeautifulSoup, doc: str, meta: dict) -> list[dict]:
    """One record per h2 section of the documentation part of a codebook page."""
    records = []
    for heading in soup.find_all("h2"):
        name = squash(heading.get_text(" "))
        if name == NHANES_CODEBOOK_HEADING or heading.find_parent("div", id="toc"):
            continue
        parts = []
        for sibling in heading.next_siblings:
            if isinstance(sibling, Tag) and sibling.name == "h2":
                break
            text = sibling.get_text(" ") if isinstance(sibling, Tag) else str(sibling)
            if text.strip():
                parts.append(squash(text))
        body = "\n".join(parts)
        if not body:
            continue
        title = f"{meta['component_title']} - {name}"
        records.append(_record(doc, name, "nhanes", "nhanes_narrative", title,
                               f"{title}\n{body}", dict(meta, heading_path=[name])))
    return records


def _nhanes_variables(soup: BeautifulSoup, doc: str, meta: dict) -> list[dict]:
    """One record per variable block: header fields, then one line per code row."""
    records = []
    for block in soup.select("div.pagebreak"):
        dl = block.find("dl")
        if not dl:
            continue
        fields = {squash(dt.get_text(" ")).rstrip(":"): squash(dd.get_text(" "))
                  for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd"))}
        var = fields.get("Variable Name")
        if not var:
            continue
        heading = block.find("h3")
        title = squash(heading.get_text(" ")) if heading else var
        lines = [title] + [f"{key}: {value}" for key, value in fields.items()]
        table = block.find("table")
        if table:
            header = [squash(th.get_text(" ")) for th in table.find_all("th")]
            lines.append("Codes: " + " | ".join(h for h in header if h != "Cumulative"))
            for row in table.find_all("tr"):
                cells = [squash(td.get_text(" ")) for td in row.find_all("td")]
                if len(cells) >= 3:
                    # keep code, description, count and skip-to; drop the cumulative count
                    keep = cells[:3] + cells[4:5]
                    lines.append(" | ".join(keep))
        records.append(_record(doc, var, "nhanes", "nhanes_variable", title, "\n".join(lines),
                               dict(meta, heading_path=[NHANES_CODEBOOK_HEADING, var])))
    return records


def load_nhanes(path: Path, docs_dir: Path) -> list[dict]:
    """Records for one NHANES codebook page (narrative sections, then variables)."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    component = re.sub(rf"^{NHANES_CYCLE}_|\.htm$", "", path.name)
    title_tag = soup.find("h3", string=re.compile(rf"\({re.escape(component)}\)"))
    component_title = squash(title_tag.get_text(" ")) if title_tag else component
    doc = path.relative_to(docs_dir).as_posix()
    meta = {"component": component, "component_title": component_title,
            "cycle": NHANES_CYCLE, "file": path.name}
    return _nhanes_narratives(soup, doc, meta) + _nhanes_variables(soup, doc, meta)


# ---------------------------------------------------------------- MIMIC

def _split_front_matter(text: str) -> tuple[dict, str]:
    """Return (YAML front matter, body) for a Jekyll-style markdown page."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return yaml.safe_load(parts[1]) or {}, parts[2]
    return {}, text


def clean_heading(text: str) -> str:
    """Heading text without markdown emphasis or backticks, e.g. 'value, valuenum'.

    Underscores are removed only as emphasis markers (`_labevents_`), never inside names
    like `hadm_id`.
    """
    text = re.sub(r"[`*]", "", text)
    return squash(re.sub(r"(?<!\w)_+|_+(?!\w)", "", text))


def load_mimic_includes(zip_path: Path) -> dict[str, str]:
    """Jekyll include snippets (`_includes/<name>`) from the frozen MIMIC docs zip."""
    includes = {}
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            parent, _, file_name = name.rpartition("/")
            if parent.endswith("_includes") and file_name:
                includes[file_name] = archive.read(name).decode("utf-8").strip()
    return includes


def load_mimic(path: Path, docs_dir: Path, includes: dict[str, str] | None = None) -> list[dict]:
    """One record per markdown heading with a body; text before any heading is the intro.

    `{% include x.md %}` is replaced by the snippet from `includes`, as on the website;
    a missing snippet raises KeyError rather than leaving template code in the corpus.
    """
    front, body = _split_front_matter(path.read_text(encoding="utf-8"))
    # HTML comments are not rendered on the MIMIC website, so they are not published docs
    body = HTML_COMMENT_RE.sub("", body)
    if includes is not None:
        body = INCLUDE_RE.sub(lambda match: includes[match.group(1)], body)
    doc = path.relative_to(docs_dir).as_posix()
    module = path.stem.split("__")[0]
    page = squash(str(front.get("title", path.stem)))
    meta = {"module": module, "page": page,
            "description": squash(str(front.get("description", ""))),
            "doc_version": MIMIC_DOC_VERSION, "file": path.name}

    sections: list[tuple[list[str], list[str]]] = [([], [])]   # (heading path, body lines)
    stack: list[tuple[int, str]] = []
    in_fence = False
    for line in body.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
        match = None if in_fence else HEADING_RE.match(line)
        if match:
            level, name = len(match.group(1)), clean_heading(match.group(2))
            stack = [(lvl, h) for lvl, h in stack if lvl < level] + [(level, name)]
            sections.append(([h for _, h in stack], []))
        else:
            sections[-1][1].append(line)

    records = []
    for heading_path, lines in sections:
        # plain spaces for any other whitespace (the docs use non-breaking spaces); keep the
        # line structure and indentation so lists and tables stay readable
        text = "\n".join(SPACE_RE.sub(" ", line).rstrip() for line in lines).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        if not text:
            continue
        section = heading_path[-1] if heading_path else page
        title = " > ".join([page] + heading_path)
        if not heading_path and meta["description"]:
            text = f"{meta['description']}\n\n{text}"
        records.append(_record(doc, section, "mimic", "mimic_section", title,
                               f"{title}\n{text}", dict(meta, heading_path=heading_path)))
    return records


# ---------------------------------------------------------------- OMOP

def _omop_rows(path: Path, docs_dir: Path, kind: str) -> list[dict]:
    doc = path.relative_to(docs_dir).as_posix()
    records = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            table = row["cdmTableName"].strip().lower()
            if table in {value.lower() for value in OMOP_EMPTY}:
                continue                  # blank trailing row in the field-level CSV
            field = row.get("cdmFieldName", "").strip().lower()
            section = f"{table}.{field}" if kind == "omop_field" else table
            lines = [f"{key}: {squash(value)}" for key, value in row.items()
                     if squash(value or "") not in OMOP_EMPTY]
            title = f"OMOP CDM v{OMOP_CDM_VERSION} {section}"
            meta = {"table": table, "cdm_version": OMOP_CDM_VERSION, "file": path.name}
            if field:
                meta["field"] = field
            records.append(_record(doc, section, "omop", kind, title,
                                   title + "\n" + "\n".join(lines), meta))
    return records


def load_omop(table_csv: Path, field_csv: Path, docs_dir: Path) -> list[dict]:
    """One record per table-level row, then one per field-level row."""
    return (_omop_rows(table_csv, docs_dir, "omop_table")
            + _omop_rows(field_csv, docs_dir, "omop_field"))


# ---------------------------------------------------------------- all sources

def assign_ids(records: list[dict]) -> list[dict]:
    """Set `order` and a stable `id` (doc#section, with ~2, ~3 for repeats)."""
    counts: dict[str, int] = {}
    for order, record in enumerate(records):
        base = f"{record['doc']}#{record['section']}"
        counts[base] = counts.get(base, 0) + 1
        record["id"] = base if counts[base] == 1 else f"{base}~{counts[base]}"
        record["order"] = order
    return records


def load_all(data_dir: Path) -> list[dict]:
    """Every corpus record from <data_dir>/docs, in a fixed order: NHANES, MIMIC, OMOP."""
    docs_dir = data_dir / "docs"
    records: list[dict] = []
    for path in sorted((docs_dir / "nhanes").glob("*.htm")):
        records += load_nhanes(path, docs_dir)
    includes = load_mimic_includes(data_dir / MIMIC_DOCS_ZIP)
    for path in sorted((docs_dir / "mimic").glob("*.md")):
        records += load_mimic(path, docs_dir, includes)
    omop = docs_dir / "omop"
    records += load_omop(omop / OMOP_TABLE_CSV, omop / OMOP_FIELD_CSV, docs_dir)
    return assign_ids(records)
