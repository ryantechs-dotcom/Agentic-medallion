"""Generation layer and judge with fake backends (no model calls, no network)."""

import json

import pytest

from medrag.config import load_config
from medrag.evaluation.judge import JUDGE_SCHEMA, judge_message, judge_one
from medrag.generation import load_prompt
from medrag.generation.llm import (ANSWER_SCHEMA, API_KEY_VARS, BACKENDS, answer,
                                   build_user_message, check_answer, cli_command, cli_env,
                                   fake_complete, get_backend, model_settings,
                                   parse_cli_output)

MODEL = "claude-opus-5-5"
PASSAGE = {"id": "nhanes/2017-2018_DIQ_J.htm#DIQ010", "doc": "nhanes/2017-2018_DIQ_J.htm",
           "section": "DIQ010", "text": "DIQ010 - Doctor told you have diabetes\n9 | Don't know"}


def cli_payload(**overrides) -> str:
    """A trimmed `claude -p --output-format json` result, as seen in a real probe call."""
    payload = {
        "type": "result", "subtype": "success", "is_error": False, "num_turns": 2,
        "api_error_status": None, "total_cost_usd": 0.0173,
        "result": '{"answer": "Don\'t know", "citations": [], "abstain": false}',
        "structured_output": {"answer": "Don't know", "citations": [], "abstain": False},
        "modelUsage": {
            "claude-haiku-5-5": {"inputTokens": 1216, "outputTokens": 22},
            MODEL: {"inputTokens": 2, "outputTokens": 269, "cacheReadInputTokens": 0,
                    "cacheCreationInputTokens": 1474, "thinkingTokens": 69},
        },
    }
    payload.update(overrides)
    return json.dumps(payload)


def backend_returning(data, error=None):
    calls = []

    def complete(system, user, schema, settings):
        calls.append({"system": system, "user": user, "schema": schema, "settings": settings})
        return {"data": data, "usage": {"input_tokens": 10, "output_tokens": 5},
                "model": MODEL, "cost_usd": 0.01, "error": error}
    complete.calls = calls
    return complete


def test_config_has_no_temperature_and_a_known_backend():
    gen = load_config()["generation"]
    assert "temperature" not in gen
    assert gen["backend"] in BACKENDS
    assert get_backend("fake") is fake_complete
    with pytest.raises(ValueError):
        get_backend("openai")


def test_model_settings_judge_reuses_model_with_its_own_effort():
    config = {"generation": {"model": MODEL, "effort": "high", "timeout_s": 5, "max_turns": 3},
              "judge": {"effort": "low"}}
    assert model_settings(config)["effort"] == "high"
    judge = model_settings(config, "judge")
    assert judge["model"] == MODEL and judge["effort"] == "low"


def test_user_message_with_and_without_passages():
    closed = build_user_message("What is DIQ010?", None)
    assert "No documentation passages" in closed and closed.endswith("What is DIQ010?")
    rag = build_user_message("What is DIQ010?", [PASSAGE])
    assert "[nhanes/2017-2018_DIQ_J.htm#DIQ010]\nDIQ010 - Doctor" in rag


@pytest.mark.parametrize("data", [
    None, "text", {"answer": 1, "citations": [], "abstain": False},
    {"answer": "x", "citations": "a", "abstain": False},
    {"answer": "x", "citations": [], "abstain": "no"},
])
def test_check_answer_rejects_malformed(data):
    assert check_answer(data) is not None


def test_answer_success_and_failure_never_raise():
    config = load_config()
    prompt = {"text": "SYSTEM"}
    ok = answer("q", [PASSAGE], config, prompt,
                backend_returning({"answer": "Don't know", "citations": [PASSAGE["id"]],
                                   "abstain": False}))
    assert ok["error"] is None and ok["citations"] == [PASSAGE["id"]]
    assert ok["abstained"] is False and ok["usage"]["input_tokens"] == 10
    bad = answer("q", None, config, prompt, backend_returning({"answer": 3}))
    assert bad["answer"] is None and "not a string" in bad["error"]
    failed = answer("q", None, config, prompt, backend_returning(None, error="CLI timed out"))
    assert failed["error"] == "CLI timed out"


def test_answer_sends_prompt_schema_and_settings():
    backend = backend_returning({"answer": "a", "citations": [], "abstain": True})
    answer("q", None, load_config(), {"text": "SYSTEM"}, backend)
    call = backend.calls[0]
    assert call["system"] == "SYSTEM" and call["schema"] == ANSWER_SCHEMA
    assert call["settings"]["model"] == load_config()["generation"]["model"]


def test_cli_command_is_isolated_and_tool_less():
    settings = {"model": MODEL, "effort": "high", "timeout_s": 5, "max_turns": 3}
    cmd = cli_command("claude", "SYSTEM", ANSWER_SCHEMA, settings)
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--system-prompt") + 1] == "SYSTEM"
    assert cmd[cmd.index("--model") + 1] == MODEL
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == ANSWER_SCHEMA
    for flag in ("--safe-mode", "--strict-mcp-config", "--no-session-persistence"):
        assert flag in cmd


def test_cli_env_drops_api_keys_so_the_seat_is_used():
    env = cli_env({"PATH": "x", **{key: "secret" for key in API_KEY_VARS}})
    assert env == {"PATH": "x"}


def test_parse_cli_output_counts_only_the_answering_model():
    result = parse_cli_output(cli_payload(), MODEL)
    assert result["error"] is None
    assert result["data"]["answer"] == "Don't know"
    assert result["usage"]["input_tokens"] == 2 + 1474     # haiku side call excluded
    assert result["usage"]["output_tokens"] == 269
    assert result["cost_usd"] == 0.0173


@pytest.mark.parametrize("stdout, fragment", [
    ("not json", "not JSON"),
    (cli_payload(is_error=True, subtype="error_during_execution", api_error_status=429,
                 result="rate limited"), "status 429"),
    (cli_payload(structured_output=None), "no structured_output"),
    (cli_payload(modelUsage={"claude-haiku-5-5": {}}), "not in CLI modelUsage"),
])
def test_parse_cli_output_errors(stdout, fragment):
    assert fragment in parse_cli_output(stdout, MODEL)["error"]


def test_prompts_exist_and_load():
    for name in ("answer_v1", "answer_v2", "judge_v1"):
        prompt = load_prompt(name)
        assert prompt["text"].strip() and len(prompt["sha256"]) == 64


ROW = {"qid": "NH-001", "qtype": "lookup", "question": "What does DIQ010 = 9 mean?",
       "gold_answer": "Don't know", "notes": ""}


def output(**overrides):
    base = {"qid": "NH-001", "answer": "Don't know", "abstained": False, "error": None,
            "skipped": None}
    return {**base, **overrides}


def test_judge_rules_for_abstention_and_missing_answers():
    config, prompt = load_config(), {"text": "J"}
    never = backend_returning(None, error="should not be called")
    unanswerable = {**ROW, "qtype": "unanswerable", "gold_answer": ""}
    assert judge_one(unanswerable, output(abstained=True), config, prompt,
                     never)["verdict"] == "correct"
    assert judge_one(ROW, output(abstained=True), config, prompt,
                     never)["verdict"] == "abstained"
    skipped = judge_one(ROW, output(answer=None, skipped="no gold"), config, prompt, never)
    assert skipped["verdict"] is None and skipped["error"] is None
    assert never.calls == []


def test_judge_model_verdict_and_invalid_verdict():
    config, prompt = load_config(), {"text": "J"}
    good = backend_returning({"verdict": "correct", "rationale": "matches"})
    result = judge_one(ROW, output(), config, prompt, good)
    assert result["verdict"] == "correct" and result["judged_by"] == "model"
    assert good.calls[0]["schema"] == JUDGE_SCHEMA
    assert "Gold answer: Don't know" in good.calls[0]["user"]
    bad = judge_one(ROW, output(), config, prompt, backend_returning({"verdict": "maybe"}))
    assert bad["verdict"] is None and "invalid verdict" in bad["error"]


def test_judge_message_marks_empty_gold():
    text = judge_message({**ROW, "gold_answer": "", "notes": "not released"}, "employer")
    assert "not available in the documentation" in text and "not released" in text
