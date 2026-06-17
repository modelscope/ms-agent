# Copyright (c) ModelScope Contributors. All rights reserved.
"""Lightweight BM25 retriever -- zero external dependencies beyond stdlib."""
import math
import re
from typing import Dict, List, Optional

from .base import BaseRetriever, SearchResult

_TOKEN_RE = re.compile(r'[\w\u4e00-\u9fff]+', re.UNICODE)


def _tokenize(text: str) -> List[str]:
    """Simple regex tokenizer that handles Latin and CJK characters."""
    return _TOKEN_RE.findall(text.lower())


class BM25Retriever(BaseRetriever):
    """Self-contained BM25 implementation with no heavy dependencies.

    Uses a simple regex tokenizer instead of ``TokenizerUtil`` so that
    ``modelscope`` / Qwen tokenizer downloads are not required.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b

        self._documents: List[str] = []
        self._doc_ids: List[str] = []
        self._tokenized: List[List[str]] = []
        self._idf: Dict[str, float] = {}
        self._doc_len: List[int] = []
        self._doc_term_freqs: List[Dict[str, int]] = []
        self._avgdl: float = 0.0

    # ------------------------------------------------------------------ #
    #  BaseRetriever interface
    # ------------------------------------------------------------------ #

    def index(self, documents: List[str],
              doc_ids: Optional[List[str]] = None) -> None:
        self.reset()
        self._documents = list(documents)
        self._doc_ids = (
            list(doc_ids) if doc_ids else
            [str(i) for i in range(len(documents))])

        self._tokenized = [_tokenize(d) for d in self._documents]
        self._build_stats()

    def search(self, query: str, top_k: int = 10) -> List[SearchResult]:
        if not self._documents:
            return []
        q_tokens = _tokenize(query)
        scores = self._score(q_tokens)

        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        results: List[SearchResult] = []
        for idx, score in ranked[:top_k]:
            if score <= 0:
                break
            results.append(SearchResult(
                doc_id=self._doc_ids[idx],
                text=self._documents[idx],
                score=score,
            ))
        return results

    def reset(self) -> None:
        self._documents.clear()
        self._doc_ids.clear()
        self._tokenized.clear()
        self._idf.clear()
        self._doc_len.clear()
        self._doc_term_freqs.clear()
        self._avgdl = 0.0

    # ------------------------------------------------------------------ #
    #  Internal
    # ------------------------------------------------------------------ #

    def _build_stats(self) -> None:
        n = len(self._tokenized)
        if n == 0:
            return

        doc_freq: Dict[str, int] = {}
        total_len = 0
        for tokens in self._tokenized:
            length = len(tokens)
            self._doc_len.append(length)
            total_len += length

            freqs: Dict[str, int] = {}
            for t in tokens:
                freqs[t] = freqs.get(t, 0) + 1
            self._doc_term_freqs.append(freqs)

            for t in set(tokens):
                doc_freq[t] = doc_freq.get(t, 0) + 1

        self._avgdl = total_len / n
        for word, df in doc_freq.items():
            self._idf[word] = math.log((n - df + 0.5) / (df + 0.5) + 1)

    def _score(self, query_tokens: List[str]) -> List[float]:
        scores = [0.0] * len(self._documents)
        for token in query_tokens:
            idf = self._idf.get(token)
            if idf is None:
                continue
            for i, freqs in enumerate(self._doc_term_freqs):
                tf = freqs.get(token, 0)
                if tf == 0:
                    continue
                dl = self._doc_len[i]
                numer = tf * (self.k1 + 1)
                denom = tf + self.k1 * (
                    1 - self.b + self.b * (dl / self._avgdl))
                scores[i] += idf * (numer / denom)
        return scores
