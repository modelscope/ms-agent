# flake8: noqa
import enum
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Generic, List, Optional, TypeVar

import json

T = TypeVar('T')


class SearchEngineType(enum.Enum):
    EXA = 'exa'
    SERPAPI = 'serpapi'
    ARXIV = 'arxiv'


@dataclass
class BaseResult:
    """A class representing the base fields of a search result.

    Attributes:
        url (str): The URL of the search result.
        id (str): The temporary ID for the document.
        title (str): The title of the search result.
        highlights (Optional[List[str]]): Highlights from the search result.
        highlight_scores (Optional[List[float]]): Scores for the highlights.
        summary (Optional[str]): A summary of the search result.
        markdown (Optional[str]): Markdown content of the search result.
    """

    url: Optional[str] = None
    id: Optional[str] = None
    title: Optional[str] = None
    highlights: Optional[List[str]] = None
    highlight_scores: Optional[List[float]] = None
    summary: Optional[str] = None
    markdown: Optional[str] = None


@dataclass
class SearchResponse(Generic[T]):
    """Base class for search responses."""

    # A list of search results.
    results: List[T]


class SearchRequest(ABC):
    """Abstract base class for search requests."""

    def __init__(self,
                 query: str,
                 num_results: Optional[int] = 10,
                 **kwargs: Any):
        """
        Initialize SearchRequest with search parameters.

        Args:
            query: The search query string
            num_results: Number of results to return, default is 10
        """
        self.query = query
        self.num_results = num_results
        self._kwargs = kwargs

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Convert the request parameters to a dictionary."""
        pass

    def to_json(self) -> str:
        """
        Convert the request parameters to a JSON string.

        Returns:
            str: The parameters as a JSON string
        """
        return json.dumps(self.to_dict(), ensure_ascii=False)


class SearchResult(ABC):
    """Base class for search results."""

    def __init__(self,
                 query: str,
                 arguments: Optional[Dict[str, Any]] = None,
                 response: Any = None):
        """
        Initialize SearchResult.

        Args:
            query: The original search query string
            arguments: The arguments used for the search
            response: The raw results returned by the search
        """
        self.query = query
        self.arguments = arguments
        self.response = response

    @abstractmethod
    def _process_results(self) -> SearchResponse:
        """
        Process the raw results into a standardized format.

        Returns:
            SearchResponse: Processed search results
        """
        pass

    def to_list(self) -> List[Dict[str, Any]]:
        """
        Convert the search results to a list of dictionaries.
        """

        if not self.response or not self.response.results:
            print('***Warning: No search results found.')
            return []

        if not self.query:
            print('***Warning: No query provided for search results.')
            return []

        res_list: List[Dict[str, Any]] = []
        for res in self.response.results:
            res_list.append({
                'url': res.url,
                'id': res.id,
                'title': res.title,
                'highlights': res.highlights,
                'highlight_scores': res.highlight_scores,
                'summary': res.summary,
                'markdown': res.markdown,
            })

        return res_list

    @staticmethod
    def load_from_disk(file_path: str) -> List[Dict[str, Any]]:
        """Load search results from a JSON file."""
        if not os.path.exists(file_path):
            return []

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f'Search results loaded from {file_path}')

        return data


class SearchEngine(ABC):
    """Abstract base class for search engines."""

    @abstractmethod
    def search(self, search_request: SearchRequest) -> SearchResult:
        """Perform a search and return results."""
        pass
