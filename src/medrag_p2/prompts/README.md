# Problem 2 prompt templates

One `.txt` file per role and version, e.g. `proposer_v1.txt`, `verifier_v1.txt`,
`single_agent_v1.txt`. Templates are versioned in git and never edited after a run uses them:
copy to `_v2` instead. The single-agent and multi-agent conditions share the same base
instructions, so the comparison tests the architecture rather than the wording.

Load with `medrag.generation.load_prompt("proposer_v1", medrag_p2.PROMPT_DIR)`, which returns
the file, text and sha256 for the run's `config.json` (docs/contracts.md section 10).
