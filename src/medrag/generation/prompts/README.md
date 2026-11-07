# prompts/

One file per prompt version, named `<problem>_<purpose>_v<N>.txt`, e.g. `p1_answer_v1.txt`,
`p1_judge_v1.txt`, `p2_proposer_v1.txt`. Load with `medrag.generation.load_prompt(name)`, which
returns the text and its sha256; record both in the run's `config.json`.

Never edit a version that has results in `results/`; copy it to `_v<N+1>` instead, so every run
stays traceable. Full rules: `docs/contracts.md`, section 10.
