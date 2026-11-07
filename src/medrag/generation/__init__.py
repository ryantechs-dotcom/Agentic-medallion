"""LLM calls and versioned prompt templates (naming rules in docs/contracts.md, section 10)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
PROMPT_NAME_RE = re.compile(r"^p[1-3]_[a-z0-9_]+_v\d+$")


def load_prompt(name: str) -> tuple[str, str]:
    """Return (text, sha256) of prompts/<name>.txt, e.g. load_prompt("p1_answer_v1").

    Record both in the run's config.json so every result points at the exact prompt used.
    """
    if not PROMPT_NAME_RE.match(name):
        raise ValueError(f"prompt name {name!r} must look like p1_answer_v1 "
                         "(<problem>_<purpose>_v<N>)")
    path = PROMPT_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    raw = path.read_bytes()
    return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()
