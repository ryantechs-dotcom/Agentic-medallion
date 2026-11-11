"""Run one P1 condition over an eval split and write its run log (docs/contracts.md section 9).

    run("c1_closed_book", "dev")  ->  results/<YYYY-MM-DD>_p1_c1_closed_book/
        config.json     merged config, git commit, prompt sha256, corpus sha256, split
        outputs.jsonl   one `run_output` line per question, written as each one finishes
        metrics.json    answer metrics by qtype, source, needs_data, guessable
    judge_run(run_dir)  ->  judgments.jsonl, then metrics.json again with accuracy

Conditions (`condition.context` in configs/c*.yaml): `none` (closed-book), `gold_docs` (the
whole gold document plus gold_evidence documents; unanswerable rows are skipped) and
`retrieval` (top `retrieval.k` chunks). The test split is refused unless `confirm_test`.
A run stops after `generation.max_consecutive_errors` failures in a row (e.g. the seat's usage
window ran out); `resume=True` keeps finished answers and redoes only the missing or failed ones.
"""

from __future__ import annotations

import csv
import json
import subprocess
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

from medrag import contracts
from medrag.config import PROJECT_ROOT, load_config
from medrag.corpus.chunking import load_records
from medrag.evaluation.judge import judge_one
from medrag.evaluation.metrics import GROUP_KEYS, answer_metrics, citation_check, group_by
from medrag.generation import load_prompt
from medrag.generation.llm import Backend, answer, get_backend
from medrag.retrieval import Retriever, build_retriever, search_docs

CONDITIONS = ("c1_closed_book", "c2_long_context", "c3_rag")
CONTEXT_KINDS = ("none", "gold_docs", "retrieval")
# These sections must match when resuming, or old and new answers would not be comparable
RESUME_KEYS = ("generation", "retrieval", "condition", "split", "prompts")


def git_commit() -> str:
    """Short hash of HEAD, or "unknown" outside a git checkout."""
    proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                          text=True, cwd=PROJECT_ROOT, check=False)
    return proc.stdout.strip() or "unknown"


def load_eval_rows(config: dict, split: str) -> list[dict]:
    """All eval rows of one split, in file order."""
    with (PROJECT_ROOT / config["paths"]["eval_file"]).open(encoding="utf-8", newline="") as f:
        return [row for row in csv.DictReader(f) if row["split"] == split]


def corpus_sha256(config: dict) -> str:
    """sha256 of the corpus file, from its manifest next to it."""
    corpus = PROJECT_ROOT / config["paths"]["corpus_file"]
    manifest = corpus.with_name(corpus.name.replace(".jsonl", ".manifest.json"))
    return json.loads(manifest.read_text(encoding="utf-8"))["sha256"]


def group_records(records: list[dict]) -> dict[str, list[dict]]:
    """Corpus records grouped by doc, each list in document order."""
    by_doc: dict[str, list[dict]] = {}
    for record in sorted(records, key=lambda r: (r["doc"], r["order"])):
        by_doc.setdefault(record["doc"], []).append(record)
    return by_doc


def evidence_docs(row: dict) -> list[str]:
    """gold_doc followed by the other documents named in gold_evidence (`doc#section;...`)."""
    docs = [row["gold_doc"]] if row["gold_doc"] else []
    for ref in filter(None, (part.strip() for part in row["gold_evidence"].split(";"))):
        doc = ref.split("#", 1)[0]
        if doc not in docs:
            docs.append(doc)
    return docs


def doc_passages(docs: list[str], by_doc: dict[str, list[dict]]) -> list[dict]:
    """Every record of each doc as a passage `{id, doc, section, text}`."""
    missing = [doc for doc in docs if doc not in by_doc]
    if missing:
        raise ValueError(f"gold docs not in the corpus: {missing}")
    return [{"id": r["id"], "doc": r["doc"], "section": r["section"], "text": r["text"]}
            for doc in docs for r in by_doc[doc]]


def build_context(row: dict, kind: str, k: int, by_doc: dict | None,
                  retriever: Retriever | None) -> tuple[list[dict], list[dict], str | None]:
    """(passages, retrieved, skip_reason) for one question under one context kind."""
    if kind == "none":
        return [], [], None
    if kind == "gold_docs":
        docs = evidence_docs(row)
        if not docs:
            return [], [], "no gold document (C2 is scored on answerable rows only)"
        return doc_passages(docs, by_doc), [], None
    if kind == "retrieval":
        chunks = search_docs(retriever, row["question"], k)["chunks"]
        passages = [{"id": c["chunk_id"], "doc": c["doc"], "section": c["section"],
                     "text": c["text"]} for c in chunks]
        retrieved = [{"chunk_id": c["chunk_id"], "doc": c["doc"], "section": c["section"],
                      "score": c["score"]} for c in chunks]
        return passages, retrieved, None
    raise ValueError(f"unknown context kind {kind!r}; expected one of {CONTEXT_KINDS}")


def answer_row(row: dict, config: dict, prompt: dict, backend: Backend, by_doc: dict | None,
               retriever: Retriever | None) -> dict:
    """Answer one eval row and return its `run_output` line (validated)."""
    start = time.perf_counter()
    kind = config["condition"]["context"]
    passages, retrieved, skip = build_context(row, kind, config["retrieval"]["k"], by_doc,
                                              retriever)
    out = {"qid": row["qid"], "answer": None, "citations": [], "retrieved": retrieved,
           "tool_calls": [], "usage": {"input_tokens": 0, "output_tokens": 0},
           "latency_s": 0.0, "error": None, "abstained": None, "model": None,
           "cost_usd": None, "citation_hit": None, "invalid_citations": [],
           "n_passages": len(passages), "skipped": skip}
    if skip is None:
        result = answer(row["question"], passages, config, prompt, backend)
        out.update(result)
        hit, invalid = citation_check(result["citations"], passages, row["gold_doc"],
                                      row["gold_section"])
        if result["error"] is None:
            out.update(citation_hit=hit, invalid_citations=invalid)
        # contract: wall-clock for the whole item (retrieval + model call)
        out["latency_s"] = round(time.perf_counter() - start, 3)
    return contracts.validate(out, "run_output")


def run_rows(rows: list[dict], config: dict, prompt: dict, backend: Backend,
             by_doc: dict | None, retriever: Retriever | None,
             write: Callable[[dict], None]) -> tuple[int, bool]:
    """Answer rows in order, passing each output to `write`. Returns (n_done, stopped_early)."""
    limit = config["generation"]["max_consecutive_errors"]
    streak = 0
    for done, row in enumerate(rows, 1):
        out = answer_row(row, config, prompt, backend, by_doc, retriever)
        write(out)
        streak = streak + 1 if out["error"] else 0
        if streak >= limit:
            return done, True
    return len(rows), False


def run_name(config: dict, limit: int | None, backend_name: str) -> str:
    """Run folder name:
    `<date>_p1_<condition>[_<retriever>][_fixed][_<prompt>][_fake][_smokeN]`."""
    name = f"{date.today():%Y-%m-%d}_p1_{config['condition']['name']}"
    if config["condition"]["context"] == "retrieval":
        base = load_config()["retrieval"]
        if config["retrieval"]["kind"] != base["kind"]:
            name += f"_{config['retrieval']['kind']}"
        if config["retrieval"]["chunking"] != base["chunking"]:
            name += f"_{config['retrieval']['chunking']}"
    if config["generation"]["prompt"] != load_config()["generation"]["prompt"]:
        name += f"_{config['generation']['prompt']}"
    if backend_name == "fake":
        name += "_fake"
    if limit:
        name += f"_smoke{limit}"
    return name


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, items: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for item in items:
            f.write(json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, item: dict) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n")


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compute_metrics(run_dir: Path, rows: list[dict]) -> dict:
    """metrics.json content from outputs.jsonl (+ judgments.jsonl if it exists)."""
    by_qid = {row["qid"]: row for row in rows}
    judgments = {j["qid"]: j for j in read_jsonl(run_dir / "judgments.jsonl")}
    items = [{"row": by_qid[o["qid"]], "output": o, "judgment": judgments.get(o["qid"])}
             for o in read_jsonl(run_dir / "outputs.jsonl")]
    metrics = group_by(items, GROUP_KEYS, answer_metrics)
    # same question set for every condition (C2 skips unanswerable rows)
    metrics["answerable"] = answer_metrics([i for i in items
                                            if i["row"]["qtype"] != "unanswerable"])
    metrics["n_questions_in_split"] = len(rows)
    # list-price estimates from the CLI, not a bill (a seat is not charged per call)
    metrics["answer_cost_usd_estimate"] = sum(i["output"].get("cost_usd") or 0.0
                                              for i in items)
    metrics["judge_cost_usd_estimate"] = sum(j.get("cost_usd") or 0.0
                                             for j in judgments.values())
    return metrics


def run(condition: str, split: str = "dev", *, limit: int | None = None,
        backend_name: str | None = None, prompt_name: str | None = None,
        retrieval: dict | None = None,
        run_dir: Path | None = None, resume: bool = False, overwrite: bool = False,
        confirm_test: bool = False, backend: Backend | None = None) -> tuple[Path, bool]:
    """Run one condition; returns (run_dir, complete). See the module docstring."""
    if split == "test" and not confirm_test:
        raise PermissionError("the test split is for final runs only; pass confirm_test")
    config = load_config(condition)
    config["retrieval"].update(retrieval or {})
    if backend_name:
        config["generation"]["backend"] = backend_name
    if prompt_name:
        config["generation"]["prompt"] = prompt_name
    backend_name = config["generation"]["backend"]
    backend = backend or get_backend(backend_name)
    rows = load_eval_rows(config, split)[:limit] if limit else load_eval_rows(config, split)
    prompt = load_prompt(config["generation"]["prompt"])
    run_config = {**config, "split": split, "limit": limit, "git_commit": git_commit(),
                  "prompts": {"answer": {"file": prompt["file"], "sha256": prompt["sha256"]}},
                  "corpus_sha256": corpus_sha256(config), "snapshot": "v1",
                  "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    run_dir = run_dir or PROJECT_ROOT / config["paths"]["results_dir"] / run_name(
        config, limit, backend_name)
    outputs_path = run_dir / "outputs.jsonl"
    kept: list[dict] = []
    if run_dir.exists() and resume:
        stored = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
        changed = [key for key in RESUME_KEYS if stored.get(key) != run_config.get(key)]
        if changed:
            raise ValueError(f"can't resume {run_dir.name}: config changed in {changed}")
        run_config["started_at"] = stored["started_at"]
        run_config["git_commit"] = stored["git_commit"]
        kept = [o for o in read_jsonl(outputs_path) if o["error"] is None]
    elif run_dir.exists() and not overwrite:
        raise FileExistsError(f"{run_dir.name} exists; resume or overwrite it")
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "config.json", run_config)
    write_jsonl(outputs_path, kept)

    kind = config["condition"]["context"]
    by_doc = group_records(load_records(PROJECT_ROOT / config["paths"]["corpus_file"])) \
        if kind == "gold_docs" else None
    retriever = build_retriever(config) if kind == "retrieval" else None
    done = {o["qid"] for o in kept}
    todo = [row for row in rows if row["qid"] not in done]
    if todo:                    # judgments are stale once outputs change; keep them otherwise
        (run_dir / "judgments.jsonl").unlink(missing_ok=True)
    _, stopped = run_rows(todo, config, prompt, backend, by_doc, retriever,
                          lambda out: append_jsonl(outputs_path, out))
    write_json(run_dir / "metrics.json", compute_metrics(run_dir, rows))
    return run_dir, not stopped


def judge_run(run_dir: Path, *, backend: Backend | None = None) -> tuple[dict, bool]:
    """Judge a finished run with the same backend and model; returns (metrics, complete).

    Keeps existing judgments without error, so an interrupted judging pass can be re-run.
    """
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    backend = backend or get_backend(config["generation"]["backend"])
    prompt = load_prompt(config["judge"]["prompt"])
    rows = {row["qid"]: row for row in load_eval_rows(config, config["split"])}
    path = run_dir / "judgments.jsonl"
    kept = {j["qid"]: j for j in read_jsonl(path) if j["error"] is None}
    write_jsonl(path, list(kept.values()))
    streak, stopped = 0, False
    for output in read_jsonl(run_dir / "outputs.jsonl"):
        if output["qid"] in kept:
            continue
        judgment = judge_one(rows[output["qid"]], output, config, prompt, backend)
        append_jsonl(path, judgment)
        streak = streak + 1 if judgment["error"] else 0
        if streak >= config["generation"]["max_consecutive_errors"]:
            stopped = True
            break
    metrics = compute_metrics(run_dir, list(rows.values())[:config["limit"]]
                              if config["limit"] else list(rows.values()))
    metrics["judge"] = {"model": config["generation"]["model"],
                        "effort": config["judge"]["effort"],
                        "backend": config["generation"]["backend"],
                        "prompt": {"file": prompt["file"], "sha256": prompt["sha256"]}}
    write_json(run_dir / "metrics.json", metrics)
    return metrics, not stopped
