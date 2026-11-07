"""LLM calls and versioned prompt templates (rules in docs/contracts.md, section 10)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from medrag.config import PROJECT_ROOT

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"     # P1's prompts
PROMPT_NAME_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*_v\d+$")


def load_prompt(name: str, prompts_dir: Path = PROMPT_DIR) -> dict:
    """Return {"file", "text", "sha256"} for <prompts_dir>/<name>.txt.

    `name` looks like `answer_v1` (<purpose>_v<N>). Each problem passes its own folder, e.g.
    `load_prompt("proposer_v1", medrag_p2.PROMPT_DIR)`. Put `file` and `sha256` in the run's
    config.json under `prompts` so every result points at the exact prompt text.
    """
    if not PROMPT_NAME_RE.match(name):
        raise ValueError(f"prompt name {name!r} must look like answer_v1 (<purpose>_v<N>)")
    path = Path(prompts_dir) / f"{name}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found")
    raw = path.read_bytes()
    try:
        file = path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:                      # outside the repo (e.g. a test's temp folder)
        file = path.as_posix()
    return {"file": file, "text": raw.decode("utf-8"), "sha256": hashlib.sha256(raw).hexdigest()}
