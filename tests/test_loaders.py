"""Corpus loaders on small hand-written files shaped like the real sources."""

import zipfile

from medrag import contracts
from medrag.corpus import loaders

NHANES_HTML = """<html><body>
<div id="toc"><h2>Component Description</h2></div>
<div id="Sections">
<h3>Diabetes (DIQ_J)</h3>
<h2 id="Component_Description">Component Description</h2>
<p>The diabetes   section provides
interview data.</p>
<h2 id="Analytic_Notes">Analytic Notes</h2>
<p>Use the weights.</p>
<h2>Codebook and Frequencies</h2>
</div>
<div class="pagebreak"><h3 id="SEQN">SEQN - Respondent sequence number</h3>
<dl><dt>Variable Name:</dt><dd>SEQN</dd><dt>SAS Label:</dt><dd>Respondent sequence number</dd>
</dl></div>
<div class="pagebreak"><h3 id="DIQ010">DIQ010 - Doctor told you have diabetes</h3>
<dl><dt>Variable Name:</dt><dd>DIQ010</dd><dt>SAS Label:</dt><dd>Doctor told you</dd>
<dt>English Text:</dt><dd>Ever told by a doctor?</dd><dt>Target:</dt><dd>Both  1 YEARS -
  150 YEARS</dd></dl>
<table><thead><tr><th>Code or Value</th><th>Value Description</th><th>Count</th>
<th>Cumulative</th><th>Skip to Item</th></tr></thead>
<tbody><tr><td>1</td><td>Yes</td><td>856</td><td>856</td><td></td></tr>
<tr><td>7</td><td>Refused</td><td>0</td><td>856</td><td>DIQ050</td></tr>
<tr><td>9</td><td>Don't know</td><td>5</td><td>861</td><td>DIQ050</td></tr></tbody></table>
</div></body></html>"""

MIMIC_MD = """---
title: labevents
description: Laboratory measurements.
parent: Hosp
---

Intro text before any heading.

<!--
# Hidden heading
-->

## Table columns

Name | Postgres data type
---- | ----
`value` | VARCHAR(200)

### `hadm_id`

{% include hadm_id.md %}

### `value`, `valuenum`

The result, and the numeric value.

```
# not a heading inside a code fence
```
"""

OMOP_TABLES = "cdmTableName,isRequired,tableDescription\nperson,Yes,People.\n"
OMOP_FIELDS = ("cdmTableName,cdmFieldName,isRequired,userGuidance\n"
               "person,gender_concept_id,Yes,Sex at birth.\n"
               "person,year_of_birth,Yes,NA\n"
               "NA,,,\n")


def make_data_dir(tmp_path):
    docs = tmp_path / "docs"
    for folder in ("nhanes", "mimic", "omop"):
        (docs / folder).mkdir(parents=True)
    (docs / "nhanes" / "2017-2018_DIQ_J.htm").write_text(NHANES_HTML, encoding="utf-8")
    (docs / "mimic" / "hosp__labevents.md").write_text(MIMIC_MD, encoding="utf-8")
    (docs / "omop" / loaders.OMOP_TABLE_CSV).write_text(OMOP_TABLES, encoding="utf-8")
    (docs / "omop" / loaders.OMOP_FIELD_CSV).write_text(OMOP_FIELDS, encoding="utf-8")
    zip_path = tmp_path / loaders.MIMIC_DOCS_ZIP
    zip_path.parent.mkdir(parents=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("site-main/_includes/hadm_id.md", "`hadm_id` is a stay identifier.\n")
    return tmp_path


def test_nhanes_records(tmp_path):
    data = make_data_dir(tmp_path)
    path = data / "docs" / "nhanes" / "2017-2018_DIQ_J.htm"
    records = loaders.load_nhanes(path, data / "docs")
    sections = [(r["kind"], r["section"]) for r in records]
    assert sections == [("nhanes_narrative", "Component Description"),
                        ("nhanes_narrative", "Analytic Notes"),
                        ("nhanes_variable", "SEQN"), ("nhanes_variable", "DIQ010")]
    narrative, diq010 = records[0], records[3]
    assert "The diabetes section provides interview data." in narrative["text"]
    assert diq010["doc"] == "nhanes/2017-2018_DIQ_J.htm"
    assert diq010["metadata"]["component"] == "DIQ_J"
    assert diq010["metadata"]["component_title"] == "Diabetes (DIQ_J)"
    assert "Target: Both 1 YEARS - 150 YEARS" in diq010["text"]
    assert "7 | Refused | 0 | DIQ050" in diq010["text"]
    assert "9 | Don't know | 5 | DIQ050" in diq010["text"]
    assert "861" not in diq010["text"]           # cumulative counts are dropped


def test_mimic_records(tmp_path):
    data = make_data_dir(tmp_path)
    path = data / "docs" / "mimic" / "hosp__labevents.md"
    includes = loaders.load_mimic_includes(data / loaders.MIMIC_DOCS_ZIP)
    records = loaders.load_mimic(path, data / "docs", includes)
    by_section = {r["section"]: r for r in records}
    assert list(by_section) == ["labevents", "Table columns", "hadm_id", "value, valuenum"]
    assert "Laboratory measurements." in by_section["labevents"]["text"]
    assert "Hidden heading" not in "".join(r["text"] for r in records)
    assert "`hadm_id` is a stay identifier." in by_section["hadm_id"]["text"]
    value = by_section["value, valuenum"]
    assert "The result, and the numeric value." in value["text"]
    assert "# not a heading inside a code fence" in value["text"]
    assert value["metadata"]["heading_path"] == ["Table columns", "value, valuenum"]
    assert value["metadata"]["module"] == "hosp"


def test_omop_records(tmp_path):
    data = make_data_dir(tmp_path)
    omop = data / "docs" / "omop"
    records = loaders.load_omop(omop / loaders.OMOP_TABLE_CSV, omop / loaders.OMOP_FIELD_CSV,
                                data / "docs")
    assert [(r["kind"], r["section"]) for r in records] == [
        ("omop_table", "person"), ("omop_field", "person.gender_concept_id"),
        ("omop_field", "person.year_of_birth")]
    assert "userGuidance: Sex at birth." in records[1]["text"]
    assert "userGuidance" not in records[2]["text"]   # NA values are left out


def test_load_all_ids_order_and_contract(tmp_path):
    records = loaders.load_all(make_data_dir(tmp_path))
    contracts.validate_all(records, "corpus_record")
    assert [r["order"] for r in records] == list(range(len(records)))
    assert [r["source"] for r in records][:1] == ["nhanes"]
    assert records[-1]["id"] == "omop/OMOP_CDMv5.3_Field_Level.csv#person.year_of_birth"


def test_repeated_sections_get_suffixes():
    records = [{"doc": "d.md", "section": "Major changes"} for _ in range(3)]
    ids = [r["id"] for r in loaders.assign_ids(records)]
    assert ids == ["d.md#Major changes", "d.md#Major changes~2", "d.md#Major changes~3"]


def test_clean_heading_keeps_identifier_underscores():
    assert loaders.clean_heading("`hadm_id`") == "hadm_id"
    assert loaders.clean_heading("*_labevents_*") == "labevents"
