import asyncio
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import json
from ms_agent.tools.search.websearch_tool import WebSearchTool
from ms_agent.tools.todolist_tool import TodoListTool
from projects.deep_research.v2.tools.evidence_tool import EvidenceTool
from projects.deep_research.v2.tools.report_tool import ReportTool

from modelscope.utils.test_utils import test_level

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    # Allow running this test file directly: `python tests/tools/test_server_tools_smoke.py`
    # without requiring `tests/` to be a package.
    sys.path.insert(0, _REPO_ROOT)


def _make_config(output_dir: str, tools: dict) -> SimpleNamespace:
    """
    Minimal config object compatible with ToolBase usage in this repo.
    Keep it SimpleNamespace-based so it's easy to tweak scenarios.
    """
    return SimpleNamespace(
        output_dir=output_dir, tools=SimpleNamespace(**tools))


class _FakeSearchResult:

    def __init__(self, results):
        self._results = results

    def to_list(self):
        return list(self._results)


class _FakeSearchEngine:
    """
    A deterministic, no-network SearchEngine stub for WebSearchTool tests.
    It matches the subset of the SearchEngine API used by WebSearchTool.
    """

    def __init__(self, *args, **kwargs):
        # WebSearchTool may pass api_key/provider args depending on engine type.
        # This stub ignores them.
        pass

    @classmethod
    def get_tool_definition(cls, server_name: str = 'web_search'):
        return {
            'tool_name': 'arxiv_search',
            'server_name': server_name,
            'description': 'Fake arxiv search (no network).',
            'parameters': {
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': 'Query',
                    },
                    'num_results': {
                        'type': 'integer',
                        'description': 'Number of results',
                    },
                },
                'required': ['query'],
                'additionalProperties': True,
            },
        }

    @classmethod
    def build_request_from_args(cls, **kwargs):
        # WebSearchTool only passes this into search(); we keep it transparent.
        return dict(kwargs)

    def search(self, search_request):
        # Deterministic single-result output; easy to extend in new scenarios.
        q = (search_request or {}).get('query', '')
        return _FakeSearchResult([{
            'url': 'https://example.com/a',
            'title': f'fake result for {q}',
            'summary': 'fake summary',
            'published_date': '2026-01-23',
            # arxiv-specific keys (optional; keep empty to exercise fallback path)
            'arxiv_id': '',
            'id': '',
            'authors': [],
            'categories': [],
        }])


class _FakeContentFetcher:

    def fetch(self, url: str):
        return (f'content for {url}', {'fetcher': 'fake'})


class TestWebSearchToolServer(unittest.TestCase):

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_web_search_tool_smoke_no_network(self):

        async def main():
            with tempfile.TemporaryDirectory() as td:
                cfg = _make_config(
                    td,
                    tools={
                        'web_search':
                        SimpleNamespace(
                            engines=['exa', 'serpapi', 'arxiv'],
                            exa_api_key='fake',
                            serpapi_api_key='fake',
                            serpapi_provider='google',
                            fetch_content=True,
                            enable_chunking=False,
                            max_results=3,
                            fetcher='jina_reader',
                        )
                    },
                )

                # Patch the engine/fetcher factories so connect() is deterministic and offline.
                import ms_agent.tools.search.websearch_tool as wst

                def _make_engine_cls(engine_type: str):
                    tool_name = {
                        'exa': 'exa_search',
                        'serpapi': 'serpapi_search',
                        'arxiv': 'arxiv_search',
                    }[engine_type]

                    class _E(_FakeSearchEngine):

                        @classmethod
                        def get_tool_definition(cls,
                                                server_name: str = 'web_search'
                                                ):
                            base = dict(super().get_tool_definition(
                                server_name=server_name))
                            base['tool_name'] = tool_name
                            base[
                                'description'] = f'Fake {engine_type} search (no network).'
                            return base

                        def search(self, search_request):
                            q = (search_request or {}).get('query', '')
                            return _FakeSearchResult([{
                                'url':
                                f'https://example.com/{engine_type}',
                                'title':
                                f'fake {engine_type} result for {q}',
                                'summary':
                                f'fake {engine_type} summary',
                                'published_date':
                                '2026-01-23',
                            }])

                    return _E

                with patch.object(wst, 'get_search_engine_class',
                                  side_effect=_make_engine_cls), \
                        patch.object(wst, 'get_content_fetcher',
                                     return_value=_FakeContentFetcher()):
                    tool = WebSearchTool(cfg)
                    await tool.connect()

                    tools = await tool.get_tools()
                    self.assertIn('web_search', tools)
                    names = {t['tool_name'] for t in tools['web_search']}
                    self.assertIn('exa_search', names)
                    self.assertIn('serpapi_search', names)
                    self.assertIn('arxiv_search', names)
                    self.assertIn('fetch_page', names)

                    # Ensure dynamic param injection works.
                    arxiv_tool = next(t for t in tools['web_search']
                                      if t['tool_name'] == 'arxiv_search')
                    props = arxiv_tool.get('parameters',
                                           {}).get('properties', {})
                    self.assertIn('fetch_content', props)

                    # Engine tool routes
                    res = await tool.call_tool(  # fetch_content=True -> content present
                        server_name='web_search',
                        tool_name='serpapi_search',
                        tool_args={
                            'query': 'ms-agent',
                            'num_results': 1,
                            'fetch_content': True,
                        },
                    )
                    data = json.loads(res)
                    self.assertEqual(data['status'], 'ok')
                    self.assertEqual(data['engine'], 'serpapi')
                    self.assertEqual(data['count'], 1)
                    self.assertIn('content', data['results'][0])
                    self.assertTrue(data['results'][0]['fetch_success'])

                    res_no_fetch = await tool.call_tool(  # fetch_content=False -> summary present
                        server_name='web_search',
                        tool_name='exa_search',
                        tool_args={
                            'query': 'ms-agent',
                            'num_results': 1,
                            'fetch_content': False,
                        },
                    )
                    data2 = json.loads(res_no_fetch)
                    self.assertEqual(data2['status'], 'ok')
                    self.assertEqual(data2['engine'], 'exa')
                    self.assertIn('summary', data2['results'][0])

                    # Fallback tool route: web_search maps to the first engine in config (exa).
                    res_fallback = await tool.call_tool(
                        server_name='web_search',
                        tool_name='web_search',
                        tool_args={
                            'query': 'ms-agent',
                            'num_results': 1,
                            'fetch_content': False,
                        },
                    )
                    data3 = json.loads(res_fallback)
                    self.assertEqual(data3['status'], 'ok')
                    self.assertEqual(data3['engine'], 'exa')

                    # Fetch page route
                    res2 = await tool.call_tool(
                        server_name='web_search',
                        tool_name='fetch_page',
                        tool_args={'url': 'https://example.com/a'},
                    )
                    page = json.loads(res2)
                    self.assertIn(page['status'], ['ok', 'error'])
                    self.assertEqual(page['url'], 'https://example.com/a')
                    self.assertIn('content', page)

                    await tool.cleanup()

        asyncio.run(main())


class TestWebSearchToolServerNetwork(unittest.TestCase):
    """
    Real-network integration tests for WebSearchTool.

    These tests are skipped by default to avoid flaky CI runs and missing API keys.
    Enable them explicitly:
      MS_AGENT_ENABLE_NETWORK_TESTS=1 python -m unittest -q tests.tools.test_server_tools_smoke
    """

    def _network_enabled(self) -> bool:
        return str(os.getenv('MS_AGENT_ENABLE_NETWORK_TESTS',
                             '')).strip() in ('1', 'true', 'True')

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_arxiv_search_real(self):
        if not self._network_enabled():
            self.skipTest(
                'Set MS_AGENT_ENABLE_NETWORK_TESTS=1 to run real-network tests.'
            )

        async def main():
            with tempfile.TemporaryDirectory() as td:
                cfg = _make_config(
                    td,
                    tools={
                        # Use arxiv only: no API key required, but still needs network.
                        'web_search':
                        SimpleNamespace(
                            engines=['arxiv'],
                            fetch_content=
                            True,  # avoid extra page fetching calls
                            enable_chunking=False,
                            max_results=1,
                        )
                    },
                )
                tool = WebSearchTool(cfg)
                await tool.connect()

                res = await tool.call_tool(
                    server_name='web_search',
                    tool_name='arxiv_search',
                    tool_args={
                        'query': 'large language model',
                        'num_results': 1,
                        'fetch_content': True,
                    },
                )
                data = json.loads(res)
                self.assertEqual(data['status'], 'ok')
                self.assertEqual(data['engine'], 'arxiv')
                self.assertGreaterEqual(data['count'], 0)
                if data['count'] > 0:
                    self.assertIn('title', data['results'][0])
                    self.assertIn('url', data['results'][0])
                    # fetch_content=False -> summary path
                    self.assertIn('abstract', data['results'][0])

                await tool.cleanup()

        asyncio.run(main())

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_exa_search_real(self):
        if not self._network_enabled():
            self.skipTest(
                'Set MS_AGENT_ENABLE_NETWORK_TESTS=1 to run real-network tests.'
            )
        if not os.getenv('EXA_API_KEY'):
            self.skipTest('EXA_API_KEY is required for Exa real-network test.')

        async def main():
            with tempfile.TemporaryDirectory() as td:
                cfg = _make_config(
                    td,
                    tools={
                        'web_search':
                        SimpleNamespace(
                            engines=['exa'],
                            exa_api_key=os.getenv('EXA_API_KEY'),
                            fetch_content=False,  # keep it cheap + less flaky
                            enable_chunking=False,
                            max_results=1,
                        )
                    },
                )
                tool = WebSearchTool(cfg)
                await tool.connect()

                res = await tool.call_tool(
                    server_name='web_search',
                    tool_name='exa_search',
                    tool_args={
                        'query': 'OpenAI',
                        'num_results': 1,
                        'fetch_content': True,
                    },
                )
                data = json.loads(res)
                self.assertEqual(data['status'], 'ok')
                self.assertEqual(data['engine'], 'exa')
                self.assertGreaterEqual(data['count'], 0)
                if data['count'] > 0:
                    self.assertIn('title', data['results'][0])
                    self.assertIn('url', data['results'][0])
                    self.assertIn('summary', data['results'][0])

                await tool.cleanup()

        asyncio.run(main())

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_serpapi_search_real(self):
        if not self._network_enabled():
            self.skipTest(
                'Set MS_AGENT_ENABLE_NETWORK_TESTS=1 to run real-network tests.'
            )
        if not os.getenv('SERPAPI_API_KEY'):
            self.skipTest(
                'SERPAPI_API_KEY is required for SerpApi real-network test.')

        async def main():
            with tempfile.TemporaryDirectory() as td:
                cfg = _make_config(
                    td,
                    tools={
                        'web_search':
                        SimpleNamespace(
                            engines=['serpapi'],
                            serpapi_api_key=os.getenv('SERPAPI_API_KEY'),
                            serpapi_provider=os.getenv('SERPAPI_PROVIDER',
                                                       'google'),
                            fetch_content=True,
                            enable_chunking=False,
                            max_results=1,
                        )
                    },
                )
                tool = WebSearchTool(cfg)
                await tool.connect()

                res = await tool.call_tool(
                    server_name='web_search',
                    tool_name='serpapi_search',
                    tool_args={
                        'query': 'ModelScope',
                        'num_results': 1,
                        'fetch_content': False,
                    },
                )
                data = json.loads(res)
                self.assertEqual(data['status'], 'ok')
                self.assertEqual(data['engine'], 'serpapi')
                self.assertGreaterEqual(data['count'], 0)
                if data['count'] > 0:
                    self.assertIn('title', data['results'][0])
                    self.assertIn('url', data['results'][0])
                    self.assertIn('summary', data['results'][0])

                await tool.cleanup()

        asyncio.run(main())


class TestTodoListToolServer(unittest.TestCase):

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_todo_list_tool_write_read_render(self):

        async def main():
            with tempfile.TemporaryDirectory() as td:
                cfg = _make_config(
                    td,
                    tools={
                        'todo_list':
                        SimpleNamespace(
                            plan_filename='plan.json',
                            plan_md_filename='plan.md',
                            auto_render_md=True,
                        )
                    },
                )
                tool = TodoListTool(cfg)
                await tool.connect()

                tools = await tool.get_tools()
                self.assertIn('todo_list', tools)
                names = {t['tool_name'] for t in tools['todo_list']}
                self.assertEqual(names,
                                 {'todo_write', 'todo_read', 'todo_render_md'})

                # Write + merge update
                res1 = await tool.todo_write(
                    merge=True,
                    todos=[{
                        'id': 't1',
                        'content': 'do A',
                        'status': 'pending',
                        'priority': 'high',
                    }],
                )
                data1 = json.loads(res1)
                self.assertEqual(data1['status'], 'ok')
                self.assertEqual(len(data1['todos']), 1)

                res2 = await tool.todo_write(
                    merge=True,
                    todos=[{
                        'id': 't1',
                        'content': 'do A',
                        'status': 'completed',
                        'priority': 'high',
                    }],
                )
                data2 = json.loads(res2)
                self.assertEqual(data2['todos'][0]['status'], 'completed')

                # Read
                read = await tool.todo_read()
                todos = json.loads(read)
                self.assertEqual(todos[0]['id'], 't1')

                # Render markdown
                msg = await tool.todo_render_md()
                self.assertIn('OK: rendered plan markdown', msg)

                # Files exist
                self.assertTrue(os.path.exists(os.path.join(td, 'plan.json')))
                self.assertTrue(os.path.exists(os.path.join(td, 'plan.md')))

        asyncio.run(main())


class TestEvidenceToolServer(unittest.TestCase):

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_evidence_tool_write_get_list_search_delete(self):

        async def main():
            with tempfile.TemporaryDirectory() as td:
                cfg = _make_config(
                    td, tools={'evidence_store': SimpleNamespace()})
                tool = EvidenceTool(cfg)
                await tool.connect()

                tools = await tool.get_tools()
                self.assertIn('evidence_store', tools)

                res = await tool.write_note(
                    title='Finding A',
                    claim='Claim A',
                    supports='Support A',
                    sources=[{
                        'url': 'https://example.com/src',
                        'published_at': '2026-01-01',
                        'source_tier': 'primary',
                    }],
                    summary='summary A',
                    task_id='task_1',
                    tags=['tag1', 'tag2'],
                    quality_score=80,
                )
                data = json.loads(res)
                self.assertEqual(data['status'], 'ok')
                note_id = data['note_id']

                idx = json.loads(await tool.load_index())
                self.assertEqual(idx['status'], 'ok')
                self.assertEqual(idx['total_notes'], 1)

                got = json.loads(await tool.get_note(
                    note_id=note_id, parse_note=True))
                self.assertEqual(got['status'], 'ok')
                self.assertEqual(got['note']['note_id'], note_id)
                self.assertEqual(got['note']['claim'], 'Claim A')

                listed = json.loads(await tool.list_notes(
                    task_id='task_1', tags=['tag1']))
                self.assertEqual(listed['status'], 'ok')
                self.assertEqual(listed['count'], 1)

                listed2 = json.loads(await tool.list_notes(min_quality=90))
                self.assertEqual(listed2['count'], 0)

                searched = json.loads(await
                                      tool.search_notes(keyword='Finding'))
                self.assertEqual(searched['status'], 'ok')
                self.assertEqual(searched['count'], 1)

                deleted = json.loads(await tool.delete_note(note_id=note_id))
                self.assertEqual(deleted['status'], 'ok')

                missing = json.loads(await tool.get_note(note_id=note_id))
                self.assertEqual(missing['status'], 'error')

        asyncio.run(main())


class TestReportToolServer(unittest.TestCase):

    @unittest.skipUnless(test_level() >= 0, 'skip test in current test level')
    def test_report_tool_outline_chapter_draft_conflict(self):

        async def main():
            with tempfile.TemporaryDirectory() as td:
                # Prepare evidence using EvidenceTool to ensure realistic on-disk structure.
                ev_cfg = _make_config(
                    td, tools={'evidence_store': SimpleNamespace()})
                ev = EvidenceTool(ev_cfg)
                await ev.connect()
                n1 = json.loads(await ev.write_note(
                    title='N1',
                    claim='C1',
                    supports='S1',
                    sources=[{
                        'url': 'https://example.com/1'
                    }],
                    summary='sum1',
                    task_id='task_1',
                    tags=['t'],
                ))
                n2 = json.loads(await ev.write_note(
                    title='N2',
                    claim='C2',
                    supports='S2',
                    sources=[{
                        'url': 'https://example.com/2'
                    }],
                    summary='sum2',
                    task_id='task_1',
                    tags=['t'],
                ))
                note_ids = [n1['note_id'], n2['note_id']]

                cfg = _make_config(
                    td, tools={'report_generator': SimpleNamespace()})
                tool = ReportTool(cfg)
                await tool.connect()

                outline_res = json.loads(await tool.commit_outline(
                    title='My Report',
                    chapters=[{
                        'title': 'Ch1',
                        'goals': ['g1'],
                        'sections_description': 'sec',
                        'candidate_evidence': note_ids,
                    }],
                ))
                self.assertEqual(outline_res['status'], 'ok')

                bundle = json.loads(await tool.prepare_chapter_bundle(
                    chapter_id=1,
                    relevant_evidence=[note_ids[1]],
                    need_raw_chunks=False,
                ))
                self.assertEqual(bundle['status'], 'ok')
                self.assertEqual(bundle['chapter_id'], 1)
                self.assertEqual(bundle['evidence_count'], 2)
                self.assertTrue(
                    os.path.exists(os.path.join(td, bundle['meta_path'])))

                chapter_res = json.loads(await tool.commit_chapter(
                    chapter_id=1,
                    reranked_evidence=note_ids,
                    content='# Ch1\n\nhello\n',
                    cited_urls=['https://example.com/1'],
                ))
                self.assertEqual(chapter_res['status'], 'ok')
                self.assertTrue(
                    os.path.exists(os.path.join(td, chapter_res['path'])))

                # Draft assembly requires all chapters completed.
                draft = json.loads(await tool.assemble_draft(
                    include_toc=True, include_references=True))
                self.assertEqual(draft['status'], 'ok')
                self.assertTrue(
                    os.path.exists(os.path.join(td, draft['draft_path'])))

                conflict = json.loads(await tool.commit_conflict(
                    description='conflict',
                    evidence_ids=note_ids,
                    chapter_id=1,
                    resolution='resolved',
                ))
                self.assertEqual(conflict['status'], 'ok')

                status = json.loads(await tool.get_status())
                self.assertTrue(status['outline_exists'])
                self.assertEqual(status['progress'], '1/1')
                self.assertTrue(status['draft_exists'])
                self.assertGreaterEqual(status['conflicts_count'], 1)

                updated = json.loads(await tool.update_outline(
                    chapter_id=1,
                    updates={'title': 'Ch1 updated'},
                ))
                self.assertEqual(updated['status'], 'ok')

                not_impl = json.loads(await tool.load_chunk(chunk_ids=['c1']))
                self.assertEqual(not_impl['status'], 'not_implemented')

        asyncio.run(main())


if __name__ == '__main__':
    unittest.main()
