"""Corpus built from the real snapshot: complete, deterministic, and covers every gold section.

The gold-coverage test reads only gold metadata (gold_doc, gold_section, gold_evidence), never
system outputs. A failure means the parser is missing a section; fix the parser, not the gold.
"""

import csv

import pytest

from medrag import contracts
from medrag.config import PROJECT_ROOT, data_dir
from medrag.corpus.loaders import load_all

import build_corpus


@pytest.fixture(scope="module")
def records():
    if not (data_dir() / "docs").exists():
        pytest.skip("data snapshot not present")
    return contracts.validate_all(load_all(data_dir()), "corpus_record")


def gold_references():
    with (PROJECT_ROOT / "eval" / "questions.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    refs = [(r["qid"], r["gold_doc"], r["gold_section"]) for r in rows if r["gold_doc"]]
    for row in rows:
        for entry in filter(None, row["gold_evidence"].split(";")):
            doc, _, section = entry.partition("#")
            refs.append((row["qid"], doc, section))
    return refs


def test_every_source_and_kind_present(records):
    assert {r["kind"] for r in records} == set(contracts.CORPUS_KINDS)
    assert not any("{%" in r["text"] or "<!--" in r["text"] for r in records)


def test_build_is_deterministic(records):
    assert build_corpus.serialize(records) == build_corpus.serialize(load_all(data_dir()))


def test_every_gold_reference_is_covered(records):
    refs = gold_references()
    missing = [ref for ref in refs
               if not any(contracts.matches_gold(r, ref[1], ref[2]) for r in records)]
    assert refs and not missing, f"{len(missing)}/{len(refs)} gold references uncovered"
