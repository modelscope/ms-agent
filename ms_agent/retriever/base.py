# Copyright (c) ModelScope Contributors. All rights reserved.
"""Base abstractions for the pluggable retriever framework."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SearchResult:
    """A single search result returned by a retriever."""
    doc_id: str
    text: str
    score: float
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)


class BaseRetriever(ABC):
    """Abstract interface for all retriever backends.

    Implementations must support two operations:
      1. ``index`` -- build an internal search index from a list of documents.
      2. ``search`` -- query the index and return ranked results.
    """

    @abstractmethod
    def index(self, documents: List[str],
              doc_ids: Optional[List[str]] = None) -> None:
        """Build search index from *documents*.

        Args:
            documents: Texts to index.
            doc_ids: Optional identifiers (one per document). When omitted the
                retriever should use ``str(i)`` as the doc_id.
        """

    @abstractmethod
    def search(self, query: str, top_k: int = 10) -> List[SearchResult]:
        """Return up to *top_k* results ranked by relevance (descending)."""

    def reset(self) -> None:
        """Clear the index. Subclasses should override if they hold state."""


class FusionStrategy(ABC):
    """Merge multiple ranked result lists into one."""

    @abstractmethod
    def fuse(self, result_lists: List[List[SearchResult]]) -> List[SearchResult]:
        """Merge *result_lists* (one per retriever) into a single ranked list."""
