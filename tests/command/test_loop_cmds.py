"""Tests for the /loop slash command.

The handler parses the three loop forms, writes loop config onto the Runtime,
and returns a SUBMIT_PROMPT for the first iteration -- or, for long/detached
cadences, registers a persistent cron job instead of looping in-session.
"""
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks.loop_controller import SELF_PACED_SUFFIX
from ms_agent.command.builtin import register_builtin_commands
from ms_agent.command.builtin.loop_cmds import (
    CRON_THRESHOLD_SECONDS,
    DEFAULT_MAINTENANCE_PROMPT,
    _parse_interval,
)
from ms_agent.command.router import CommandRouter
from ms_agent.command.types import CommandContext, CommandResultType


def _router():
    r = CommandRouter()
    register_builtin_commands(r)
    return r


def _runtime(output_dir=None):
    rt = Runtime()
    if output_dir is not None:
        rt.llm = SimpleNamespace(
            config=OmegaConf.create({'output_dir': str(output_dir)}))
    return rt


def _ctx(text, router, runtime):
    cmd, args = CommandRouter.parse_input(text)
    return CommandContext(
        raw_input=text,
        command_name=cmd,
        args=args,
        runtime=runtime,
        extra={'router': router, 'messages': []},
    )


async def _dispatch(text, router, runtime):
    return await router.dispatch(_ctx(text, router, runtime))


class TestParsing:
    def test_leading_interval(self):
        assert _parse_interval('5m check ci') == (300, '5m', 'check ci')

    def test_trailing_every(self):
        assert _parse_interval('check ci every 30m') == (1800, '30m',
                                                         'check ci')

    def test_no_interval(self):
        assert _parse_interval('just watch') == (None, None, 'just watch')

    def test_hours_and_slash_body(self):
        assert _parse_interval('1h /review') == (3600, '1h', '/review')


class TestInSessionModes:
    @pytest.mark.asyncio
    async def test_interval_mode(self):
        router, rt = _router(), _runtime()
        result = await _dispatch('/loop 5m check the build', router, rt)
        assert result.type == CommandResultType.SUBMIT_PROMPT
        assert rt.loop_active is True
        assert rt.loop_mode == 'interval'
        assert rt.loop_interval == 300
        assert rt.loop_prompt == 'check the build'
        assert result.content == 'check the build'

    @pytest.mark.asyncio
    async def test_self_paced_mode(self):
        router, rt = _router(), _runtime()
        result = await _dispatch('/loop keep an eye on CI', router, rt)
        assert result.type == CommandResultType.SUBMIT_PROMPT
        assert rt.loop_mode == 'self_paced'
        assert rt.loop_interval is None
        assert result.content.startswith('keep an eye on CI')
        assert SELF_PACED_SUFFIX.strip()[:20] in result.content

    @pytest.mark.asyncio
    async def test_maintenance_mode_default(self, tmp_path):
        router, rt = _router(), _runtime(output_dir=tmp_path)
        result = await _dispatch('/loop', router, rt)
        assert result.type == CommandResultType.SUBMIT_PROMPT
        assert rt.loop_mode == 'maintenance'
        assert result.content.startswith(DEFAULT_MAINTENANCE_PROMPT[:30])

    @pytest.mark.asyncio
    async def test_maintenance_loop_md_override(self, tmp_path):
        cfg_dir = tmp_path / '.ms_agent'
        cfg_dir.mkdir()
        (cfg_dir / 'loop.md').write_text('CUSTOM MAINTENANCE PLAYBOOK')
        router, rt = _router(), _runtime(output_dir=tmp_path)
        result = await _dispatch('/loop', router, rt)
        assert result.content.startswith('CUSTOM MAINTENANCE PLAYBOOK')

    @pytest.mark.asyncio
    async def test_flags_max_and_budget(self):
        router, rt = _router(), _runtime()
        result = await _dispatch('/loop --max 10 --budget 5000 watch', router,
                                 rt)
        assert result.type == CommandResultType.SUBMIT_PROMPT
        assert rt.loop_max == 10
        assert rt.loop_token_budget == 5000
        assert rt.loop_prompt == 'watch'

    @pytest.mark.asyncio
    async def test_nested_loop_body_rejected(self):
        router, rt = _router(), _runtime()
        result = await _dispatch('/loop 5m /loop do it', router, rt)
        assert result.type == CommandResultType.MESSAGE
        assert 'cannot itself be /loop' in result.content
        assert rt.loop_active is False


class TestSubCommands:
    @pytest.mark.asyncio
    async def test_status_inactive(self):
        router, rt = _router(), _runtime()
        result = await _dispatch('/loop status', router, rt)
        assert 'No active loop' in result.content

    @pytest.mark.asyncio
    async def test_status_active(self):
        router, rt = _router(), _runtime()
        await _dispatch('/loop 5m watch', router, rt)
        result = await _dispatch('/loop status', router, rt)
        assert 'active (interval)' in result.content

    @pytest.mark.asyncio
    async def test_stop_clears_loop(self):
        router, rt = _router(), _runtime()
        await _dispatch('/loop 5m watch', router, rt)
        assert rt.loop_active is True
        result = await _dispatch('/loop stop', router, rt)
        assert 'stopped' in result.content.lower()
        assert rt.loop_active is False

    @pytest.mark.asyncio
    async def test_stop_without_active_loop(self):
        router, rt = _router(), _runtime()
        result = await _dispatch('/loop off', router, rt)
        assert 'No active loop' in result.content


class TestCronBridge:
    @pytest.mark.asyncio
    async def test_long_interval_creates_cron_job(self, tmp_path, monkeypatch):
        monkeypatch.setenv('MS_AGENT_CRON_WORKSPACE', str(tmp_path))
        router, rt = _router(), _runtime()
        result = await _dispatch('/loop 2h nightly digest', router, rt)
        assert result.type == CommandResultType.MESSAGE
        assert 'cron job' in result.content
        assert 'every 2h' in result.content
        # Not an in-session loop.
        assert rt.loop_active is False
        # The job is persisted in the workspace.
        from ms_agent.cron.service import CronService
        jobs = CronService(workspace=tmp_path).manager.list_jobs()
        assert len(jobs) == 1
        spec, _state = jobs[0]
        assert spec.prompt == 'nightly digest'
        assert spec.session_mode == 'persistent'

    @pytest.mark.asyncio
    async def test_detach_flag_forces_cron(self, tmp_path, monkeypatch):
        monkeypatch.setenv('MS_AGENT_CRON_WORKSPACE', str(tmp_path))
        router, rt = _router(), _runtime()
        result = await _dispatch('/loop 5m --detach watch ci', router, rt)
        assert result.type == CommandResultType.MESSAGE
        assert 'cron job' in result.content
        assert rt.loop_active is False

    @pytest.mark.asyncio
    async def test_times_flag_bounds_cron_repeat(self, tmp_path, monkeypatch):
        monkeypatch.setenv('MS_AGENT_CRON_WORKSPACE', str(tmp_path))
        router, rt = _router(), _runtime()
        await _dispatch('/loop 2h --times 3 digest', router, rt)
        from ms_agent.cron.service import CronService
        jobs = CronService(workspace=tmp_path).manager.list_jobs()
        spec, _state = jobs[0]
        assert spec.repeat is not None
        assert spec.repeat.times == 3


class TestThreshold:
    def test_threshold_boundary(self):
        # 1h is exactly the threshold -> cron bridge.
        assert CRON_THRESHOLD_SECONDS == 3600
