"""Model calls behind one small backend interface (prompts: docs/contracts.md section 10).

A backend is a function `complete(system, user, schema, settings) -> completion`, where
`settings` holds `model`, `effort`, `timeout_s` and `max_turns`, and the completion is
`{"data": dict | None, "usage": dict, "model": str, "cost_usd": float | None,
"error": str | None}`. `data` is the JSON object the schema asked for.

Backends (`generation.backend` in config):
- `claude_cli`: headless Claude Code (`claude -p`) on the user's Claude seat, no API key.
  Built-in tools, CLAUDE.md, skills, hooks and MCP servers are switched off and it runs from a
  scratch folder outside the repo, so a closed-book run cannot read local files (D-next).
- `fake`: no model call; for dry runs of the pipeline and for tests.

Adding a backend (e.g. the Anthropic API once a key exists) means writing one more `complete`
function and registering it in `BACKENDS`; nothing else changes. Non-Claude providers are out
of scope for this project (future work, D-next).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

Backend = Callable[[str, str, dict, dict], dict]

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
        "abstain": {"type": "boolean"},
    },
    "required": ["answer", "citations", "abstain"],
    "additionalProperties": False,
}

# Removed from the CLI's environment: in `claude -p` an API key outranks the seat login, so a
# key in .env would silently switch billing to the API.
API_KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
CLI_WORKDIR = Path(tempfile.gettempdir()) / "medrag_claude_cli"


def model_settings(config: dict, section: str = "generation") -> dict:
    """Backend settings for generation or the judge (the judge reuses model and backend)."""
    gen = config["generation"]
    own = config.get(section, {}) if section != "generation" else {}
    return {"model": gen["model"], "effort": own.get("effort", gen["effort"]),
            "timeout_s": gen["timeout_s"], "max_turns": gen["max_turns"]}


def format_passages(passages: list[dict]) -> str:
    """Render context passages as `[id]` + text blocks, in the order given."""
    return "\n\n".join(f"[{p['id']}]\n{p['text']}" for p in passages)


def build_user_message(question: str, passages: list[dict] | None) -> str:
    """The user turn: documentation passages (if any), then the question."""
    if not passages:
        return f"No documentation passages are provided.\n\nQuestion: {question}"
    return (f"Documentation passages:\n\n{format_passages(passages)}\n\n"
            f"Question: {question}")


def check_answer(data: object) -> str | None:
    """Return an error message if `data` is not a valid answer object, else None."""
    if not isinstance(data, dict):
        return "answer is not a JSON object"
    if not isinstance(data.get("answer"), str):
        return "answer.answer is not a string"
    citations = data.get("citations")
    if not isinstance(citations, list) or not all(isinstance(c, str) for c in citations):
        return "answer.citations is not a list of strings"
    if not isinstance(data.get("abstain"), bool):
        return "answer.abstain is not true/false"
    return None


def answer(question: str, passages: list[dict] | None, config: dict, prompt: dict,
           backend: Backend) -> dict:
    """Answer one question; returns {answer, citations, abstained, usage, latency_s, model,
    cost_usd, error}. A backend failure or a malformed answer is an `error`, never raised."""
    start = time.perf_counter()
    result = backend(prompt["text"], build_user_message(question, passages), ANSWER_SCHEMA,
                     model_settings(config))
    latency = round(time.perf_counter() - start, 3)
    out = {"answer": None, "citations": [], "abstained": None, "usage": result["usage"],
           "latency_s": latency, "model": result["model"], "cost_usd": result["cost_usd"],
           "error": result["error"]}
    if out["error"] is None:
        out["error"] = check_answer(result["data"])
    if out["error"] is None:
        data = result["data"]
        out.update(answer=data["answer"], citations=data["citations"],
                   abstained=data["abstain"])
    return out


def get_backend(name: str) -> Backend:
    """Look up a backend by its config name."""
    if name not in BACKENDS:
        raise ValueError(f"unknown backend {name!r}; expected one of {sorted(BACKENDS)}")
    return BACKENDS[name]


# --- claude_cli ---------------------------------------------------------------------------

def cli_command(executable: str, system: str, schema: dict, settings: dict) -> list[str]:
    """Arguments for one isolated, tool-less `claude -p` call (the prompt goes on stdin)."""
    return [
        executable, "-p",
        "--model", settings["model"],
        "--effort", settings["effort"],
        "--system-prompt", system,
        "--tools", "",
        "--json-schema", json.dumps(schema, sort_keys=True),
        "--output-format", "json",
        "--max-turns", str(settings["max_turns"]),
        "--no-session-persistence",
        "--safe-mode",
        "--strict-mcp-config",
    ]


def cli_env(environ: dict) -> dict:
    """The CLI's environment: everything except API keys, so the seat login is used."""
    return {key: value for key, value in environ.items() if key not in API_KEY_VARS}


def parse_cli_output(stdout: str, model: str) -> dict:
    """Turn `claude -p --output-format json` output into a completion.

    Token counts come from `modelUsage[model]` only: Claude Code also makes a small side call
    with another model, which is not part of the answer. `total_cost_usd` (which includes it)
    is kept as `cost_usd`, a list-price estimate, not a bill.
    """
    empty = {"input_tokens": 0, "output_tokens": 0}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {"data": None, "usage": empty, "model": model, "cost_usd": None,
                "error": f"CLI output is not JSON: {stdout[:200]!r}"}
    used = payload.get("modelUsage", {}).get(model, {})
    usage = {
        "input_tokens": (used.get("inputTokens", 0) + used.get("cacheReadInputTokens", 0)
                         + used.get("cacheCreationInputTokens", 0)),
        "output_tokens": used.get("outputTokens", 0),
        "cache_read_input_tokens": used.get("cacheReadInputTokens", 0),
        "thinking_tokens": used.get("thinkingTokens", 0),
        "num_turns": payload.get("num_turns"),
    }
    error = None
    if payload.get("is_error") or payload.get("subtype") != "success":
        status = payload.get("api_error_status")
        error = (f"CLI {payload.get('subtype')} (status {status}): "
                 f"{str(payload.get('result', ''))[:300]}")
    elif not used:
        error = f"model {model!r} not in CLI modelUsage {sorted(payload.get('modelUsage', {}))}"
    data = payload.get("structured_output")
    if error is None and data is None:
        error = "CLI returned no structured_output"
    return {"data": data, "usage": usage, "model": model,
            "cost_usd": payload.get("total_cost_usd"), "error": error}


def claude_cli_complete(system: str, user: str, schema: dict, settings: dict) -> dict:
    """Backend `claude_cli`: one headless Claude Code call on the seat login."""
    executable = shutil.which("claude")
    empty = {"input_tokens": 0, "output_tokens": 0}
    if executable is None:
        return {"data": None, "usage": empty, "model": settings["model"], "cost_usd": None,
                "error": "claude CLI not found on PATH"}
    CLI_WORKDIR.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(cli_command(executable, system, schema, settings), input=user,
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=settings["timeout_s"], cwd=CLI_WORKDIR,
                              env=cli_env(dict(os.environ)), check=False)
    except subprocess.TimeoutExpired:
        return {"data": None, "usage": empty, "model": settings["model"], "cost_usd": None,
                "error": f"CLI timed out after {settings['timeout_s']} s"}
    if proc.returncode != 0 and not proc.stdout.strip():
        return {"data": None, "usage": empty, "model": settings["model"], "cost_usd": None,
                "error": f"CLI exit {proc.returncode}: {proc.stderr.strip()[:300]}"}
    return parse_cli_output(proc.stdout, settings["model"])


# --- fake ---------------------------------------------------------------------------------

def fake_complete(system: str, user: str, schema: dict, settings: dict) -> dict:
    """Backend `fake`: a fixed, schema-valid reply with no model call (dry runs)."""
    if "verdict" in schema.get("properties", {}):
        data = {"verdict": "incorrect", "rationale": "fake backend"}
    else:
        data = {"answer": "fake answer", "citations": [], "abstain": False}
    return {"data": data, "usage": {"input_tokens": 0, "output_tokens": 0},
            "model": "fake", "cost_usd": 0.0, "error": None}


BACKENDS: dict[str, Backend] = {"claude_cli": claude_cli_complete, "fake": fake_complete}
