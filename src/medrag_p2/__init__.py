"""medrag_p2 - Problem 2: schema mapping and Silver spec generation, single- vs. multi-agent.

Consumes `medrag.db` (read-only data) and `medrag.retrieval` (retriever tool contract in
docs/contracts.md section 4); does not modify them. Owner: Skylar.
"""

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"   # for medrag.generation.load_prompt
