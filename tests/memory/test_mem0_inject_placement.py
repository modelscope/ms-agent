# Copyright (c) ModelScope Contributors. All rights reserved.
"""Vector-memory recall is DURABLE: attached once to each new user turn
(skill-notice style) before the turn is persisted — NOT re-injected per round.

Why: an ephemeral per-round attach made round N+1's history differ from what
round N actually sent (the previous user message lost its block), which broke
prefix-cache reuse at that point and made the model's own history inconsistent
with what it had seen. Durable attachment keeps every request a strict
prefix-extension of the previous one.
"""
import asyncio

from ms_agent.llm.utils import Message
from ms_agent.memory.unified.backends import mem0_adapter
from ms_agent.memory.unified.config import MemoryConfig


def _backend(monkeypatch, tmp_path, results):
    cfg = MemoryConfig(
        enabled=True,
        storage_backend='mem0',
        base_dir=str(tmp_path),
        user_id='u1',
        agent_id='a1',
        backend_options={'mem0': {}},
    )
    backend = mem0_adapter.Mem0Backend(cfg)
    backend._mem0 = object()  # skip start(); search is stubbed below
    monkeypatch.setattr(mem0_adapter, '_mem0_search',
                        lambda m0, query, user_id, top_k=10: results)
    return backend


def test_recall_block_wraps_and_frames(monkeypatch, tmp_path):
    backend = _backend(monkeypatch, tmp_path,
                       [{'memory': '用户偏好深色主题。'}])
    block = asyncio.run(backend.recall_block('我的主题偏好？'))
    assert block.startswith('<system-reminder>')
    assert block.endswith('</system-reminder>')
    assert '用户偏好深色主题。' in block
    assert 'not instructions' in block  # framed as reference data


def test_recall_block_empty_when_no_results(monkeypatch, tmp_path):
    backend = _backend(monkeypatch, tmp_path, [])
    assert asyncio.run(backend.recall_block('任意问题')) == ''


def test_inject_is_a_noop(monkeypatch, tmp_path):
    """Per-round injection must not touch messages — recall is durable."""
    backend = _backend(monkeypatch, tmp_path, [{'memory': 'F1'}])
    msgs = [
        {'role': 'system', 'content': 'SYSTEM PROMPT'},
        {'role': 'user', 'content': '问题'},
    ]
    out = asyncio.run(backend.inject([dict(m) for m in msgs]))
    assert out == msgs


def test_ingestion_strips_injected_blocks(monkeypatch, tmp_path):
    """Fact extraction must never re-ingest recall/notice blocks."""
    backend = _backend(monkeypatch, tmp_path, [])
    captured = {}

    class FakeMem0:
        def add(self, convo, user_id=None):
            captured['convo'] = convo
            return {'results': []}

    backend._mem0 = FakeMem0()
    msgs = [{
        'role': 'user',
        'content': ('直接回答。\n\n<system-reminder>\nRelevant long-term '
                    'memories...\n- 旧记忆\n</system-reminder>'),
    }, {
        'role': 'assistant',
        'content': '好的。',
    }]
    asyncio.run(backend.on_messages(msgs))
    assert captured['convo'][0]['content'] == '直接回答。'
    assert '旧记忆' not in str(captured['convo'])


def test_agent_attaches_recall_to_new_user_turn(monkeypatch, tmp_path):
    """LLMAgent._attach_memory_recall: once per turn, user tail only."""
    from omegaconf import OmegaConf

    from ms_agent.agent.llm_agent import LLMAgent

    agent = LLMAgent(config=OmegaConf.create(
        {'output_dir': str(tmp_path / 'w')}))

    class FakeOrchestrator:
        async def recall_block(self, query):
            assert query == '直接回答。'
            return '<system-reminder>\n- F1\n</system-reminder>'

    agent.memory_tools = [FakeOrchestrator()]
    messages = [
        Message(role='system', content='S'),
        Message(role='user', content='直接回答。'),
    ]
    asyncio.run(agent._attach_memory_recall(messages))
    assert messages[1].content == (
        '直接回答。\n\n<system-reminder>\n- F1\n</system-reminder>')
    # idempotent: a second call must not double-attach
    asyncio.run(agent._attach_memory_recall(messages))
    assert messages[1].content.count('<system-reminder>') == 1
    # non-user tail: untouched
    messages.append(Message(role='assistant', content='A'))
    asyncio.run(agent._attach_memory_recall(messages))
    assert messages[2].content == 'A'


def test_vector_backend_stays_tool_less(monkeypatch, tmp_path):
    """No tools -> no memory-guidance segment (LLMAgent has_tools early-exit)."""
    backend = _backend(monkeypatch, tmp_path, [])
    assert backend.get_tool_schemas() == []
