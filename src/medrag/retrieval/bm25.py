"""Sparse retrieval with rank-bm25 over chunk text (condition 3a)."""

from __future__ import annotations

import re

import numpy as np
from rank_bm25 import BM25Okapi

from medrag.retrieval.base import filter_mask, top_k

_TOKEN = re.compile(r"[a-z0-9_]+")

# NLTK's English stopword list, minus the apostrophe forms (the tokenizer splits on
# apostrophes, so "don't" arrives as "don" + "t", both listed). Inlined to avoid a dependency.
ENGLISH_STOPWORDS = frozenset("""
i me my myself we our ours ourselves you your yours yourself yourselves he him his himself she
her hers herself it its itself they them their theirs themselves what which who whom this that
these those am is are was were be been being have has had having do does did doing a an the
and but if or because as until while of at by for with about against between into through
during before after above below to from up down in out on off over under again further then
once here there when where why how all any both each few more most other some such no nor not
only own same so than too very s t can will just don should now d ll m o re ve y ain aren
couldn didn doesn hadn hasn haven isn ma mightn mustn needn shan shouldn wasn weren won wouldn
""".split())
STOPWORD_LISTS = {"english": ENGLISH_STOPWORDS, "none": frozenset()}


def tokenize(text: str, stopwords: frozenset[str] = frozenset()) -> list[str]:
    """Lowercase word tokens; identifiers are kept whole and also split on underscores.

    `gender_concept_id` -> [gender_concept_id, gender, concept, id], so a query can match
    either the exact column name or its plain-English parts. `DIQ010` stays one token.
    Tokens in `stopwords` are dropped (question words like "what does" otherwise match
    NHANES question labels that start the same way).
    """
    tokens = []
    for token in _TOKEN.findall(text.lower()):
        tokens.append(token)
        parts = [part for part in token.split("_") if part]
        if len(parts) > 1:
            tokens += parts
    return [token for token in tokens if token not in stopwords]


class BM25Retriever:
    """BM25 (Okapi, rank-bm25 defaults k1=1.5, b=0.75) over chunk text."""

    def __init__(self, chunks: list[dict], stopwords: str = "none"):
        if stopwords not in STOPWORD_LISTS:
            raise ValueError(f"unknown stopwords {stopwords!r}; expected one of "
                             f"{sorted(STOPWORD_LISTS)}")
        self.chunks = chunks
        self.stopwords = STOPWORD_LISTS[stopwords]
        self.index = BM25Okapi([tokenize(chunk["text"], self.stopwords) for chunk in chunks])

    def scores(self, query: str) -> np.ndarray:
        """Return one BM25 score per chunk."""
        return np.asarray(self.index.get_scores(tokenize(query, self.stopwords)), dtype=float)

    def search(self, query: str, k: int, filters: dict | None = None) -> list[dict]:
        return top_k(self.chunks, self.scores(query), filter_mask(self.chunks, filters), k)
