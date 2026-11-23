import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.llm.utils import Message
from ms_agent.memory.unified.config import MemoryConfig
from ms_agent.memory.unified.orchestrator import MemoryOrchestrator
from ms_agent.session.context_assembler import ContextAssembler, _dicts_to_messages
from ms_agent.session.session_log import SessionLog
from ms_agent.session.strategies.summary_compactor import SummaryCompactor


def test_default_pipeline_preserves_tool_evidence_until_summarized():
    agent = LLMAgent.__new__(LLMAgent)
    llm = SimpleNamespace(generate=Mock(return_value=Message('assistant', 'Key=KMS-5729')))
    agent.llm = llm
    strategies = agent._build_compaction_strategies(None)
    assert [s.name for s in strategies] == ['summary_compactor']
    rows = [
        {'role': 'user', 'content': 'Read procurement evidence'},
        {'role': 'assistant', 'tool_calls': [{'id': 'c1', 'tool_name': 'search', 'arguments': '{}'}]},
        {'role': 'tool', 'tool_call_id': 'c1', 'content': 'Key=KMS-5729\n' + 'X' * 15000},
        {'role': 'assistant', 'content': 'Read.'},
        {'role': 'user', 'content': 'What was the key?'},
    ]
    compacted, meta = strategies[0].apply(rows, rows, {
        'context_limit': 4000, 'input_limit': 3500, 'compression_threshold': 3000,
        'summary_max_tokens': 100,
    })
    assert meta
    assert any('Key=KMS-5729' in m.content for c in llm.generate.call_args_list for m in c.args[0])
    assert any('Key=KMS-5729' in m.get('content', '') for m in compacted)


def test_truncated_nonempty_summary_never_replaces_history(tmp_path):
    response = Message('assistant', '##')
    response.finish_reason = 'length'
    llm = SimpleNamespace(generate=Mock(return_value=response))
    log = SessionLog(tmp_path)
    log.append_messages([{'role': 'user', 'content': 'x' * 2000}, {'role': 'user', 'content': 'next'}])
    before = log.get_all_messages()
    assembler = ContextAssembler(log, [SummaryCompactor(llm)], {
        'context_limit': 4000, 'input_limit': 3500, 'compression_threshold': 400,
    })
    assembler.assemble()
    assert log.last_consolidated == 0
    assert log.get_all_messages() == before


def test_error_object_is_not_accepted_as_summary(tmp_path):
    llm = SimpleNamespace(generate=Mock(return_value=Message('assistant', '{"error":"incomplete"}')))
    log = SessionLog(tmp_path)
    log.append_messages([{'role': 'user', 'content': 'x' * 2000}, {'role': 'user', 'content': 'next'}])
    ContextAssembler(log, [SummaryCompactor(llm)], {
        'context_limit': 4000, 'input_limit': 3500, 'compression_threshold': 400,
    }).assemble()
    assert log.last_consolidated == 0
    assert llm.generate.call_count == 2


def test_short_fragments_are_kept_without_lossy_merge():
    llm = SimpleNamespace(generate=Mock(return_value=Message('assistant', 'A short independent fact.')))
    strategy = SummaryCompactor(llm)
    summary = strategy._generate_summary([{'role': 'user', 'content': 'x' * 3000}], {
        'context_limit': 4000, 'input_limit': 3500, 'summary_input_char_limit': 1000,
        'summary_max_tokens': 100, 'summary_target_tokens': 500,
    })
    assert summary.count('A short independent fact.') == 4
    assert llm.generate.call_count == 4
    assert all(c.args[0][0].role == 'system' and c.args[0][1].role == 'user'
               for c in llm.generate.call_args_list)


def test_summary_is_not_ingested_as_a_new_user_statement(tmp_path):
    class Backend:
        batches = []
        async def on_messages(self, messages, **kwargs):
            self.batches.append(messages)

    async def run():
        backend = Backend()
        orch = MemoryOrchestrator(MemoryConfig(base_dir=str(tmp_path), storage_backend='file'))
        orch._backend, orch._started = backend, True
        rows = _dicts_to_messages([
            {'role': 'user', 'content': 'A genuine new correction'},
            {'role': 'user', 'content': '[Conversation Summary]\nGenerated facts', 'context_summary': True},
        ])
        await orch.add(rows)
        assert [m['content'] for m in backend.batches[0]] == ['A genuine new correction']
        assert LLMAgent._msg_to_dict(rows[1])['context_summary']
        assert 'context_summary' not in rows[1].to_dict_clean()
    asyncio.run(run())


def test_memory_flush_excludes_system_and_synthetic_summary(tmp_path):
    from unittest.mock import AsyncMock

    async def run():
        backend = SimpleNamespace(on_pre_compress=AsyncMock())
        orch = MemoryOrchestrator(MemoryConfig(base_dir=str(tmp_path), storage_backend='file'))
        orch._backend, orch._started = backend, True
        rows = _dicts_to_messages([
            {'role': 'system', 'content': 'large system instructions'},
            {'role': 'user', 'content': 'genuine request'},
            {'role': 'tool', 'content': 'key evidence', 'tool_call_id': 'c1'},
            {'role': 'user', 'content': 'generated summary', 'context_summary': True},
        ])
        await orch.flush(rows)
        sent = backend.on_pre_compress.call_args.args[0]
        assert [m['content'] for m in sent] == ['genuine request', 'key evidence']
        assert sent[-1]['tool_call_id'] == 'c1'
    asyncio.run(run())


def test_file_ingest_ledger_waits_for_durable_queue_write(tmp_path):
    from ms_agent.memory.unified.backends.file_based import FileBasedBackend

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        class Queue:
            async def add_nowait(self, *args):
                entered.set()
                await release.wait()
                raise RuntimeError('write failed')
        config = MemoryConfig(base_dir=str(tmp_path), storage_backend='file', retrieval_strategy='fts')
        backend = FileBasedBackend(config)
        backend._update_queue = Queue()
        orch = MemoryOrchestrator(config)
        orch._backend, orch._started = backend, True
        task = asyncio.create_task(orch.add([Message('user', 'must survive')]))
        await entered.wait()
        assert not orch._ledger_load()
        release.set()
        await task
        assert not orch._ledger_load()
        assert orch.ingest_status['state'] == 'error'
    asyncio.run(run())


@pytest.mark.parametrize('model,expected', [('qwen3.8-max', 'off'), ('glm-5.3', 'low')])
def test_summary_uses_lowest_supported_effort_without_changing_main_config(model, expected):
    config = OmegaConf.create({
        'llm': {'service': 'alibaba-token-plan-cn', 'model': model,
                'base_url': 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'},
        'generation_config': {'reasoning_effort': 'high'},
    })
    llm = SimpleNamespace(config=config, generate=Mock(return_value=Message('assistant', 'summary')))
    result = SummaryCompactor(llm)._generate_summary([{'role': 'user', 'content': 'evidence'}], {
        'context_limit': 16000, 'input_limit': 12000, 'summary_max_tokens': 256,
    })
    assert result == 'summary'
    assert llm.generate.call_args.kwargs['reasoning_effort'] == expected
    assert llm.generate.call_args.kwargs['max_continue_runs'] == 0
    assert config.generation_config.reasoning_effort == 'high'
