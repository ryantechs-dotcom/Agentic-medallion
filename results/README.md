# results/

One folder per experiment run: `results/<YYYY-MM-DD>_<pN>_<condition>/` (e.g.
`2026-11-10_p1_c1_closed_book/`) containing `config.json` (merged config plus git commit,
prompt files and sha256s, corpus sha256, snapshot version, eval split), `outputs.jsonl` (one line
per question) and `metrics.json`. Field definitions: `docs/contracts.md` section 9.
Numbers in the report must come from files here.

Run folders are gitignored: like `data/`, they live on the team Drive. `python scripts/sync_drive.py`
copies your problem's runs to `04_results/<pN>/` (`MEDRAG_PROBLEM` in `.env`); download
teammates' runs from there.
