"""Turn loaded documents into retrievable chunks.

Planned (see docs/PROBLEM1_PLAN.md, "Chunking"):
- chunk_structured(records): about one chunk per corpus record (records are already the
  natural unit per source); split records longer than the token limit into parts
- chunk_fixed(records, tokens, overlap): fixed-size ablation; re-join each doc's records in
  `order`, then window; sizes come from config
Input: corpus records (corpus/corpus_v1.jsonl). Chunk schema: docs/contracts.md section 3.
"""
