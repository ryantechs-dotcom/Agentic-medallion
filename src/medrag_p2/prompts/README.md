# Problem 2 prompt templates

One `.txt` file per role and version, e.g. `proposer_v1.txt`, `verifier_v1.txt`,
`single_agent_v1.txt`. Templates are versioned in git and never edited after a run uses them:
copy to `_v2` instead. The single-agent and multi-agent conditions share the same base
instructions, so the comparison tests the architecture rather than the wording.
