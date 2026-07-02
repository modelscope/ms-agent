"""Tests for hook context helpers."""

from ms_agent.hooks.context import (
    apply_hook_result_to_messages,
    condense_hook_attachments_for_llm,
    extract_latest_user_prompt,
    HookAttachment,
)
from ms_agent.hooks.events import HookResult
from ms_agent.llm.utils import Message


class TestContext:
    def test_extract_latest_user_prompt(self):
        msgs = [
            Message(role='system', content='sys'),
            Message(role='user', content='hello'),
        ]
        assert extract_latest_user_prompt(msgs) == 'hello'

    def test_condense_attachments(self):
        att = HookAttachment(
            type='hook_additional_context',
            hook_event='PostToolUse',
            tool_call_id='id1',
            content='extra info',
        )
        tool_msg = Message(role='tool', content='result', hook_attachments=[att])
        msgs = [tool_msg]
        out = condense_hook_attachments_for_llm(msgs)
        assert len(out) == 2
        assert '[hook:PostToolUse]' in out[1].content
        assert out[0].content == 'result'

    def test_condense_stop_blocking_feedback(self):
        from ms_agent.hooks.context import append_stop_blocking_feedback

        assistant = Message(role='assistant', content='done')
        msgs = [assistant]
        append_stop_blocking_feedback(msgs, 'not finished yet')
        out = condense_hook_attachments_for_llm(msgs)
        assert len(out) == 2
        assert 'Stop hook feedback:' in out[1].content
        assert 'not finished yet' in out[1].content

    def test_apply_deny_user_prompt(self):
        msgs = [Message(role='user', content='bad')]
        ok = apply_hook_result_to_messages(
            msgs,
            HookResult(action='deny', reason='no'),
            hook_event='UserPromptSubmit',
        )
        assert ok is False
