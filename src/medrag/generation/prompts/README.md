# prompts/ (Problem 1)

One file per prompt version, named `<purpose>_v<N>.txt`, e.g. `answer_v1.txt`, `judge_v1.txt`.
Load with `medrag.generation.load_prompt("answer_v1")`, which returns the file, text and
sha256; record `file` and `sha256` in the run's `config.json` under `prompts`.

Never edit a version that has results in `results/`; copy it to `_v<N+1>` instead, so every run
stays traceable. Other problems keep their prompts in their own package
(`src/medrag_p2/prompts/`, ...). Full rules: `docs/contracts.md`, section 10.
