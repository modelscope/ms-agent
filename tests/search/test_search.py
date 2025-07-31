import unittest

from arxiv import Result, SortCriterion, SortOrder
from ms_agent.tools.search.arxiv.schema import (ArxivSearchRequest,
                                                ArxivSearchResult)
from ms_agent.tools.search.arxiv.search import ArxivSearch
from ms_agent.tools.search.search_base import SearchEngineType

from modelscope.utils.test_utils import test_level


class MockArxivResult(Result):
    """Mock class for arxiv.Result to simulate search results."""

    def __init__(self, entry_id, title, summary, pdf_url):
        self.entry_id = entry_id
        self.title = title
        self.summary = summary
        self.pdf_url = pdf_url


class TestArxivSearchRequest(unittest.TestCase):
    """Test cases for ArxivSearchRequest class."""

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_init_default_values(self):
        """Test initialization with default values."""
        request = ArxivSearchRequest(query='machine learning')
        self.assertEqual(request.query, 'machine learning')
        self.assertEqual(request.num_results, 10)
        self.assertEqual(request.sort_strategy, SortCriterion.Relevance)
        self.assertEqual(request.sort_order, SortOrder.Descending)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_init_custom_values(self):
        """Test initialization with custom values."""
        request = ArxivSearchRequest(
            query='deep learning',
            num_results=5,
            sort_strategy=SortCriterion.SubmittedDate,
            sort_order=SortOrder.Ascending)
        self.assertEqual(request.query, 'deep learning')
        self.assertEqual(request.num_results, 5)
        self.assertEqual(request.sort_strategy, SortCriterion.SubmittedDate)
        self.assertEqual(request.sort_order, SortOrder.Ascending)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_to_dict(self):
        """Test conversion to dictionary."""
        request = ArxivSearchRequest(query='neural networks', num_results=3)
        result = request.to_dict()
        expected = {
            'query': 'neural networks',
            'max_results': 3,
            'sort_by': SortCriterion.Relevance,
            'sort_order': SortOrder.Descending
        }
        self.assertEqual(result, expected)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_to_json(self):
        """Test conversion to JSON string."""
        request = ArxivSearchRequest(query='reinforcement learning')
        json_str = request.to_json()
        self.assertIn('"query": "reinforcement learning"', json_str)
        self.assertIn('"max_results": 10', json_str)
        self.assertIn('"sort_strategy": "relevance"', json_str)
        self.assertIn('"sort_order": "descending"', json_str)


class TestArxivSearchResult(unittest.TestCase):
    """Test cases for ArxivSearchResult class."""

    def setUp(self):
        """Set up test fixtures."""

        def mock_results_generator_func():
            """Mock generator function to simulate arxiv results."""
            yield MockArxivResult(
                entry_id='http://arxiv.org/abs/1234.5678',
                title='Test Paper 1',
                summary='This is a test paper about AI',
                pdf_url='http://arxiv.org/pdf/1234.5678')
            yield MockArxivResult(
                entry_id='http://arxiv.org/abs/8765.4321',
                title='Test Paper 2',
                summary='Another test paper about machine learning',
                pdf_url='http://arxiv.org/pdf/8765.4321')

        self.arguments = {
            'query': 'Deep Learning',
            'num_results': 2,
            'sort_strategy': SortCriterion.Relevance,
            'sort_order': SortOrder.Descending
        }
        self.arxiv_results_generator_func = mock_results_generator_func

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_process_results(self):
        """Test processing of arxiv results."""
        search_result = ArxivSearchResult(
            query='test query',
            arguments=self.arguments,
            response=self.arxiv_results_generator_func())

        processed = search_result.response
        self.assertEqual(len(processed.results), 2)

        # Test first result
        self.assertEqual(processed.results[0].url,
                         'http://arxiv.org/pdf/1234.5678')
        self.assertEqual(processed.results[0].id,
                         'http://arxiv.org/abs/1234.5678')
        self.assertEqual(processed.results[0].title, 'Test Paper 1')
        self.assertEqual(processed.results[0].summary,
                         'This is a test paper about AI')

        # Test second result
        self.assertEqual(processed.results[1].url,
                         'http://arxiv.org/pdf/8765.4321')
        self.assertEqual(processed.results[1].id,
                         'http://arxiv.org/abs/8765.4321')
        self.assertEqual(processed.results[1].title, 'Test Paper 2')
        self.assertEqual(processed.results[1].summary,
                         'Another test paper about machine learning')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_process_empty_results(self):
        """Test processing of empty results."""
        result = ArxivSearchResult(
            query='test query', arguments=self.arguments, response=[])
        processed = result.response
        self.assertEqual(len(processed.results), 0)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_to_list(self):
        """Test conversion to list of dictionaries."""
        result = ArxivSearchResult(
            query='test query',
            arguments=self.arguments,
            response=self.arxiv_results_generator_func())

        result_list = result.to_list()
        self.assertEqual(len(result_list), 2)

        # Test first result
        self.assertEqual(result_list[0]['url'],
                         'http://arxiv.org/pdf/1234.5678')
        self.assertEqual(result_list[0]['id'],
                         'http://arxiv.org/abs/1234.5678')
        self.assertEqual(result_list[0]['title'], 'Test Paper 1')
        self.assertEqual(result_list[0]['summary'],
                         'This is a test paper about AI')


class TestArxivSearch(unittest.TestCase):
    """Test cases for ArxivSearch class."""

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_init(self):
        """Test initialization."""
        search_engine = ArxivSearch()
        self.assertEqual(search_engine.engine_type, SearchEngineType.ARXIV)
        self.assertIsNotNone(search_engine.client)

    @unittest.skipUnless(test_level() >= 2, 'skip test in current test level')
    def test_search(self):
        """Test search functionality."""
        search_engine = ArxivSearch()
        search_request = ArxivSearchRequest(
            query='Deep Learning',
            num_results=2,
            sort_strategy=SortCriterion.Relevance,
            sort_order=SortOrder.Descending)
        search_result = search_engine.search(search_request)

        self.assertIsInstance(search_result, ArxivSearchResult)
        self.assertEqual(search_result.query, 'Deep Learning')
        self.assertEqual(
            search_result.arguments, {
                'query': 'Deep Learning',
                'max_results': 2,
                'sort_strategy': SortCriterion.Relevance.value,
                'sort_order': SortOrder.Descending.value
            })
        self.assertEqual(len(search_result.response.results), 2)


if __name__ == '__main__':
    unittest.main()
