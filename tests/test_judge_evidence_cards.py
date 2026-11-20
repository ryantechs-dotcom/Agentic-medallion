"""Evidence cards for the judge-validation sheet: pure card building, no data needed."""

import importlib.util

spec = importlib.util.spec_from_file_location("judge_evidence_cards",
                                              "scripts/judge_evidence_cards.py")
cards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cards)

SAMPLE = {"sample_id": "J99", "run": "r", "qid": "NH-999", "qtype": "lookup",
          "question": "Which variable links files?", "gold_answer": "SEQN", "notes": "",
          "answer": "SEQN.", "human_verdict": "", "human_notes": ""}
QUESTION = {"gold_doc": "nhanes/a.htm", "gold_section": "SEQN",
            "gold_evidence": "nhanes/b.htm#RIDAGEYR", "verify_sql": "SELECT 1"}
RECORDS = [{"doc": "nhanes/a.htm", "section": "Intro", "text": "see SEQN below", "order": 0},
           {"doc": "nhanes/a.htm", "section": "SEQN", "text": "Respondent sequence number",
            "order": 1}]


def test_gold_refs_include_gold_doc_and_evidence():
    assert cards.gold_refs(QUESTION) == [("nhanes/a.htm", "SEQN"), ("nhanes/b.htm", "RIDAGEYR")]


def test_find_sections_puts_heading_matches_first():
    hits = cards.find_sections(RECORDS, "nhanes/a.htm", "SEQN")
    assert [r["section"] for r in hits] == ["SEQN", "Intro"]


def test_card_shows_evidence_sql_result_and_missing_refs():
    sections = {ref: cards.find_sections(RECORDS, *ref) for ref in cards.gold_refs(QUESTION)}
    text = cards.card(SAMPLE, QUESTION, sections, [(1,)])
    assert "Respondent sequence number" in text
    assert "`nhanes/b.htm#RIDAGEYR`\nnot found in the corpus" in text
    assert "SELECT 1" in text and "```\n1\n```" in text
    assert "verdict" not in text.lower()


def test_card_for_unanswerable_states_the_rule_and_sql_errors_show():
    sample = {**SAMPLE, "gold_answer": ""}
    question = {**QUESTION, "gold_doc": "", "gold_evidence": ""}
    text = cards.card(sample, question, {}, "ParserException: bad")
    assert cards.UNANSWERABLE_RULE in text and "(the gold cites no document)" in text
    assert "ERROR: ParserException: bad" in text
