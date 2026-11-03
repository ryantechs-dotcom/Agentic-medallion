"""Turn loaded documents into retrievable chunks.

Planned (see docs/PROBLEM1_PLAN.md, "Chunking"):
- chunk_structured(records): natural unit per source (NHANES variable, MIMIC column section,
  OMOP CSV row); keeps metadata so retrieval can be scored against gold_doc/gold_section
- chunk_fixed(records, tokens, overlap): fixed-size ablation; sizes come from config
Chunk schema: {chunk_id, doc, section, source, text, metadata}.
"""
