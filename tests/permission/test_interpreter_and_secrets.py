"""Two holes the path policy had: an interpreter's argument is a program, so
extracting paths from it proves nothing; and the sensitive-path list was only
ever consulted for writes, so the files it names could be read out."""
import asyncio

import pytest

from ms_agent.permission.ask_resolver import (REMEMBERABLE_ASK_CATEGORIES,
                                              resolve_ask)
from ms_agent.permission.config import PermissionConfig, SafetyConfig
from ms_agent.permission.enforcer import (PermissionDecision,
                                          PermissionEnforcer)
from ms_agent.permission.handler import (PermissionAction, PermissionResponse,
                                         WebPermissionHandler)
from ms_agent.permission.shell_validator import (PathSafetyConfig,
                                                 ShellPathValidator)

WS = '/tmp/ms-agent-secret-tests'


class _Emitter:

    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


def _validator() -> ShellPathValidator:
    cfg = SafetyConfig()
    allowed = list(cfg.effective_allowed_directories(WS))
    return ShellPathValidator(
        allowed_dirs=allowed,
        safety_config=PathSafetyConfig(
            workspace_root=WS,
            allowed_directories=tuple(allowed),
            sensitive_read_paths=cfg.sensitive_read_paths,
        ))


def _enforcer():
    emitter = _Emitter()
    handler = WebPermissionHandler(emitter)
    return emitter, handler, PermissionEnforcer(
        config=PermissionConfig(mode='interactive'), handler=handler)


@pytest.mark.parametrize('command', [
    'python3 -c "import os; os.remove(\'/etc/hosts\')"',
    'node -e "require(\'fs\').unlinkSync(\'/etc/hosts\')"',
    'bash -c "rm -rf /"',
    'python3 -',
])
def test_inline_code_is_surfaced_rather_than_waved_through(command):
    decision = _validator().check(command)
    assert decision.action == 'ask', command
    assert decision.category == 'interpreter_exec', command


@pytest.mark.parametrize('command', ['python3 build.py', 'node server.js'])
def test_running_a_script_inside_the_workspace_stays_quiet(command):
    assert _validator().check(command).action == 'allow', command


def test_script_outside_the_workspace_is_still_judged():
    assert _validator().check('python3 /etc/evil.py').action != 'allow'


@pytest.mark.parametrize('mode, expected', [
    ('auto', 'allow'),
    ('interactive', 'ask'),
    ('strict', 'deny'),
])
def test_interpreter_resolution_follows_the_mode(mode, expected):
    decision = _validator().check('python3 -c "print(1)"')
    assert resolve_ask(decision, mode, 'loose').action == expected


@pytest.mark.parametrize('command', [
    'cat ~/.ssh/id_rsa',
    'cat /home/other/.aws/credentials',
    'cat /srv/certs/server.pem',
])
def test_credentials_are_never_read_unattended(command):
    decision = _validator().check(command)
    assert decision.category == 'sensitive_read', command
    assert resolve_ask(decision, 'auto', 'loose').action == 'deny', command
    assert resolve_ask(decision, 'interactive', 'loose').action == 'ask'


def test_write_protection_does_not_become_read_refusal():
    """``sensitive_paths`` stops `.git/config` being CHANGED. Reading it is
    how an agent finds a git remote; refusing that would be a regression."""
    decision = _validator().check('cat .git/config')
    assert decision.category != 'sensitive_read'
    assert resolve_ask(decision, 'auto', 'loose').action == 'allow'


def test_only_the_settleable_category_is_rememberable():
    """Inline code is the same decision every time; a credential read is risky
    because of the specific file, so it must be decided each time."""
    assert REMEMBERABLE_ASK_CATEGORIES == frozenset({'interpreter_exec'})


@pytest.mark.asyncio
async def test_always_allow_actually_sticks_for_inline_code():
    """An `interpreter_exec` ask used to take the forced path, which skips
    memory — "always run" stored a pattern that was never consulted."""
    emitter, handler, enforcer = _enforcer()
    tool = 'code_executor---shell_executor'
    ask = PermissionDecision(
        action='ask', reason='runs code inline', rememberable=True)

    first = asyncio.create_task(
        enforcer.check(
            tool, {'command': 'python3 -c "print(1)"'}, force_decision=ask))
    await asyncio.sleep(0.05)
    handler.resolve(
        emitter.events[0]['request_id'],
        PermissionResponse(
            action=PermissionAction.ALLOW_ALWAYS, pattern=f'{tool}:python3 *'))
    assert (await first).action == 'allow'

    # Second time: no card at all.
    before = len(emitter.events)
    again = await enforcer.check(
        tool, {'command': 'python3 -c "print(2)"'}, force_decision=ask)
    assert again.action == 'allow'
    assert len(emitter.events) == before, 'asked again despite "always allow"'


@pytest.mark.asyncio
async def test_a_credential_read_still_asks_every_time():
    emitter, handler, enforcer = _enforcer()
    tool = 'code_executor---shell_executor'
    ask = PermissionDecision(action='ask', reason='reads a sensitive path')

    first = asyncio.create_task(
        enforcer.check(
            tool, {'command': 'cat ~/.ssh/id_rsa'}, force_decision=ask))
    await asyncio.sleep(0.05)
    handler.resolve(
        emitter.events[0]['request_id'],
        PermissionResponse(
            action=PermissionAction.ALLOW_ALWAYS, pattern=f'{tool}:cat *'))
    await first

    before = len(emitter.events)
    second = asyncio.create_task(
        enforcer.check(
            tool, {'command': 'cat ~/.ssh/id_ed25519'}, force_decision=ask))
    await asyncio.sleep(0.05)
    assert len(emitter.events) == before + 1, 'a credential read was waved through'
    second.cancel()
    await asyncio.gather(second, return_exceptions=True)
