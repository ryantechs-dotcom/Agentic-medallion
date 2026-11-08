# results/

One folder per experiment run: `results/<YYYY-MM-DD>_<pN>_<condition>/` (e.g.
`2026-11-10_p1_c1_closed_book/`) containing `config.json` (merged config plus git commit,
prompt files and sha256s, corpus sha256, snapshot version, eval split), `outputs.jsonl` (one line
per question) and `metrics.json`. Field definitions: `docs/contracts.md` section 9.
Numbers in the report must come from files here.
