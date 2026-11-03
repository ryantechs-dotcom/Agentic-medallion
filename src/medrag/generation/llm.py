"""Thin wrapper around the LLM API (key from .env).

Planned:
- answer(question, chunks, config, tools=None) -> {answer, citations, usage, latency_s}
Model, temperature and prompt_version come from config and are recorded with every output.
"""
