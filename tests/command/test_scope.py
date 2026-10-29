"""Scope helper: omit-token parsing and work-dir lookup."""
from types import SimpleNamespace

from omegaconf import OmegaConf

from ms_agent.command.scope import parse_optional_scope, work_dir_of
from ms_agent.command.types import CommandContext


def test_parse_optional_scope_needs_a_name_before_the_token():
    assert parse_optional_scope(['project']) == (None, ['project'])
    assert parse_optional_scope(['demo', 'project']) == ('project', ['demo'])
    assert parse_optional_scope(['/tmp/foo']) == (None, ['/tmp/foo'])
    assert parse_optional_scope(['/tmp/foo', 'global']) == (
        'global', ['/tmp/foo'])


def test_work_dir_prefers_llm_config():
    ctx = CommandContext(
        raw_input='/mcp',
        command_name='mcp',
        runtime=SimpleNamespace(
            llm=SimpleNamespace(
                config=OmegaConf.create({'output_dir': '/work'}))),
    )
    assert work_dir_of(ctx) == '/work'


def test_work_dir_accepts_fake_agent_config():
    ctx = CommandContext(
        raw_input='/mcp',
        command_name='mcp',
        runtime=SimpleNamespace(
            config=OmegaConf.create({'output_dir': '/agent'})),
    )
    assert work_dir_of(ctx) == '/agent'
