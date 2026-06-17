# Copyright (c) ModelScope Contributors. All rights reserved.
"""Pluggable retriever framework.

Provides standalone BM25, vector, and hybrid retrieval with configurable
fusion strategies (weighted sum, RRF).
"""
from .base import BaseRetriever, FusionStrategy, SearchResult
from .bm25 import BM25Retriever
from .fusion import RRFFusion, WeightedFusion
from .hybrid import HybridRetriever

__all__ = [
    'BaseRetriever',
    'SearchResult',
    'FusionStrategy',
    'BM25Retriever',
    'HybridRetriever',
    'WeightedFusion',
    'RRFFusion',
]

try:
    from .vector import VectorRetriever
    __all__.append('VectorRetriever')
except Exception:
    pass
