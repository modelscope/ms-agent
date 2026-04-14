import json
import os
import unittest
from unittest.mock import MagicMock, patch

from ms_agent.tools.search.exa.schema import (ExaSearchRequest,
                                               ExaSearchResult)
from ms_agent.tools.search.search_base import SearchEngineType

from modelscope.utils.test_utils import test_level


class TestExaSearchRequest(unittest.TestCase):
    """Test cases for ExaSearchRequest class."""

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_init_default_values(self):
        """Test initialization with default values."""
        request = ExaSearchRequest(query='AI agents')
        self.assertEqual(request.query, 'AI agents')
        self.assertEqual(request.num_results, 5)
        self.assertEqual(request.type, 'auto')
        self.assertTrue(request.text)
        self.assertFalse(request.highlights)
        self.assertFalse(request.summary)
        self.assertIsNone(request.category)
        self.assertIsNone(request.include_domains)
        self.assertIsNone(request.exclude_domains)
        self.assertIsNone(request.user_location)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_init_custom_values(self):
        """Test initialization with custom values."""
        request = ExaSearchRequest(
            query='deep learning papers',
            num_results=10,
            type='neural',
            text=True,
            highlights=True,
            summary=True,
            start_published_date='2024-01-01',
            end_published_date='2024-12-31',
            include_domains=['arxiv.org'],
            category='research paper',
            user_location='US',
        )
        self.assertEqual(request.query, 'deep learning papers')
        self.assertEqual(request.num_results, 10)
        self.assertEqual(request.type, 'neural')
        self.assertTrue(request.highlights)
        self.assertTrue(request.summary)
        self.assertEqual(request.include_domains, ['arxiv.org'])
        self.assertEqual(request.category, 'research paper')
        self.assertEqual(request.user_location, 'US')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_to_dict_basic(self):
        """Test conversion to dictionary with defaults."""
        request = ExaSearchRequest(query='test query')
        result = request.to_dict()
        self.assertEqual(result['query'], 'test query')
        self.assertEqual(result['type'], 'auto')
        self.assertEqual(result['num_results'], 5)
        self.assertTrue(result['text'])
        self.assertFalse(result['highlights'])
        self.assertFalse(result['summary'])
        # Optional fields should not be present when None
        self.assertNotIn('start_published_date', result)
        self.assertNotIn('end_published_date', result)
        self.assertNotIn('start_crawl_date', result)
        self.assertNotIn('end_crawl_date', result)
        self.assertNotIn('include_domains', result)
        self.assertNotIn('exclude_domains', result)
        self.assertNotIn('category', result)
        self.assertNotIn('user_location', result)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_to_dict_with_filters(self):
        """Test conversion to dictionary with domain and category filters."""
        request = ExaSearchRequest(
            query='startup funding',
            include_domains=['techcrunch.com', 'bloomberg.com'],
            exclude_domains=['reddit.com'],
            category='news',
            user_location='US',
        )
        result = request.to_dict()
        self.assertEqual(
            result['include_domains'], ['techcrunch.com', 'bloomberg.com'])
        self.assertEqual(result['exclude_domains'], ['reddit.com'])
        self.assertEqual(result['category'], 'news')
        self.assertEqual(result['user_location'], 'US')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_to_json(self):
        """Test conversion to JSON string."""
        request = ExaSearchRequest(query='reinforcement learning')
        json_str = request.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed['query'], 'reinforcement learning')
        self.assertEqual(parsed['type'], 'auto')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_keyword_type_not_default(self):
        """Verify 'keyword' is not the default search type (it was removed)."""
        request = ExaSearchRequest(query='test')
        self.assertNotEqual(request.type, 'keyword')


class TestExaSearchResult(unittest.TestCase):
    """Test cases for ExaSearchResult class."""

    def _make_mock_result(self, **kwargs):
        """Create a mock result object with the given attributes."""
        result = MagicMock()
        defaults = {
            'url': 'https://example.com',
            'id': 'https://example.com',
            'title': 'Test Result',
            'published_date': '2024-06-15',
            'summary': None,
            'highlights': None,
            'highlight_scores': None,
            'text': None,
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(result, k, v)
        return result

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_to_list_with_text_only(self):
        """Test to_list when only text content is present."""
        mock_response = MagicMock()
        mock_response.results = [
            self._make_mock_result(
                text='Full text content here.',
            )
        ]
        result = ExaSearchResult(
            query='test', arguments={}, response=mock_response)
        items = result.to_list()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['text'], 'Full text content here.')
        self.assertNotIn('summary', items[0])
        self.assertNotIn('highlights', items[0])

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_to_list_with_highlights(self):
        """Test to_list when highlights are present."""
        mock_response = MagicMock()
        mock_response.results = [
            self._make_mock_result(
                highlights=['key point 1', 'key point 2'],
                highlight_scores=[0.95, 0.88],
            )
        ]
        result = ExaSearchResult(
            query='test', arguments={}, response=mock_response)
        items = result.to_list()
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]['highlights'], ['key point 1', 'key point 2'])
        self.assertEqual(items[0]['highlight_scores'], [0.95, 0.88])

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_to_list_with_summary(self):
        """Test to_list when summary is present."""
        mock_response = MagicMock()
        mock_response.results = [
            self._make_mock_result(
                summary='A concise summary of the page.',
            )
        ]
        result = ExaSearchResult(
            query='test', arguments={}, response=mock_response)
        items = result.to_list()
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]['summary'], 'A concise summary of the page.')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_to_list_with_all_content(self):
        """Test to_list when text, highlights, and summary are all present."""
        mock_response = MagicMock()
        mock_response.results = [
            self._make_mock_result(
                text='Full text.',
                highlights=['highlight 1'],
                highlight_scores=[0.9],
                summary='Summary text.',
            )
        ]
        result = ExaSearchResult(
            query='test', arguments={}, response=mock_response)
        items = result.to_list()
        self.assertEqual(len(items), 1)
        self.assertIn('text', items[0])
        self.assertIn('highlights', items[0])
        self.assertIn('summary', items[0])

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_to_list_with_no_content(self):
        """Test to_list when no content fields are present."""
        mock_response = MagicMock()
        mock_response.results = [
            self._make_mock_result(
                url='https://example.com/page',
                title='Page Title',
            )
        ]
        result = ExaSearchResult(
            query='test', arguments={}, response=mock_response)
        items = result.to_list()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['url'], 'https://example.com/page')
        self.assertEqual(items[0]['title'], 'Page Title')
        self.assertNotIn('text', items[0])
        self.assertNotIn('highlights', items[0])
        self.assertNotIn('summary', items[0])

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_to_list_empty_response(self):
        """Test to_list with no results."""
        result = ExaSearchResult(query='test', arguments={}, response=None)
        items = result.to_list()
        self.assertEqual(items, [])

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_to_list_empty_query(self):
        """Test to_list with empty query string."""
        mock_response = MagicMock()
        mock_response.results = [self._make_mock_result()]
        result = ExaSearchResult(
            query='', arguments={}, response=mock_response)
        items = result.to_list()
        self.assertEqual(items, [])


class TestExaSearch(unittest.TestCase):
    """Test cases for ExaSearch class."""

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    @patch.dict(os.environ, {'EXA_API_KEY': 'test-key-123'})
    @patch('exa_py.Exa')
    def test_init_sets_integration_header(self, mock_exa_cls):
        """Test that initialization sets the x-exa-integration header."""
        mock_client = MagicMock()
        mock_client.headers = {}
        mock_exa_cls.return_value = mock_client

        from ms_agent.tools.search.exa.search import ExaSearch
        engine = ExaSearch(api_key='test-key-123')
        self.assertEqual(engine.engine_type, SearchEngineType.EXA)
        self.assertEqual(
            mock_client.headers['x-exa-integration'], 'ms-agent')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_init_requires_api_key(self):
        """Test that initialization fails without API key."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove EXA_API_KEY if set
            os.environ.pop('EXA_API_KEY', None)
            from ms_agent.tools.search.exa.search import ExaSearch
            with self.assertRaises(AssertionError):
                ExaSearch()

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_build_request_from_args_defaults(self):
        """Test building request with default arguments."""
        from ms_agent.tools.search.exa.search import ExaSearch
        request = ExaSearch.build_request_from_args(query='test query')
        self.assertEqual(request.query, 'test query')
        self.assertEqual(request.num_results, 5)
        self.assertEqual(request.type, 'auto')
        self.assertTrue(request.text)
        self.assertFalse(request.highlights)
        self.assertFalse(request.summary)
        self.assertIsNone(request.include_domains)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_build_request_from_args_full(self):
        """Test building request with all arguments."""
        from ms_agent.tools.search.exa.search import ExaSearch
        request = ExaSearch.build_request_from_args(
            query='AI news',
            num_results=10,
            type='neural',
            highlights=True,
            summary=True,
            category='news',
            include_domains=['techcrunch.com'],
            start_published_date='2024-01-01',
        )
        self.assertEqual(request.query, 'AI news')
        self.assertEqual(request.num_results, 10)
        self.assertEqual(request.type, 'neural')
        self.assertTrue(request.highlights)
        self.assertTrue(request.summary)
        self.assertEqual(request.category, 'news')
        self.assertEqual(request.include_domains, ['techcrunch.com'])
        self.assertEqual(request.start_published_date, '2024-01-01')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_tool_definition_no_keyword_type(self):
        """Verify the tool definition does not include 'keyword' as a type."""
        from ms_agent.tools.search.exa.search import ExaSearch
        tool = ExaSearch.get_tool_definition()
        type_enum = tool.parameters['properties']['type']['enum']
        self.assertNotIn('keyword', type_enum)
        self.assertIn('auto', type_enum)
        self.assertIn('neural', type_enum)
        self.assertIn('fast', type_enum)

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_tool_definition_includes_filtering(self):
        """Verify the tool definition exposes domain and category filters."""
        from ms_agent.tools.search.exa.search import ExaSearch
        tool = ExaSearch.get_tool_definition()
        props = tool.parameters['properties']
        self.assertIn('category', props)
        self.assertIn('include_domains', props)
        self.assertIn('exclude_domains', props)
        self.assertIn('highlights', props)
        self.assertIn('summary', props)


class TestExaSearchResultFixture(unittest.TestCase):
    """Test parsing of a realistic API response fixture."""

    FIXTURE = {
        'results': [
            {
                'id': 'https://arxiv.org/abs/2505.20023',
                'title': 'Training LLM-Based Agents',
                'url': 'https://arxiv.org/abs/2505.20023',
                'publishedDate': '2025-05-26T00:00:00.000Z',
                'score': 0.367,
                'text': 'Abstract: Autonomous agents...',
                'highlights': ['key finding 1', 'key finding 2'],
                'highlight_scores': [0.95, 0.88],
                'summary': 'This paper proposes STeP...',
            },
            {
                'id': 'https://arxiv.org/abs/2505.10978',
                'title': 'Group-in-Group Policy Optimization',
                'url': 'https://arxiv.org/abs/2505.10978',
                'publishedDate': '2025-05-16T00:00:00.000Z',
                'score': 0.366,
                'text': 'Abstract: Recent advances...',
                'highlights': None,
                'highlight_scores': None,
                'summary': None,
            },
        ]
    }

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_fixture_parsing(self):
        """Test that a realistic response fixture is parsed correctly."""
        # Build mock response that mimics exa_py SearchResponse
        mock_response = MagicMock()
        mock_results = []
        for r in self.FIXTURE['results']:
            mock_result = MagicMock()
            mock_result.url = r['url']
            mock_result.id = r['id']
            mock_result.title = r['title']
            mock_result.published_date = r['publishedDate']
            mock_result.text = r.get('text')
            mock_result.highlights = r.get('highlights')
            mock_result.highlight_scores = r.get('highlight_scores')
            mock_result.summary = r.get('summary')
            mock_results.append(mock_result)
        mock_response.results = mock_results

        result = ExaSearchResult(
            query='Agent RL', arguments={}, response=mock_response)
        items = result.to_list()

        self.assertEqual(len(items), 2)

        # First result has all content fields
        self.assertEqual(items[0]['title'], 'Training LLM-Based Agents')
        self.assertEqual(items[0]['text'], 'Abstract: Autonomous agents...')
        self.assertEqual(
            items[0]['highlights'], ['key finding 1', 'key finding 2'])
        self.assertEqual(items[0]['summary'], 'This paper proposes STeP...')

        # Second result has only text (highlights/summary are None)
        self.assertEqual(
            items[1]['title'], 'Group-in-Group Policy Optimization')
        self.assertIn('text', items[1])
        self.assertNotIn('highlights', items[1])
        self.assertNotIn('summary', items[1])


if __name__ == '__main__':
    unittest.main()
