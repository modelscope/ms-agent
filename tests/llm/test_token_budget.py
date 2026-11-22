# Copyright (c) ModelScope Contributors. All rights reserved.
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

from omegaconf import OmegaConf

from ms_agent.llm import token_budget
from ms_agent.llm.utils import Message
from ms_agent.memory.condenser.context_compressor import ContextCompressor
from ms_agent.session.strategies.summary_compactor import SummaryCompactor
from ms_agent.session.strategies.tool_pruner import ToolOutputPruner


def compressor():
    return ContextCompressor(OmegaConf.create({'memory': {'enable_summary': False}}))


def test_base64_length_does_not_determine_the_budget():
    def content(size):
        return [{'type': 'text', 'text': 'describe'}, {'type': 'image_url',
                'image_url': {'url': 'data:image/png;base64,' + 'A' * size}}]
    small, large = [Message(role='user', content=content(n)) for n in [1000, 2_000_000]]
    c = compressor()
    assert c.estimate_total_tokens([small]) == c.estimate_total_tokens([large])
    assert not c.is_overflow([large])
    assert token_budget.estimate_message_tokens(large) < 10_000


def test_attachment_and_inline_representation_are_not_double_counted():
    msg = {'role': 'tool', 'content': 'picture', 'attachments': [
        {'type': 'image', 'path': 'test.png', 'media_type': 'image/png'}]}
    cost = token_budget.estimate_message_tokens(msg)
    assert cost > token_budget.estimate_text_tokens('picture')
    msg['content'] = [{'type': 'text', 'text': 'picture'},
                      {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}]
    assert token_budget.estimate_message_tokens(msg) == cost


def test_usage_anchor_covers_prefix_but_not_new_images():
    rows = [{'role': 'user', 'content': 'question'},
            {'role': 'assistant', 'content': 'ok', 'prompt_tokens': 100, 'completion_tokens': 2},
            {'role': 'user', 'content': '', 'attachments': [
                {'type': 'image', 'path': 'a.png', 'media_type': 'image/png'}]}]
    assert token_budget.estimate_total_tokens(rows) == 102 + token_budget.estimate_message_tokens(rows[-1])


def test_changed_prefix_cannot_hide_behind_old_usage():
    rows = [{'role': 'system', 'content': 'new instructions' * 2000},
            {'role': 'assistant', 'content': 'ok', 'prompt_tokens': 100}]
    assert token_budget.estimate_total_tokens(rows) > 100


def test_summary_never_contains_encoded_pixels():
    c = compressor()
    c.llm = Mock()
    c.llm.generate.return_value = Message(role='assistant', content='summary')
    c.summarize([Message(role='user', content=[{'type': 'text', 'text': 'look'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,SECRET_PIXELS'}}])])
    prompt = c.llm.generate.call_args.args[0][0].content
    assert 'look' in prompt and 'omitted' in prompt
    assert 'SECRET_PIXELS' not in prompt and 'base64' not in prompt


def test_uncompressible_latest_request_is_preserved_without_summary_calls():
    c = compressor()
    c.llm = Mock()
    messages = [Message(role='system', content='sys'), Message(role='user', content='x' * 480000)]
    assert c.compress(messages) == messages
    assert c.compress(messages) == messages
    c.llm.generate.assert_not_called()


def test_summary_that_increases_budget_is_not_committed_or_repeated():
    llm = SimpleNamespace(generate=Mock())
    compactor = SummaryCompactor(llm)
    # Isolate the final acceptance guard from the hierarchical generator's
    # separate input/output limits and internal bounded retries.
    compactor._generate_summary = Mock(return_value='x' * 6000)
    rows = [{'role': 'user', 'content': 'a' * 1000}, {'role': 'assistant', 'content': 'b' * 1000},
            {'role': 'user', 'content': 'last question'}]
    config = {'context_limit': 500, 'reserved_buffer': 10}
    for _ in range(2):
        result, meta = compactor.apply(rows, rows, config)
        assert result == rows and meta is None
    assert compactor._generate_summary.call_count == 1


def test_session_pruning_preserves_images_and_billing_evidence():
    rows = [{'role': 'tool', 'content': 't' * 16000},
        {'role': 'tool', 'content': '', 'attachments': [
        {'type': 'image', 'path': 'a.png', 'media_type': 'image/png'}]},
        {'role': 'assistant', 'content': 'ok', 'prompt_tokens': 5000, 'completion_tokens': 1}]
    result, meta = ToolOutputPruner().apply(deepcopy(rows), rows,
        {'context_limit': 2000, 'reserved_buffer': 0, 'prune_protect': 0})
    assert meta is not None and meta['tokens_after'] < meta['tokens_before']
    assert result[1]['attachments'] == rows[1]['attachments']
    assert result[2]['_usage_invalidated']
    assert result[2]['prompt_tokens'] == rows[2]['prompt_tokens'] == 5000
    assert len(rows[0]['content']) == 16000 and '_usage_invalidated' not in rows[2]


def test_legacy_pruning_invalidates_continuation_usage_without_mutating_history():
    usage = [{'usage': {'prompt_tokens': 5000, 'completion_tokens': 1}}]
    messages = [Message(role='tool', attachments=[{'type': 'image', 'path': 'a.png'}]),
                Message(role='assistant', content='ok', prompt_tokens=5000, usage_records=usage)]
    c = compressor()
    c.prune_protect = 0
    result = c.prune_tool_outputs(messages)
    assert result[0].attachments == [] and result[1].usage_records == []
    assert result[1].prompt_tokens == 0
    assert messages[0].attachments and messages[1].usage_records == usage


def test_summary_keeps_latest_image_only_message():
    refs = [{'type': 'image', 'path': 'a.png', 'media_type': 'image/png'}]
    rows = [{'role': 'user', 'content': 'x' * 12000},
            {'role': 'assistant', 'content': 'old answer'},
            {'role': 'user', 'content': '', 'attachments': refs}]
    llm = SimpleNamespace(generate=Mock(return_value=Message(role='assistant', content='short summary')))
    c = compressor()
    c.llm = llm
    c.context_limit, c.reserved_buffer = 2000, 0
    assert c.compress([Message(**r) for r in rows])[-1].attachments == refs
    result, meta = SummaryCompactor(llm).apply(rows, rows, {
        'context_limit': 2000, 'reserved_buffer': 0})
    assert meta is not None and result[-1]['attachments'] == refs
