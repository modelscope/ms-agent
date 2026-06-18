# Copyright (c) ModelScope Contributors. All rights reserved.
"""Skill search engine -- thin wrapper over the pluggable retriever framework."""
from typing import List, Optional, Tuple

from ms_agent.retriever.base import BaseRetriever
from ms_agent.retriever.bm25 import BM25Retriever
from ms_agent.utils.logger import get_logger

logger = get_logger()


class SkillSearchEngine:
    """Search over a :class:`SkillCatalog` using pluggable retriever backends.

    Supported *backend* values:

    * ``"bm25"``   -- lightweight, zero heavy deps (default)
    * ``"vector"`` -- FAISS + sentence-transformers (lazy loaded)
    * ``"hybrid"`` -- combines BM25 + vector via configurable fusion
    """

    def __init__(self, catalog, backend: str = 'bm25', **kwargs):
        self._catalog = catalog
        self._backend_name = backend
        self._kwargs = kwargs
        self._retriever: BaseRetriever = self._build_retriever(
            backend, **kwargs)
        self._index_version: int = -1

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def search(self, query: str,
               top_k: int = 10) -> List[Tuple[str, float]]:
        """Return ``(skill_id, score)`` pairs ranked by relevance."""
        self._ensure_indexed()
        results = self._retriever.search(query, top_k=top_k)
        return [(r.doc_id, r.score) for r in results]

    # ------------------------------------------------------------------ #
    #  Internal
    # ------------------------------------------------------------------ #

    def _build_retriever(self, backend: str, **kwargs) -> BaseRetriever:
        if backend == 'bm25':
            return BM25Retriever()
        elif backend == 'vector':
            from ms_agent.retriever.vector import VectorRetriever
            return VectorRetriever(
                embed_model=kwargs.get('embed_model'))
        elif backend == 'hybrid':
            from ms_agent.retriever.vector import VectorRetriever
            from ms_agent.retriever.hybrid import HybridRetriever
            from ms_agent.retriever.fusion import RRFFusion, WeightedFusion

            bm25 = BM25Retriever()
            vector = VectorRetriever(
                embed_model=kwargs.get('embed_model'))

            fusion_name = kwargs.get('fusion', 'rrf')
            if fusion_name == 'rrf':
                fusion = RRFFusion(k=kwargs.get('rrf_k', 60))
            else:
                fusion = WeightedFusion(
                    weights=kwargs.get('weights', [0.3, 0.7]))
            return HybridRetriever([bm25, vector], fusion=fusion)
        else:
            logger.warning(
                f"Unknown search backend '{backend}', falling back to bm25")
            return BM25Retriever()

    def _ensure_indexed(self) -> None:
        """Rebuild the index when the catalog changes."""
        current_version = self._catalog._cache_version
        if self._index_version == current_version:
            return

        skills = self._catalog.get_enabled_skills()
        docs: List[str] = []
        ids: List[str] = []
        for sid, skill in skills.items():
            corpus = (
                f"{skill.name} {skill.description} "
                f"{' '.join(skill.tags or [])} "
                f"{skill.content[:500]}")
            docs.append(corpus)
            ids.append(sid)

        if docs:
            self._retriever.index(docs, ids)
        self._index_version = current_version
