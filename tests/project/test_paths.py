# Copyright (c) ModelScope Contributors. All rights reserved.
"""Every framework-internal path resolves under <work>/.ms_agent/ (or the
global ~/.ms_agent), so a work dir never accumulates scattered files."""
from pathlib import Path

from ms_agent.project import paths


def test_work_local_helpers_under_ms_agent(tmp_path):
    w = str(tmp_path)
    internal = str(paths.local_internal_dir(w))
    for fn in (paths.memory_dir, paths.snapshots_dir, paths.artifacts_dir,
               paths.index_dir, paths.locks_dir, paths.tmp_dir,
               paths.subagents_dir, paths.web_search_dir):
        assert str(fn(w)).startswith(internal), fn.__name__
    assert str(paths.search_index_dir(w, 'rag')).startswith(internal)
    assert str(paths.stats_file(w)).startswith(internal)


def test_global_helpers_under_ms_agent_home(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path / 'home'))
    home = str((tmp_path / 'home').resolve())
    assert str(paths.global_projects_root()).startswith(home)
    assert str(paths.global_logs_dir()).startswith(home)
    assert str(paths.global_project_dir('/some/work')).startswith(home)


def test_project_internal_file_prefers_new_then_legacy(tmp_path):
    proj = tmp_path / 'proj'
    # nothing exists -> returns the new .ms_agent path
    p = paths.project_internal_file(proj, 'mcp.json')
    assert p.parent.name == '.ms_agent'
    # only legacy exists -> returns legacy
    legacy = proj / '.ms-agent'
    legacy.mkdir(parents=True)
    (legacy / 'mcp.json').write_text('{}')
    assert paths.project_internal_file(proj, 'mcp.json').parent.name == '.ms-agent'
    # new exists -> prefers new
    new = proj / '.ms_agent'
    new.mkdir(parents=True)
    (new / 'mcp.json').write_text('{}')
    assert paths.project_internal_file(proj, 'mcp.json').parent.name == '.ms_agent'


def test_project_key_stable_and_readable():
    assert paths.project_key('/Users/x/proj') == paths.project_key('/Users/x/proj')
    assert 'proj' in paths.project_key('/Users/x/proj')
