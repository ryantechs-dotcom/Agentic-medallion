"""Load raw documents from data/docs into (doc, text, metadata) records.

Planned:
- load_nhanes(docs_dir): one record per codebook .htm (strip HTML, keep variable headings)
- load_mimic(docs_dir): one record per markdown table page
- load_omop(docs_dir): table-level and field-level CSV rows
Metadata on every record: source, doc (path relative to data/docs), table/file, version/cycle.
"""
