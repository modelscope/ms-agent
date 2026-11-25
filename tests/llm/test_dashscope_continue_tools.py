# Copyright (c) ModelScope Contributors. All rights reserved.
"""DashScope legacy continuation must send provider-shaped tool schemas.

``generate()`` formats tools with ``format_tools()`` before the first request
but passes the raw internal ``Tool`` dicts into continuation. On a truncated
assistant turn (``finish_reason='length'``) the DashScope override forwarded
those raw dicts straight to ``_call_llm`` and the API rejected them with a 400.
"""
from unittest.mock import MagicMock, patch

from ms_agent.llm.dashscope_llm import DashScope
from ms_agent.llm.utils import Message

RAW_TOOL = {'tool_name': 't', 'description': '', 'parameters': {}}


def test_dashscope_continue_gen_formats_tools():
    # Bypass __init__ so no client, credentials or network are created.
    llm = DashScope.__new__(DashScope)
    messages = [Message(role='user', content='hi')]
    continuation = Message(role='assistant', content='truncated answer')

    call_llm = MagicMock(return_value='sentinel')
    with patch.object(llm, '_call_llm', call_llm):
        result = llm._call_llm_for_continue_gen(
            messages, continuation, tools=[RAW_TOOL])

    assert result == 'sentinel'
    forwarded = call_llm.call_args.kwargs['tools']
    assert forwarded[0]['type'] == 'function'
    assert forwarded[0]['function']['name'] == 't'
    # Parsing at the boundary leaves the caller's internal schema untouched.
    assert RAW_TOOL == {'tool_name': 't', 'description': '', 'parameters': {}}
