"""scripts/eval_retrieval.py helpers: fixed-size scan settings, folder suffix, context size."""

import importlib.util

import pytest

from medrag.config import PROJECT_ROOT


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location(
        "eval_retrieval", PROJECT_ROOT / "scripts" / "eval_retrieval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def retrieval(**overrides):
    base = {"chunking": "structure", "bm25_stopwords": "english", "fixed_chunk_tokens": 400,
            "fixed_chunk_overlap": 50}
    return {**base, **overrides}


def test_fixed_tokens_keep_the_configured_overlap_ratio(script):
    for tokens, overlap in ((400, 50), (150, 19), (60, 8)):
        config = retrieval()
        script.apply_fixed_tokens(config, tokens)
        assert config["chunking"] == "fixed"
        assert (config["fixed_chunk_tokens"], config["fixed_chunk_overlap"]) == (tokens, overlap)


def test_run_suffix_marks_size_only_for_a_scan(script):
    assert script.run_suffix(retrieval(), "hybrid", sized=False) == ""
    assert script.run_suffix(retrieval(chunking="fixed"), "hybrid", sized=False) == "_fixed"
    sized = retrieval(chunking="fixed", fixed_chunk_tokens=60)
    assert script.run_suffix(sized, "hybrid", sized=True) == "_fixed60"
    nostop = retrieval(chunking="fixed", fixed_chunk_tokens=60, bm25_stopwords="none")
    assert script.run_suffix(nostop, "bm25", sized=True) == "_fixed60_nostop"
    assert script.run_suffix(nostop, "dense", sized=True) == "_fixed60"


def test_mean_context_words_counts_only_the_top_k(script):
    words = {"a": 10, "b": 20, "c": 300}
    retrieved = [[{"chunk_id": "a"}, {"chunk_id": "b"}, {"chunk_id": "c"}],
                 [{"chunk_id": "b"}, {"chunk_id": "a"}]]
    assert script.mean_context_words(retrieved, words, 2) == 30
    assert script.mean_context_words([], words, 2) is None
