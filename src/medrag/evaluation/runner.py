"""Run one condition over an eval split.

Planned:
- run(condition, split): load config + eval/questions.csv, answer each question, write
  results/<YYYY-MM-DD>_<condition>/{config.json, outputs.jsonl, metrics.json}
Refuses split=test unless explicitly confirmed (test split is for final runs only).
"""
