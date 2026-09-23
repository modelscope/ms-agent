"""Usability e2e: prompts, defaults, and acceptance-doc conflicts.

These tests are written from a user/developer seat, not from the
implementation. A case marked ``xfail`` is a product issue we want fixed;
unmarked failures mean a regression. Comments that mention ``e2e.md`` call
out pass criteria that are themselves misleading.
"""
from __future__ import annotations

import json

import pytest

from ms_agent.project.manager import ProjectManager
from ms_agent.tui.app import TuiApp

from tests.e2e.helpers import ModelRuntime, runtime_for, run_slash


def _assert_live_home(content: str, home) -> None:
    """Help shows the resolved path *and* that MS_AGENT_HOME produced it."""
    home = str(home)
    assert '~/.ms_agent' not in content, (
        f'help still says ~/.ms_agent while the live home is {home}')
    assert home in content, (
        f'help should show the live path {home} so a person can open the file')
    assert 'MS_AGENT_HOME' in content, (
        'help should say the path comes from MS_AGENT_HOME')


class TestHelpTextLiesAboutHome:
    """Slash help must not hardcode ``~/.ms_agent`` when MS_AGENT_HOME is set.

    Testers are told never to use ~/.ms_agent. Showing only the env var name
    also makes them expand it themselves — print the live path, then say
    which env produced it.
    """

    @pytest.mark.usability
    def test_search_help_mentions_effective_home(self, isolated_home):
        _assert_live_home(run_slash('/search').content, isolated_home)

    @pytest.mark.usability
    def test_instruction_help_mentions_effective_home(
            self, isolated_home, work_dir):
        _assert_live_home(
            run_slash('/instruction', runtime_for(work_dir)).content,
            isolated_home)

    @pytest.mark.usability
    def test_profile_help_mentions_effective_home(self, isolated_home):
        _assert_live_home(run_slash('/profile').content, isolated_home)

    @pytest.mark.usability
    def test_mcp_help_mentions_effective_home(self, isolated_home):
        _assert_live_home(run_slash('/mcp help').content, isolated_home)

    @pytest.mark.usability
    def test_skills_help_mentions_effective_home(self, isolated_home):
        _assert_live_home(run_slash('/skills help').content, isolated_home)

    @pytest.mark.usability
    def test_model_help_mentions_effective_home(
            self, isolated_home, work_dir):
        _assert_live_home(
            run_slash('/model help', ModelRuntime(work_dir)).content,
            isolated_home)


class TestBareCommandShape:
    """Bare ``/cmd`` is the current status, then the usage sheet.

    ``/cmd help`` is usage only. Action commands (/new, /quit, /stop,
    /compact) and dumps (/help, /config) stay as they are.
    """

    @pytest.mark.usability
    def test_bare_skills_is_status_then_usage(self, isolated_home):
        result = run_slash('/skills')
        assert result.content.strip().startswith('No skills.') or result.content.strip().startswith('Skills:')
        assert '/skills list' in result.content
        assert '/skills add' in result.content
        assert result.content.lower().index('usage:') > 0

    @pytest.mark.usability
    def test_bare_mcp_is_status_then_usage(self, isolated_home):
        result = run_slash('/mcp')
        assert result.content.strip().startswith('No MCP servers.') or result.content.startswith('MCP servers')
        assert '/mcp list' in result.content
        assert result.content.lower().index('usage:') > 0

    @pytest.mark.usability
    def test_skills_list_without_runtime_shows_imported_ids(
            self, isolated_home, tmp_path, work_dir):
        src = tmp_path / 'shown-skill'
        src.mkdir()
        (src / 'SKILL.md').write_text('# Shown\n', encoding='utf-8')
        rt = runtime_for(work_dir)
        run_slash(f'/skills add {src} global', rt)
        listed = run_slash('/skills list', rt)
        assert 'shown-skill' in listed.content
        assert 'Sources:' not in listed.content


class TestDefaultScopeFootgun:
    """``/mcp add`` omits to this folder (project) and says so.

    WebUI Settings → MCP is the global page, so the success line must
    mention that. ``/skills add`` and ``/skills enable`` share one default:
    project when a work dir is open, otherwise global.
    """

    @pytest.mark.usability
    def test_mcp_add_without_scope_is_project_not_global(
            self, isolated_home, work_dir, webui):
        TuiApp._open_project(str(work_dir))
        rt = runtime_for(work_dir)
        result = run_slash(
            '/mcp add docs url=https://example.invalid/mcp', rt)
        assert 'Added docs' in result.content
        assert '(project)' in result.content
        global_names = {m.name for m in webui.mcps.list_mcps('global')}
        assert 'docs' not in global_names
        project = ProjectManager(base_dir=str(isolated_home)).find_by_path(
            str(work_dir))
        project_names = {
            m.name
            for m in webui.mcps.list_mcps(f'project:{project.id}')
        }
        assert 'docs' in project_names

    @pytest.mark.usability
    def test_mcp_add_without_scope_warns_about_settings_page(
            self, isolated_home, work_dir):
        TuiApp._open_project(str(work_dir))
        result = run_slash(
            '/mcp add docs url=https://example.invalid/mcp',
            runtime_for(work_dir))
        lowered = result.content.lower()
        assert 'global' in lowered and (
            'settings' in lowered or 'not visible' in lowered
            or 'project scope' in lowered)

    @pytest.mark.usability
    def test_skills_add_and_enable_share_project_default_when_work_dir(
            self, isolated_home, work_dir):
        """Same command family, one default: this folder if TUI has --work-dir."""
        TuiApp._open_project(str(work_dir))
        rt = runtime_for(work_dir)
        src = work_dir / 'scoped-skill'
        src.mkdir()
        (src / 'SKILL.md').write_text('# scoped\n', encoding='utf-8')
        added = run_slash(f'/skills add {src}', rt)
        assert 'Imported' in added.content
        assert '(project)' in added.content
        assert (work_dir / '.ms_agent' / 'skills' / 'scoped-skill').is_dir()
        assert not (isolated_home / 'skills' / 'scoped-skill').exists()
        disabled = run_slash('/skills disable scoped-skill', rt)
        assert 'disable scoped-skill (project)' in disabled.content


class TestModelSwitchShadowsWebuiDefault:
    """e2e.md A5 / 0.5 tell testers to delete ``<work>/.ms_agent/config.yaml``
    before checking that TUI follows the WebUI default. That file is created
    by the documented way to switch models (B2 ``/model <id>``).

    The pass criterion is therefore self-defeating: exercising B2 makes A5
    fail on the same work dir. Users who switch once in TUI can never pick
    up a later WebUI default for that folder.
    """

    @pytest.mark.usability
    def test_later_webui_default_wins_over_old_tui_switch(
            self, isolated_home, work_dir, stub_llm_rebuild, webui):
        rt = ModelRuntime(work_dir)
        TuiApp._open_project(str(work_dir))
        run_slash(
            '/model provider add acme key=sk-acme '
            'url=https://example.invalid/v1 protocol=openai',
            rt)
        run_slash('/model catalog add acme pinned-in-tui', rt)
        switched = run_slash('/model acme/pinned-in-tui', rt)
        assert 'pinned-in-tui' in switched.content
        patch = work_dir / '.ms_agent' / 'config.yaml'
        assert not patch.is_file()

        from app.backends.ms_agent import model_link
        model_link.set_active_model('openai', 'qwen3.7-plus')
        cfg = TuiApp._load_runtime_config(
            'unused.yaml', str(work_dir), explicit_config=False)
        cfg = TuiApp._prepare_config(cfg, None, str(work_dir))
        assert cfg.llm.model == 'qwen3.7-plus', (
            f'TUI still pinned to {cfg.llm.model} via {patch} after WebUI '
            'changed the default')
        assert cfg.llm.service == 'openai'

    @pytest.mark.usability
    def test_switch_does_not_write_a_project_patch(
            self, isolated_home, work_dir, stub_llm_rebuild):
        rt = ModelRuntime(work_dir)
        run_slash(
            '/model provider add acme key=sk-acme '
            'url=https://example.invalid/v1 protocol=openai',
            rt)
        run_slash('/model catalog add acme a-1', rt)
        result = run_slash('/model acme/a-1', rt)
        assert 'Saved as the default' in result.content
        assert 'project patch' not in result.content.lower()
        assert not (work_dir / '.ms_agent' / 'config.yaml').exists()


class TestBareShowsStatusThenUsage:
    """Bare ``/model`` / ``/search`` show the current value first, then usage."""

    @pytest.mark.usability
    def test_bare_model_is_status_then_usage(self, isolated_home,
                                                     work_dir,
                                                     stub_llm_rebuild):
        result = run_slash('/model', ModelRuntime(work_dir))
        text = result.content
        assert 'Provider:' in text or 'Model:' in text
        assert 'usage:' in text.lower()
        status_at = min(
            i for i in (text.find('Provider:'), text.find('Model:')) if i >= 0)
        assert status_at < text.lower().index('usage:')

    @pytest.mark.usability
    def test_bare_search_is_status_then_usage(self, isolated_home):
        result = run_slash('/search')
        text = result.content
        assert 'Engine:' in text
        assert 'usage:' in text.lower()
        assert text.index('Engine:') < text.lower().index('usage:')


class TestMemoryBackendSemantics:
    """``/memory global on`` does not touch the current project.
    ``/memory backend`` is the same: omit-scope writes only the global
    default. The current folder needs ``/memory project backend``.
    """

    @pytest.mark.usability
    def test_backend_without_scope_does_not_rewrite_existing_project(
            self, isolated_home, work_dir):
        TuiApp._open_project(str(work_dir))
        rt = runtime_for(work_dir)
        run_slash('/memory project backend file', rt)
        # Same command family, still in the project: omit-scope should only
        # change the global default for *new* folders, like `/memory global on`.
        result = run_slash('/memory backend vector', rt)
        assert 'this project is unchanged' in result.content
        project = ProjectManager(base_dir=str(isolated_home)).find_by_path(
            str(work_dir))
        data = json.loads((isolated_home / 'settings.json').read_text())
        assert data['personalization']['memory_backend'] == 'vector'
        assert project.memory_backend == 'file'

    @pytest.mark.usability
    def test_project_backend_updates_only_this_folder(
            self, isolated_home, work_dir):
        TuiApp._open_project(str(work_dir))
        rt = runtime_for(work_dir)
        run_slash('/memory backend file', rt)
        result = run_slash('/memory project backend vector', rt)
        assert 'Project memory backend → vector' in result.content
        project = ProjectManager(base_dir=str(isolated_home)).find_by_path(
            str(work_dir))
        data = json.loads((isolated_home / 'settings.json').read_text())
        assert data['personalization']['memory_backend'] == 'file'
        assert project.memory_backend == 'vector'


class TestWebuiPartialPut:
    """PUT /api/agent-settings uses a full AgentSettings model whose
    ``default_memory_enabled`` defaults to True. A partial PUT that only
    changes the default model would silently turn memory on.
    """

    @pytest.mark.usability
    def test_partial_agent_settings_put_does_not_enable_memory(
            self, isolated_home, webui_client):
        before = webui_client.get('/api/agent-settings').json()['data']
        assert before['default_memory_enabled'] is False
        # Only send a model field. A safe API must treat omitted booleans
        # as "leave unchanged", not "schema default".
        resp = webui_client.put('/api/agent-settings', json={})
        assert resp.status_code == 200
        after = resp.json()['data']
        assert after['default_memory_enabled'] is False


class TestWebuiKeyMaskLeaksShortSecrets:
    """TUI /model list shows key=set|missing. WebUI list must not leak a
    short key via first4****last4. Presence is ``set``; long keys may 4+4.
    """

    @pytest.mark.usability
    def test_webui_provider_mask_is_not_invertible(
            self, isolated_home, work_dir, stub_llm_rebuild, webui):
        secret = 'sk-test-acme'
        run_slash(
            f'/model provider add acme key={secret} '
            'url=https://example.invalid/v1 protocol=openai',
            ModelRuntime(work_dir))
        row = next(p for p in webui.providers.list_providers() if p.id == 'acme')
        masked = row.api_key_masked or ''
        assert secret not in masked
        assert masked in ('set', 'configured', '****', '') or masked == '••••'
        # A 4+4 mask of a 12-char key is one character away from the secret.
        assert not (masked.startswith(secret[:4]) and masked.endswith(secret[-4:]))


class TestResumeIndexVsMarker:
    """Session #0 is rendered as ➤ when it is current, so the usage line
    ``/resume <#|id>`` does not match what the user sees in the table.
    Index 0 must still work.
    """

    @pytest.mark.usability
    def test_resume_zero_still_selects_first_session(self, isolated_home,
                                                     work_dir):
        from ms_agent.project import SessionManager

        project = TuiApp._open_project(str(work_dir))
        sm = SessionManager(project)
        first = sm.create(name='alpha')
        second = sm.create(name='beta')
        app = TuiApp.__new__(TuiApp)
        app._sm = sm
        app.session = first
        listed = sm.list()  # newest first
        assert listed[0].id == second.id
        assert app._resume_target('0').id == listed[0].id
        assert app._resume_target('1').id == listed[1].id
        assert app._resume_target(first.id).id == first.id


class TestMissingKeyPrompt:
    def test_setup_text_tells_user_session_stays_open(self):
        from ms_agent.llm.credentials import missing_api_key_setup_text
        text = missing_api_key_setup_text(
            ValueError('No API key found for provider "openai"'))
        assert '/model provider key' in text
        assert '/quit' in text
        assert 'stays open' in text.lower() or 'session stays' in text.lower()


class TestDocZeroFiveIsUnreasonable:
    """Period 0.5 used to tell testers to move
    ``<work>/.ms_agent/config.yaml`` out of the way. That file is no longer
    written by ``/model``; a later WebUI default is what the next TUI launch
    uses (no --config).
    """

    @pytest.mark.usability
    def test_doc_should_not_require_deleting_the_file_the_product_writes(
            self, isolated_home, work_dir, stub_llm_rebuild):
        rt = ModelRuntime(work_dir)
        run_slash(
            '/model provider add acme key=sk-acme '
            'url=https://example.invalid/v1 protocol=openai',
            rt)
        run_slash('/model catalog add acme pinned', rt)
        run_slash('/model acme/pinned', rt)
        assert not (work_dir / '.ms_agent' / 'config.yaml').exists()
        cfg2 = TuiApp._load_runtime_config(
            'unused.yaml', str(work_dir), explicit_config=False)
        assert cfg2.llm.model == 'pinned'
