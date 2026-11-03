"""Shared types for the retriever tool contract (agreed with Problem 2 - see ARCHITECTURE.md).

Planned:
- Query: {query: str, filters: {source?, table?} | None, k: int}
- RetrievedChunk: {doc, section, text, score}
- Retriever protocol: search(query) -> list[RetrievedChunk]
"""
