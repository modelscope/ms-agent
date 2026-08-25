# Copyright (c) ModelScope Contributors. All rights reserved.
"""Per-tool output budgets, and why the generic cut needed an opt-out.

The generic truncator keeps the head and the tail of an oversized result and
splices a notice into the gap. That is right for prose and destructive for
structure: applied to JSON the notice lands inside a string literal, so the
payload stops parsing and the model receives neither the data nor an error.

Measured on web_search (2026-08-25): an 84,429-char result was cut at 20,000
and reached the model — and the UI — as invalid JSON, which is why search
results silently rendered with no sources. The protocol under test is the fix:
a tool declares its own budget (or declares that it bounds itself) and the
generic path leaves it alone.
"""
import json
import math

import pytest
from ms_agent.tools.base import SELF_MANAGED_OUTPUT, ToolBase
from ms_agent.tools.tool_manager import _truncate_tool_output


class _Tool:
    """Stands in for a tool instance; only the declared attrs are read."""

    def __init__(self, budget=None, keep='both'):
        if budget is not None:
            self.max_output_chars = budget
        self.truncate_keep = keep


# ----------------------------------------------------------- default behaviour

def test_undeclared_tool_keeps_the_global_cap(monkeypatch):
    """Tools that say nothing must behave exactly as before the protocol."""
    monkeypatch.setenv('MAX_TOOL_OUTPUT_LEN', '100')
    out = _truncate_tool_output('x' * 500, _Tool())
    assert len(out) < 500
    assert 'Output truncated' in out
    assert '500 chars total' in out


def test_short_output_is_untouched(monkeypatch):
    monkeypatch.setenv('MAX_TOOL_OUTPUT_LEN', '100')
    assert _truncate_tool_output('hello', _Tool()) == 'hello'


def test_base_class_default_is_the_global_cap():
    """ToolBase must not silently exempt everything — the cap is a safety net."""
    assert ToolBase.max_output_chars.fget(object()) is None
    assert ToolBase.truncate_keep.fget(object()) == 'both'


# ------------------------------------------------------------------- opt-outs

def test_self_managed_tool_is_never_cut(monkeypatch):
    monkeypatch.setenv('MAX_TOOL_OUTPUT_LEN', '10')
    payload = 'y' * 5000
    assert _truncate_tool_output(payload, _Tool(SELF_MANAGED_OUTPUT)) == payload
    assert SELF_MANAGED_OUTPUT == math.inf


def test_per_tool_budget_overrides_the_global_one(monkeypatch):
    monkeypatch.setenv('MAX_TOOL_OUTPUT_LEN', '10')  # would shred it
    out = _truncate_tool_output('z' * 900, _Tool(1000))
    assert out == 'z' * 900  # under ITS budget, so untouched


def test_budget_below_output_still_cuts():
    out = _truncate_tool_output('z' * 900, _Tool(100))
    assert 'Output truncated' in out


# ------------------------------------------------------------------ direction

def test_keep_head_preserves_the_beginning():
    out = _truncate_tool_output('A' * 100 + 'B' * 100, _Tool(100, keep='head'))
    assert out.startswith('A' * 100)
    assert 'B' not in out.split('[SYSTEM')[0]


def test_keep_tail_preserves_the_end():
    out = _truncate_tool_output('A' * 100 + 'B' * 100, _Tool(100, keep='tail'))
    assert out.endswith('B' * 100)


def test_keep_both_is_the_default_shape():
    out = _truncate_tool_output('A' * 100 + 'B' * 100, _Tool(100))
    assert out.startswith('A' * 50) and out.endswith('B' * 50)


# ------------------------------------------------- the regression, end to end

def _search_payload(n_rows: int, body_chars: int) -> dict:
    return {
        'status': 'ok',
        'query': '今日新闻',
        'engine': 'tavily',
        'count': n_rows,
        'results': [{
            'url': f'https://example.com/{i}',
            'title': f'result {i}',
            'content': '正' * body_chars,
        } for i in range(n_rows)],
    }


def test_generic_cut_would_corrupt_json():
    """Pins the failure this protocol exists to prevent."""
    raw = json.dumps(_search_payload(10, 5000), ensure_ascii=False, indent=2)
    cut = _truncate_tool_output(raw, _Tool(20000))
    with pytest.raises(json.JSONDecodeError):
        json.loads(cut)


def test_web_search_declares_a_budget_and_stays_under_it():
    from ms_agent.tools.search.websearch_tool import WebSearchTool

    tool = WebSearchTool.__new__(WebSearchTool)
    tool._max_output_chars = 20000

    payload = _search_payload(10, 5000)          # ~50k chars of bodies
    out = tool._bounded_json(payload)

    assert len(out) <= tool.max_output_chars
    parsed = json.loads(out)                      # THE point: still parseable
    assert parsed['results'], 'evidence rows must survive'
    assert parsed['results'][0]['url'].startswith('https://')
    # And the generic path is now a no-op for it.
    assert _truncate_tool_output(out, tool) == out


def test_bounded_json_sheds_rows_only_after_bodies():
    from ms_agent.tools.search.websearch_tool import WebSearchTool

    tool = WebSearchTool.__new__(WebSearchTool)
    tool._max_output_chars = 20000
    # Bodies alone overflow; dropping them should be enough to fit every row.
    out = json.loads(tool._bounded_json(_search_payload(8, 4000)))
    assert len(out['results']) == 8, 'rows kept when shedding bodies suffices'
    assert out.get('body_omitted') is True


def test_bounded_json_drops_rows_when_urls_alone_overflow():
    from ms_agent.tools.search.websearch_tool import WebSearchTool

    tool = WebSearchTool.__new__(WebSearchTool)
    tool._max_output_chars = 1200
    out = json.loads(tool._bounded_json(_search_payload(200, 50)))
    assert out['results_omitted'] > 0
    assert len(out['results']) < 200
    assert out['count'] == len(out['results'])


def test_small_payload_is_returned_verbatim():
    from ms_agent.tools.search.websearch_tool import WebSearchTool

    tool = WebSearchTool.__new__(WebSearchTool)
    tool._max_output_chars = 20000
    payload = _search_payload(2, 10)
    out = tool._bounded_json(payload)
    assert json.loads(out) == payload  # no shedding, no markers
