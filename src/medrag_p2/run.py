"""Run one P2 architecture over the ground-truth tables of a split and score it.

    python -m medrag_p2.run --arch single --split dev            # #14
    python -m medrag_p2.run --arch multi --split dev             # #15
    python -m medrag_p2.run --arch multi --split dev --backend fake   # dry run, no model
    python -m medrag_p2.run --arch single --split test --repeat 2 --confirm-test   # final (#18)
    python -m medrag_p2.run --rescore results/<run folder>      # recompute metrics.json

Writes results/<YYYY-MM-DD>_p2_<arch>_<split>_r<repeat>[_fake]/ (docs/contracts.md section 9):
config.json (merged config, git state, prompt and ground-truth sha256), outputs.jsonl (one
`run_output` line per table, with its specs) and metrics.json (medrag_p2.scoring).

Guards, so report numbers stay traceable:
- D16: a real run needs the frozen eval/p2/p2_ground_truth.csv; fake runs use the draft.
- The test split needs --confirm-test (final runs only).
- A real run refuses uncommitted changes under src/, configs/, scripts/, eval/ unless
  --allow-dirty (recorded), as P1's runner does.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from medrag import contracts, db
from medrag.config import PROJECT_ROOT, load_config
from medrag.evaluation.runner import (append_jsonl, corpus_sha256, git_state, read_jsonl,
                                      require_clean_tree, write_json, write_jsonl)
from medrag.generation import load_prompt
from medrag.generation.llm import get_backend, model_settings
from medrag_p2 import PROMPT_DIR
from medrag_p2.agents import ARCHITECTURES, Backend
from medrag_p2.scoring import score_run
from medrag_p2.tools import guard_problem, make_caller

ROLES = {"single": ("base", "single"), "multi": ("base", "retriever", "proposer", "verifier")}


def fake_complete(system: str, user: str, schema: dict, settings: dict) -> dict:
    """Backend for dry runs: finish at once with an empty output (no model call)."""
    key = next(iter(schema["properties"]["output"]["properties"]))
    return {"data": {"action": "finish", "tool": "", "tool_input_json": "",
                     "output": {key: []}},
            "usage": {"input_tokens": 0, "output_tokens": 0}, "model": "fake",
            "cost_usd": 0.0, "error": None}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_ground_truth(p2: dict, real: bool) -> tuple[list[dict], Path]:
    """The frozen ground truth; the draft only for fake runs (D16)."""
    frozen = PROJECT_ROOT / p2["ground_truth"]
    if frozen.is_file():
        path = frozen
    elif real:
        raise PermissionError(f"D16: freeze {p2['ground_truth']} (review, sha256 in "
                              "DECISIONS.md) before any real #14/#15 run")
    else:
        path = PROJECT_ROOT / p2["draft_ground_truth"]
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh)), path


def split_tables(rows: list[dict], split: str, only: list[str] | None) -> list[tuple[str, str]]:
    """(schema, table) pairs of a split, in ground-truth order; `only` narrows them."""
    tables = list(dict.fromkeys((r["source_schema"], r["source_table"])
                                for r in rows if r["split"] == split))
    if only:
        unknown = set(only) - {t for _, t in tables}
        if unknown:
            raise ValueError(f"tables not in the {split} split: {sorted(unknown)}")
        tables = [st for st in tables if st[1] in only]
    return tables


def describe_table(con, schema: str, table: str) -> dict:
    """What every agent is told about a table: its columns, types and row count."""
    cols = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
        [schema, table]).fetchall()
    n_rows = con.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"').fetchone()[0]
    return {"schema": schema, "table": table, "n_rows": n_rows,
            "columns": [{"name": c, "dtype": t} for c, t in cols]}


def lazy_tools(config: dict):
    """Ryan's tool runner, built on first use (the corpus and retriever load slowly, and a
    fake run never calls a tool)."""
    state: dict = {}

    def call(name: str, args: dict) -> dict:
        if "context" not in state:
            from medrag.corpus.chunking import load_records
            from medrag.retrieval import build_retriever
            from medrag.tools import ToolContext
            records = load_records(PROJECT_ROOT / config["paths"]["corpus_file"])
            state["context"] = ToolContext(build_retriever(config), records, config)
        from medrag.tools import call_tool
        return call_tool(name, args, state["context"])
    return call


def doc_sections(config: dict) -> set[tuple[str, str]]:
    """(doc, section) of every corpus record, for evidence validity; empty without a corpus."""
    path = PROJECT_ROOT / config["paths"]["corpus_file"]
    if not path.is_file():
        return set()
    from medrag.corpus.chunking import load_records
    return {(r["doc"], r["section"]) for r in load_records(path)}


def sql_checker(config: dict):
    from medrag.verify.sql_tool import run_sql

    def ok(sql: str) -> bool:
        if guard_problem("run_sql", {"sql": sql}, config["p2"]):
            return False
        return run_sql(sql, 1, config["verify"]["timeout_s"])["error"] is None
    return ok


def output_line(table: dict, result: dict, latency_s: float) -> dict:
    """One `run_output` line (contract 9) with the P2 fields next to it."""
    retrieved = [r for call in result["tool_calls"] for r in call.get("retrieved", [])]
    line = {"qid": f"{table['schema']}.{table['table']}", "table": table["table"],
            "answer": None, "citations": [], "retrieved": retrieved,
            "latency_s": latency_s, **result}
    for call in line["tool_calls"]:
        call.pop("retrieved", None)
    return contracts.validate(line, "run_output")


def run_name(arch: str, split: str, repeat: int, fake: bool) -> str:
    return f"{date.today():%Y-%m-%d}_p2_{arch}_{split}_r{repeat}" + ("_fake" if fake else "")


def run(arch: str, split: str = "dev", *, tables: list[str] | None = None, repeat: int = 1,
        backend_name: str | None = None, backend: Backend | None = None,
        confirm_test: bool = False, allow_dirty: bool = False, overwrite: bool = False,
        run_dir: Path | None = None) -> Path:
    """Run `arch` on every table of `split`; returns the run folder."""
    if arch not in ARCHITECTURES:
        raise ValueError(f"unknown architecture {arch!r}; expected {sorted(ARCHITECTURES)}")
    if split == "test" and not confirm_test:
        raise PermissionError("the test split is for final runs only; pass confirm_test")
    config = load_config("p2")
    p2 = config["p2"]
    backend_name = backend_name or config["generation"]["backend"]
    fake = backend_name == "fake"
    real = backend is None and not fake
    if backend is None:
        backend = fake_complete if fake else get_backend(backend_name)
    gt_rows, gt_path = load_ground_truth(p2, real)
    state = git_state()
    if real and not allow_dirty:
        require_clean_tree(state, "run")
    prompts = {role: load_prompt(p2["prompts"][role], PROMPT_DIR) for role in ROLES[arch]}
    con = db.connect()
    todo = [describe_table(con, s, t) for s, t in split_tables(gt_rows, split, tables)]
    con.close()

    run_dir = run_dir or PROJECT_ROOT / config["paths"]["results_dir"] / run_name(
        arch, split, repeat, fake)
    if run_dir.exists() and not overwrite:
        raise FileExistsError(f"{run_dir.name} exists; pass overwrite to replace it")
    run_dir.mkdir(parents=True, exist_ok=True)
    corpus = PROJECT_ROOT / config["paths"]["corpus_file"]
    write_json(run_dir / "config.json", {
        **config, "architecture": arch, "split": split, "repeat": repeat,
        "tables": [t["table"] for t in todo], **state, "allow_dirty": allow_dirty,
        "backend_name": backend_name, "snapshot": "v1",
        "prompts": {role: {"file": p["file"], "sha256": p["sha256"]}
                    for role, p in prompts.items()},
        "ground_truth": {"file": gt_path.relative_to(PROJECT_ROOT).as_posix(),
                         "sha256": file_sha256(gt_path)},
        "corpus_sha256": corpus_sha256(config) if corpus.is_file() else None,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    outputs_path = run_dir / "outputs.jsonl"
    write_jsonl(outputs_path, [])

    caller = make_caller(lazy_tools(config), p2)
    settings = model_settings(config)
    for table in todo:
        start = datetime.now(timezone.utc)
        result = ARCHITECTURES[arch](table, prompts, backend, settings, caller, p2)
        latency = (datetime.now(timezone.utc) - start).total_seconds()
        append_jsonl(outputs_path, output_line(table, result, round(latency, 3)))
    rescore(run_dir, gt_rows=[r for r in gt_rows if r["split"] == split], config=config)
    return run_dir


def rescore(run_dir: Path, gt_rows: list[dict] | None = None,
            config: dict | None = None) -> dict:
    """(Re)write metrics.json from outputs.jsonl and the ground truth the run recorded."""
    stored = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    config = config or load_config("p2")
    if gt_rows is None:
        path = PROJECT_ROOT / stored["ground_truth"]["file"]
        if file_sha256(path) != stored["ground_truth"]["sha256"]:
            raise ValueError(f"{path.name} changed since the run; can't rescore against it")
        with path.open(encoding="utf-8", newline="") as fh:
            gt_rows = [r for r in csv.DictReader(fh) if r["split"] == stored["split"]]
    metrics = score_run(read_jsonl(run_dir / "outputs.jsonl"), gt_rows, doc_sections(config),
                        sql_checker(config), config["p2"]["top_k"])
    metrics["ground_truth"] = stored["ground_truth"]
    write_json(run_dir / "metrics.json", metrics)
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arch", choices=sorted(ARCHITECTURES))
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--tables", help="comma-separated subset of the split's tables")
    parser.add_argument("--repeat", type=int, default=1, help="repeat number (1-3 for #18)")
    parser.add_argument("--backend", help="override generation.backend (claude_cli | fake)")
    parser.add_argument("--confirm-test", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--rescore", type=Path, help="recompute metrics.json of a run folder")
    args = parser.parse_args(argv)
    if args.rescore:
        metrics = rescore(args.rescore)
    else:
        if not args.arch:
            parser.error("--arch is required")
        run_dir = run(args.arch, args.split,
                      tables=args.tables.split(",") if args.tables else None,
                      repeat=args.repeat, backend_name=args.backend,
                      confirm_test=args.confirm_test, allow_dirty=args.allow_dirty,
                      overwrite=args.overwrite)
        print(run_dir)
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    print(json.dumps({k: metrics["overall"][k] for k in
                      ("precision", "recall", "f1", "top1_accuracy")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
