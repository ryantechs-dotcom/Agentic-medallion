"""Shared types for the retriever tool contract (docs/contracts.md section 4, PROPOSED).

Planned:
- Query: {query: str, filters: {source?, table?} | None, k: int}
- RetrievedChunk: {chunk_id, doc, section, text, score} (validate as "retrieved_chunk")
- Retriever protocol: search(query) -> list[RetrievedChunk]
"""
