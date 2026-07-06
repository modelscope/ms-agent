"""Tests for ms_agent.cron.executor."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import pytest

from ms_agent.cron.executor import JobExecutor, _CRON_CONTEXT, is_in_cron_context
from ms_agent.cron.types import CronJobSpec, CronSchedule, ExecutionResult
from ms_agent.llm.utils import Message


@pytest.fixture
def executor(tmp_path):
    return JobExecutor(
        default_timeout=10,
        output_dir=tmp_path / 'output',
        session_dir=tmp_path / 'sessions',
    )


class TestContextVar:
    def test_default_not_in_cron(self):
        assert is_in_cron_context() is False

    def test_context_var_set_during_execution(self):
        token = _CRON_CONTEXT.set(True)
        assert is_in_cron_context() is True
        _CRON_CONTEXT.reset(token)
        assert is_in_cron_context() is False


class TestExtractOutput:
    def test_extract_from_message_list(self, executor):
        messages = [
            Message(role='user', content='hi'),
            Message(role='assistant', content='hello back'),
        ]
        assert executor._extract_output(messages) == 'hello back'

    def test_extract_from_dict_list(self, executor):
        messages = [
            {'role': 'user', 'content': 'hi'},
            {'role': 'assistant', 'content': 'result'},
        ]
        assert executor._extract_output(messages) == 'result'

    def test_extract_from_string(self, executor):
        assert executor._extract_output('direct string') == 'direct string'

    def test_extract_empty(self, executor):
        assert executor._extract_output(None) == ''
        assert executor._extract_output([]) == ''


class TestJobExecutorExecution:
    @pytest.mark.asyncio
    async def test_successful_execution(self, executor):
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=[
            Message(role='assistant', content='mock result'),
        ])
        mock_engine.cleanup_tools = AsyncMock()

        job = CronJobSpec(id='exec1', prompt='test prompt')

        with patch.object(executor, '_build_engine', return_value=mock_engine):
            result = await executor.execute(job, config=MagicMock())

        assert result.success is True
        assert result.output == 'mock result'
        assert result.duration_ms >= 0
        mock_engine.run.assert_called_once_with('test prompt')

    @pytest.mark.asyncio
    async def test_timeout_handling(self, executor):
        async def slow_run(prompt):
            await asyncio.sleep(100)
            return []

        mock_engine = MagicMock()
        mock_engine.run = slow_run
        mock_engine.cleanup_tools = AsyncMock()

        job = CronJobSpec(id='timeout1', prompt='slow', timeout=1)

        with patch.object(executor, '_build_engine', return_value=mock_engine):
            result = await executor.execute(job, config=MagicMock())

        assert result.success is False
        assert 'timed out' in result.error.lower()

    @pytest.mark.asyncio
    async def test_exception_handling(self, executor):
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(side_effect=RuntimeError('engine broke'))
        mock_engine.cleanup_tools = AsyncMock()

        job = CronJobSpec(id='err1', prompt='fail')

        with patch.object(executor, '_build_engine', return_value=mock_engine):
            result = await executor.execute(job, config=MagicMock())

        assert result.success is False
        assert 'engine broke' in result.error

    @pytest.mark.asyncio
    async def test_recursive_cron_protection(self, executor):
        token = _CRON_CONTEXT.set(True)
        try:
            job = CronJobSpec(id='recurse1', prompt='recursive')
            result = await executor.execute(job, config=MagicMock())
            assert result.success is False
            assert 'Recursive' in result.error
        finally:
            _CRON_CONTEXT.reset(token)

    @pytest.mark.asyncio
    async def test_cleanup_called_on_success(self, executor):
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=[
            Message(role='assistant', content='ok'),
        ])
        mock_engine.cleanup_tools = AsyncMock()

        job = CronJobSpec(id='cleanup1', prompt='test')

        with patch.object(executor, '_build_engine', return_value=mock_engine):
            await executor.execute(job, config=MagicMock())

        mock_engine.cleanup_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_output_file_written(self, executor, tmp_path):
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value=[
            Message(role='assistant', content='written output'),
        ])
        mock_engine.cleanup_tools = AsyncMock()

        job = CronJobSpec(id='write1', prompt='test')

        with patch.object(executor, '_build_engine', return_value=mock_engine):
            result = await executor.execute(job, config=MagicMock())

        assert result.success
        output_dir = tmp_path / 'output' / 'write1'
        assert output_dir.exists()
        md_files = list(output_dir.glob('*.md'))
        assert len(md_files) == 1
        assert md_files[0].read_text() == 'written output'
