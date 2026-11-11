"""Rubric-based judge for free-text answers, validated against a human-checked sample.

Verdicts: correct, partially_correct, incorrect, abstained. Abstentions are decided by rule,
without a model call: on an unanswerable question abstaining is the right behavior (correct);
on an answerable question it is recorded as `abstained`. Everything else goes to the judge
model, with the gold answer and the reviewer notes (acceptable alternatives).
"""

from __future__ import annotations

from medrag.generation.llm import Backend, model_settings

MODEL_VERDICTS = ("correct", "partially_correct", "incorrect")
VERDICTS = MODEL_VERDICTS + ("abstained",)

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(MODEL_VERDICTS)},
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "rationale"],
    "additionalProperties": False,
}


def judge_message(row: dict, candidate: str) -> str:
    """The judge's user turn: question, gold answer, notes and the candidate answer."""
    gold = row["gold_answer"] or "(empty: the information is not available in the documentation)"
    return (f"Question: {row['question']}\n\n"
            f"Gold answer: {gold}\n\n"
            f"Reviewer notes: {row['notes'] or '(none)'}\n\n"
            f"Candidate answer: {candidate}")


def judge_one(row: dict, output: dict, config: dict, prompt: dict, backend: Backend) -> dict:
    """Judge one run output; returns {qid, verdict, rationale, judged_by, usage, cost_usd,
    error}."""
    base = {"qid": output["qid"], "verdict": None, "rationale": "", "judged_by": None,
            "usage": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0.0, "error": None}
    if output.get("skipped") or output["error"] is not None or output["answer"] is None:
        return {**base, "rationale": "no answer to judge (skipped or error)"}
    if output.get("abstained"):
        unanswerable = row["qtype"] == "unanswerable"
        return {**base, "verdict": "correct" if unanswerable else "abstained",
                "rationale": "abstained", "judged_by": "rule"}
    result = backend(prompt["text"], judge_message(row, output["answer"]), JUDGE_SCHEMA,
                     model_settings(config, "judge"))
    data = result["data"]
    error = result["error"]
    if error is None and (not isinstance(data, dict)
                          or data.get("verdict") not in MODEL_VERDICTS):
        error = f"judge returned an invalid verdict: {data!r}"[:300]
    if error is not None:
        return {**base, "usage": result["usage"], "cost_usd": result["cost_usd"],
                "error": error}
    return {**base, "verdict": data["verdict"], "rationale": str(data.get("rationale", "")),
            "judged_by": "model", "usage": result["usage"], "cost_usd": result["cost_usd"]}
