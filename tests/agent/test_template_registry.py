# Copyright (c) Alibaba, Inc. and its affiliates.
import os

from ms_agent.agent.templates import registry

BUILTINS = ['general', 'plan', 'explore', 'build', 'research']


def test_builtin_templates_resolve():
    for name in BUILTINS:
        d = registry.resolve_template_dir(name)
        assert d and os.path.isdir(d), name
        assert os.path.isfile(os.path.join(d, 'agent.yaml')), name


def test_unknown_name_returns_none():
    assert registry.resolve_template_dir('definitely-not-a-template') is None


def test_resolve_source_passthrough_for_paths_and_repo_ids():
    # Existing local paths win unchanged.
    assert registry.resolve_template_source('/tmp') == '/tmp'
    # ModelScope ids contain '/', so are never treated as template names.
    assert registry.resolve_template_source('org/repo') == 'org/repo'


def test_resolve_source_hits_builtin():
    out = registry.resolve_template_source('explore')
    assert out.endswith(os.path.join('templates', 'explore'))


def test_list_primary_and_subagent():
    primary = {t['name'] for t in registry.list_templates('primary')}
    sub = {t['name'] for t in registry.list_templates('subagent')}
    # `general` is mode=all, so it appears in both views.
    assert {'general', 'plan'} <= primary
    assert {'general', 'explore', 'build', 'research'} <= sub


def test_when_to_use_nonempty():
    for name in BUILTINS:
        assert registry.get_when_to_use(name).strip()
