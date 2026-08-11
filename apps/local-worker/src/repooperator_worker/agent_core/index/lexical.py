"""Tokenizer and hand-rolled BM25 scoring (stdlib only)."""
from __future__ import annotations

import math
import re
from collections import Counter

from .config import BM25_B, BM25_K1, MAX_TOKENS_PER_FILE

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+|[0-9]+")


def _subtokens(word: str) -> list[str]:
    """Split an identifier into camelCase / snake_case subtokens (lowercased).

    ``getUserId`` -> {getuserid, get, user, id}; ``user_id`` -> {user_id, user, id}.
    The whole token is always included so exact matches still score.
    """
    lowered = word.lower()
    out = {lowered}
    for part in lowered.split("_"):
        if part:
            out.add(part)
    for part in _CAMEL_RE.findall(word):
        piece = part.lower()
        if piece:
            out.add(piece)
    return [t for t in out if t]


def tokenize(text: str) -> Counter:
    """Return term-frequency Counter for ``text`` (capped at MAX_TOKENS_PER_FILE)."""
    tf: Counter = Counter()
    seen = 0
    for match in _WORD_RE.finditer(text):
        if seen >= MAX_TOKENS_PER_FILE:
            break
        seen += 1
        for tok in _subtokens(match.group(0)):
            tf[tok] += 1
    return tf


def query_terms(query: str) -> list[str]:
    """Distinct terms for a query string, using the same subtoken expansion."""
    terms: list[str] = []
    for match in _WORD_RE.finditer(query):
        for tok in _subtokens(match.group(0)):
            if tok not in terms:
                terms.append(tok)
    return terms


def idf(n_docs: int, df: int) -> float:
    """BM25 idf with the standard +0.5 smoothing; clamped non-negative."""
    if df <= 0:
        return 0.0
    return max(0.0, math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5)))


def bm25_term_score(*, tf: int, df: int, n_docs: int, doc_len: int, avg_len: float) -> float:
    """BM25 contribution of a single term occurring ``tf`` times in a doc."""
    if tf <= 0 or n_docs <= 0:
        return 0.0
    denom = tf + BM25_K1 * (1.0 - BM25_B + BM25_B * (doc_len / avg_len if avg_len > 0 else 1.0))
    if denom <= 0:
        return 0.0
    return idf(n_docs, df) * (tf * (BM25_K1 + 1.0)) / denom
