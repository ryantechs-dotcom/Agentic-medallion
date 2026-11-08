"""Turn corpus records into retrievable chunks (docs/contracts.md section 3).

- `chunk_structured`: one chunk per corpus record (records are already each source's natural
  unit); a record longer than `max_tokens` is split on line boundaries into `#part<n>` chunks,
  each repeating the record's title line so a part still says what it is about.
- `chunk_fixed`: the fixed-size ablation; each doc's records are re-joined in `order` and cut
  into windows of `tokens` with `overlap`.

"Tokens" are whitespace-separated words: model-agnostic and deterministic (DECISIONS D-next).
"""

from __future__ import annotations

import json
from pathlib import Path

from medrag import contracts


def load_records(path: Path) -> list[dict]:
    """Read a corpus JSONL file and validate every record."""
    with Path(path).open(encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    return contracts.validate_all(records, "corpus_record")


def n_tokens(text: str) -> int:
    """Count whitespace-separated words."""
    return len(text.split())


def _chunk(record: dict, chunk_id: str, text: str, strategy: str, **extra) -> dict:
    return {
        "chunk_id": chunk_id, "record_id": record["id"], "doc": record["doc"],
        "section": record["section"], "source": record["source"], "strategy": strategy,
        "text": text,
        "metadata": {**record["metadata"], "chunk_tokens": n_tokens(text), **extra},
    }


def split_lines(text: str, max_tokens: int) -> list[str]:
    """Split text into parts of at most `max_tokens`, cutting only between lines.

    The first line (the record title) starts every part. A single line longer than the limit
    is cut between words, since there is no line boundary inside it.
    """
    title, _, body = text.partition("\n")
    budget = max(max_tokens - n_tokens(title), 1)
    parts, current, size = [], [], 0
    for line in body.split("\n"):
        pieces = [line]
        if n_tokens(line) > budget:
            words = line.split()
            pieces = [" ".join(words[i:i + budget]) for i in range(0, len(words), budget)]
        for piece in pieces:
            if current and size + n_tokens(piece) > budget:
                parts.append(current)
                current, size = [], 0
            current.append(piece)
            size += n_tokens(piece)
    if current:
        parts.append(current)
    return ["\n".join([title, *part]) for part in parts]


def chunk_structured(records: list[dict], max_tokens: int) -> list[dict]:
    """Return one chunk per record, splitting records longer than `max_tokens`."""
    chunks = []
    for record in records:
        if n_tokens(record["text"]) <= max_tokens:
            chunks.append(_chunk(record, record["id"], record["text"], "structure"))
            continue
        for n, part in enumerate(split_lines(record["text"], max_tokens), 1):
            chunks.append(_chunk(record, f"{record['id']}#part{n}", part, "structure"))
    return contracts.validate_all(chunks, "chunk")


def chunk_fixed(records: list[dict], tokens: int, overlap: int) -> list[dict]:
    """Return fixed-size word windows over each doc's records, joined in `order`."""
    if not 0 <= overlap < tokens:
        raise ValueError(f"need 0 <= overlap < tokens, got overlap={overlap}, tokens={tokens}")
    by_doc: dict[str, list[dict]] = {}
    for record in sorted(records, key=lambda r: r["order"]):
        by_doc.setdefault(record["doc"], []).append(record)
    chunks = []
    for doc, doc_records in by_doc.items():
        words, owner = [], []          # owner[i] = index of the record word i came from
        for i, record in enumerate(doc_records):
            record_words = record["text"].split()
            words += record_words
            owner += [i] * len(record_words)
        step = tokens - overlap
        for n, start in enumerate(range(0, max(len(words) - overlap, 1), step), 1):
            first = doc_records[owner[start]]
            text = " ".join(words[start:start + tokens])
            chunks.append(_chunk(first, f"{doc}@{n}", text, "fixed", overlap=overlap))
    return contracts.validate_all(chunks, "chunk")


def make_chunks(records: list[dict], retrieval_config: dict) -> list[dict]:
    """Chunk records with the strategy and sizes in the `retrieval` config section."""
    strategy = retrieval_config["chunking"]
    if strategy == "structure":
        return chunk_structured(records, retrieval_config["max_chunk_tokens"])
    if strategy == "fixed":
        return chunk_fixed(records, retrieval_config["fixed_chunk_tokens"],
                           retrieval_config["fixed_chunk_overlap"])
    raise ValueError(f"unknown chunking {strategy!r}; expected structure or fixed")
