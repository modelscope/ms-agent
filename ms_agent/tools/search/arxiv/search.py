# flake8: noqa
import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import arxiv
from arxiv import SortCriterion, SortOrder
from ms_agent.tools.search.arxiv.schema import (ArxivSearchRequest,
                                                ArxivSearchResult)
from ms_agent.tools.search.search_base import SearchEngine, SearchEngineType
from ms_agent.utils.logger import get_logger

if TYPE_CHECKING:
    from ms_agent.llm.utils import Tool

logger = get_logger()

# Valid arXiv category prefixes (mirrors arxiv-mcp-server validation)
VALID_CATEGORY_PREFIXES = {
    'cs',
    'econ',
    'eess',
    'math',
    'physics',
    'q-bio',
    'q-fin',
    'stat',
    'astro-ph',
    'cond-mat',
    'gr-qc',
    'hep-ex',
    'hep-lat',
    'hep-ph',
    'hep-th',
    'math-ph',
    'nlin',
    'nucl-ex',
    'nucl-th',
    'quant-ph',
}


def _validate_categories(categories):
    """Validate that all provided categories look like arXiv categories."""
    if not categories:
        return True
    for category in categories:
        if not category:
            return False
        prefix = category.split('.', 1)[0] if '.' in category else category
        if prefix not in VALID_CATEGORY_PREFIXES:
            return False
    return True


ARXIV_DESCRIPTION = """
Search for papers on arXiv with advanced filtering and query optimization.

QUERY CONSTRUCTION GUIDELINES:
- Use QUOTED PHRASES for exact matches: "multi-agent systems", "neural networks", "machine learning"
- Combine related concepts with OR: "AI agents" OR "software agents" OR "intelligent agents"
- Use field-specific searches for precision:
  - ti:"exact title phrase" - search in titles only
  - au:"author name" - search by author
  - abs:"keyword" - search in abstracts only
- Use ANDNOT to exclude unwanted results: "machine learning" ANDNOT "survey"
- For best results, use 2-4 core concepts rather than long keyword lists

ADVANCED SEARCH PATTERNS:
- Field + phrase: ti:"transformer architecture" for papers with exact title phrase
- Multiple fields: au:"Smith" AND ti:"quantum" for author Smith's quantum papers
- Exclusions: "deep learning" ANDNOT ("survey" OR "review") to exclude survey papers
- Broad + narrow: "artificial intelligence" AND (robotics OR "computer vision")

CATEGORY FILTERING (highly recommended for relevance):
- cs.AI: Artificial Intelligence
- cs.MA: Multi-Agent Systems
- cs.LG: Machine Learning
- cs.CL: Computation and Language (NLP)
- cs.CV: Computer Vision
- cs.RO: Robotics
- cs.HC: Human-Computer Interaction
- cs.CR: Cryptography and Security
- cs.DB: Databases

EXAMPLES OF EFFECTIVE QUERIES:
- ti:"reinforcement learning" with categories: ["cs.LG", "cs.AI"] - for RL papers by title
- au:"Hinton" AND "deep learning" with categories: ["cs.LG"] - for Hinton's deep learning work
- "multi-agent" ANDNOT "survey" with categories: ["cs.MA"] - exclude survey papers
- abs:"transformer" AND ti:"attention" with categories: ["cs.CL"] - attention papers with transformer abstracts

DATE FILTERING: Use YYYY-MM-DD format for historical research:
- date_to: "2015-12-31" - for foundational/classic work (pre-2016)
- date_from: "2020-01-01" - for recent developments (post-2020)
- Both together for specific time periods

RESULT QUALITY: Results sorted by RELEVANCE (most relevant papers first), not just newest papers.
This ensures you get the most pertinent results regardless of publication date.

TIPS FOR FOUNDATIONAL RESEARCH:
- Use date_to: "2010-12-31" to find classic papers on BDI, SOAR, ACT-R
- Combine with field searches: ti:"BDI" AND abs:"belief desire intention"
- Try author searches: au:"Rao" AND "BDI" for Anand Rao's foundational BDI work
"""


class ArxivSearch(SearchEngine):
    """
    Search engine using arXiv API.

    Best for: scientific literature, research papers, preprints.
    Supports sorting by relevance, submission date, or last update.
    """

    engine_type = SearchEngineType.ARXIV

    def __init__(self):
        self.client = arxiv.Client()

    def search(self, search_request: ArxivSearchRequest) -> ArxivSearchResult:
        """Perform a search using arxiv and return the results."""
        search_args: dict = search_request.to_dict()

        try:

            def _parse_yyyy_mm_dd(s: str, *, end_of_day: bool) -> datetime:
                dt = datetime.strptime(s, '%Y-%m-%d')
                if end_of_day:
                    dt = dt + timedelta(days=1) - timedelta(microseconds=1)
                return dt.replace(tzinfo=timezone.utc)

            date_from_dt = None
            date_to_dt = None
            if getattr(search_request, 'date_from', None):
                date_from_dt = _parse_yyyy_mm_dd(
                    search_request.date_from, end_of_day=False)
            if getattr(search_request, 'date_to', None):
                date_to_dt = _parse_yyyy_mm_dd(
                    search_request.date_to, end_of_day=True)

            if date_from_dt or date_to_dt:
                desired = int(search_request.num_results or 10)
                search_args['max_results'] = min(
                    max(desired + 10, desired), 50)

            response = []
            for paper in self.client.results(
                    search=arxiv.Search(**search_args)):
                if date_from_dt or date_to_dt:
                    paper_date = getattr(paper, 'published', None)
                    if paper_date is None:
                        continue
                    if not getattr(paper_date, 'tzinfo', None):
                        paper_date = paper_date.replace(tzinfo=timezone.utc)
                    if date_from_dt and paper_date < date_from_dt:
                        continue
                    if date_to_dt and paper_date > date_to_dt:
                        continue

                response.append(paper)
                if len(response) >= int(search_request.num_results or 10):
                    break

            extra_args = {}
            if getattr(search_request, 'date_from', None):
                extra_args['date_from'] = search_request.date_from
            if getattr(search_request, 'date_to', None):
                extra_args['date_to'] = search_request.date_to
            if getattr(search_request, 'categories', None):
                extra_args['categories'] = search_request.categories

            search_result = ArxivSearchResult(
                query=search_request.query,
                arguments={
                    **search_args,
                    **extra_args,
                },
                response=response)
        except Exception as e:
            raise RuntimeError(f'Failed to perform search: {e}') from e

        return search_result

    @classmethod
    def get_tool_definition(cls, server_name: str = 'web_search') -> 'Tool':
        """Return the tool definition for arXiv search engine."""
        from ms_agent.llm.utils import Tool
        return Tool(
            tool_name=cls.get_tool_name(),
            server_name=server_name,
            description=ARXIV_DESCRIPTION.strip(),
            parameters={
                'type': 'object',
                'properties': {
                    'query': {
                        'type':
                        'string',
                        'description':
                        ('Search query using quoted phrases for exact matches '
                         '(e.g., \'"machine learning" OR "deep learning"\') or '
                         'specific technical terms. Avoid overly broad or generic terms.'
                         ),
                    },
                    'num_results': {
                        'type':
                        'integer',
                        'minimum':
                        1,
                        'maximum':
                        15,
                        'description':
                        ('Maximum number of results to return. Default is 5.'
                         'Use 5-15 for comprehensive searches.'),
                    },
                    'date_from': {
                        'type':
                        'string',
                        'description':
                        ('Start date for papers (YYYY-MM-DD format). '
                         'Use to find recent work, e.g., "2023-01-01".'),
                    },
                    'date_to': {
                        'type':
                        'string',
                        'description':
                        ('End date for papers (YYYY-MM-DD format). '
                         'Use with date_from for historical windows, e.g., "2020-12-31".'
                         ),
                    },
                    'categories': {
                        'type':
                        'array',
                        'items': {
                            'type': 'string'
                        },
                        'description':
                        ('Strongly recommended: arXiv categories to focus search '
                         '(e.g., ["cs.AI", "cs.MA"] for agent research, ["cs.LG"] for ML, '
                         '["cs.CL"] for NLP, ["cs.CV"] for computer vision). '
                         'Greatly improves relevance.'),
                    },
                    'sort_by': {
                        'type':
                        'string',
                        'enum':
                        ['relevance', 'submittedDate', 'lastUpdatedDate'],
                        'description':
                        ('How to sort results. "relevance" for best match, '
                         '"submittedDate" for newest submissions, '
                         '"lastUpdatedDate" for recently updated. Default is "relevance".'
                         ),
                    },
                    'sort_order': {
                        'type': 'string',
                        'enum': ['descending', 'ascending'],
                        'description': 'Sort order. Default is "descending".',
                    },
                },
                'required': ['query'],
            },
        )

    @classmethod
    def build_request_from_args(cls, **kwargs) -> ArxivSearchRequest:
        """Build ArxivSearchRequest from tool call arguments."""
        num_results = kwargs.get('num_results', 5)

        categories = kwargs.get('categories') or None
        if categories:
            categories = [str(c).strip() for c in categories if str(c).strip()]
            if not _validate_categories(categories):
                logger.warning(
                    f"Invalid arXiv categories provided: {kwargs.get('categories')}. "
                    'Ignoring categories filter.')
                categories = None

        # Build final query by AND-ing base query with category filter (OR across categories)
        base_query = (kwargs.get('query') or '').strip()
        query_parts = []
        if base_query:
            query_parts.append(f'({base_query})')
        if categories:
            category_filter = ' OR '.join(f'cat:{cat}' for cat in categories)
            query_parts.append(f'({category_filter})')
        final_query = ' '.join(query_parts) if query_parts else base_query
        logger.info(f'Final query: {final_query}')

        # Map string sort_by to SortCriterion
        sort_by_map = {
            'relevance': SortCriterion.Relevance,
            'submittedDate': SortCriterion.SubmittedDate,
            'lastUpdatedDate': SortCriterion.LastUpdatedDate,
        }
        sort_order_map = {
            'descending': SortOrder.Descending,
            'ascending': SortOrder.Ascending,
        }

        sort_by = kwargs.get('sort_by', 'relevance')
        sort_order = kwargs.get('sort_order', 'descending')

        return ArxivSearchRequest(
            query=final_query,
            num_results=num_results,
            sort_strategy=sort_by_map.get(sort_by, SortCriterion.Relevance),
            sort_order=sort_order_map.get(sort_order, SortOrder.Descending),
            categories=categories,
            date_from=kwargs.get('date_from'),
            date_to=kwargs.get('date_to'),
        )
