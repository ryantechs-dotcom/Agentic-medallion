"""Read-only SQL tool for condition 4 (RAG + verification).

Planned:
- run_sql(sql, max_rows, timeout_s): SELECT/WITH only (reject anything else before execution),
  runs through medrag.db.connect() (read-only), returns columns + capped rows + truncation flag
- tool schema for the LLM (name, description, input schema)
Limits come from config (verify.max_rows, verify.timeout_s).
"""
