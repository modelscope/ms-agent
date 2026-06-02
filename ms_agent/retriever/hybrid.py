# Copyright (c) ModelScope Contributors. All rights reserved.
"""Hybrid retriever that combines N sub-retrievers via pluggable fusion."""
from typing import List, Optional

from .base import BaseRetriever, FusionStrategy, SearchResult
from .fusion import RRFFusion


class HybridRetriever(BaseRetriever):
    """Combine multiple retrievers through a configurable fusion strategy.

    By default uses :class:`RRFFusion`.  Each sub-retriever is expected to
    be indexed with the **same** corpus (calling ``index()`` on the hybrid
    will forward to every sub-retriever).
    """

    def __init__(self, retrievers: List[BaseRetriever], *,
                 fusion: Optional[FusionStrategy] = None):
        if not retrievers:
            raise ValueError("At least one sub-retriever is required")
        self._retrievers = retrievers
        self._fusion: FusionStrategy = fusion or RRFFusion()

    def index(self, documents: List[str],
              doc_ids: Optional[List[str]] = None) -> None:
        for r in self._retrievers:
            r.index(documents, doc_ids)

    def search(self, query: str, top_k: int = 10) -> List[SearchResult]:
        all_results = [
            r.search(query, top_k=top_k * 2) for r in self._retrievers
        ]
        return self._fusion.fuse(all_results)[:top_k]

    def reset(self) -> None:
        for r in self._retrievers:
            r.reset()
