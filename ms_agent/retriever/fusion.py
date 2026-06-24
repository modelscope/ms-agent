# Copyright (c) ModelScope Contributors. All rights reserved.
"""Fusion strategies for merging ranked result lists."""
from collections import defaultdict
from typing import Dict, List

from .base import FusionStrategy, SearchResult


class WeightedFusion(FusionStrategy):
    """Weighted linear combination with min-max normalisation.

    Each retriever's scores are normalised to [0, 1] independently, then
    combined using the supplied *weights* vector.
    """

    def __init__(self, weights: List[float]):
        if not weights:
            raise ValueError("weights must not be empty")
        total = sum(weights)
        self._weights = [w / total for w in weights]

    @staticmethod
    def _normalise(results: List[SearchResult]) -> List[SearchResult]:
        if not results:
            return results
        lo = min(r.score for r in results)
        hi = max(r.score for r in results)
        span = hi - lo
        if span == 0:
            return [SearchResult(r.doc_id, r.text, 1.0, r.metadata)
                    for r in results]
        return [SearchResult(r.doc_id, r.text, (r.score - lo) / span,
                             r.metadata) for r in results]

    def fuse(self, result_lists: List[List[SearchResult]]) -> List[SearchResult]:
        if len(result_lists) != len(self._weights):
            raise ValueError(
                f"Expected {len(self._weights)} result lists, "
                f"got {len(result_lists)}")

        doc_scores: Dict[str, float] = defaultdict(float)
        doc_texts: Dict[str, str] = {}
        doc_meta: Dict[str, dict] = {}

        for weight, results in zip(self._weights, result_lists):
            normed = self._normalise(results)
            for r in normed:
                doc_scores[r.doc_id] += weight * r.score
                doc_texts.setdefault(r.doc_id, r.text)
                if r.metadata:
                    doc_meta.setdefault(r.doc_id, r.metadata)

        merged = [
            SearchResult(doc_id=did, text=doc_texts[did],
                         score=doc_scores[did],
                         metadata=doc_meta.get(did))
            for did in doc_scores
        ]
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged


class RRFFusion(FusionStrategy):
    """Reciprocal Rank Fusion (Cormack et al., 2009).

    ``score(d) = sum_over_retrievers(1 / (k + rank_i(d)))``

    Higher *k* smooths rank differences; the default ``k=60`` is standard.
    """

    def __init__(self, k: int = 60):
        self.k = k

    def fuse(self, result_lists: List[List[SearchResult]]) -> List[SearchResult]:
        doc_scores: Dict[str, float] = defaultdict(float)
        doc_texts: Dict[str, str] = {}
        doc_meta: Dict[str, dict] = {}

        for results in result_lists:
            for rank, r in enumerate(results, start=1):
                doc_scores[r.doc_id] += 1.0 / (self.k + rank)
                doc_texts.setdefault(r.doc_id, r.text)
                if r.metadata:
                    doc_meta.setdefault(r.doc_id, r.metadata)

        merged = [
            SearchResult(doc_id=did, text=doc_texts[did],
                         score=doc_scores[did],
                         metadata=doc_meta.get(did))
            for did in doc_scores
        ]
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged
