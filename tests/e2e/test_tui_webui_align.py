"""TUI / WebUI settings-ledger e2e (docs/tui-webui-align-e2e.md).

Alignment means both surfaces read and write the same files under one
``MS_AGENT_HOME``, not identical UIs. Disk is the source of truth; WebUI
adapters / HTTP are the other reader.

These tests drive the same slash router the TUI uses, then assert the ledger
and (when present) the GitLab WebUI backend.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from ms_agent.config.config import Config
from ms_agent.project import SessionManager
from ms_agent.tui.app import TuiApp

from tests.e2e.helpers import ModelRuntime, runtime_for, run_slash


def _settings(home: Path) -> dict:
    path = home / 'settings.json'
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


# ---------------------------------------------------------------------------
# A / period 0 — same folder, same project, same sessions
# ---------------------------------------------------------------------------


class TestProjectAndSession:
    def test_a1_same_folder_is_one_project(self, isolated_home, work_dir,
                                           webui):
        from ms_agent.project.manager import ProjectManager

        created = webui.projects.create_project(
            __import__(
                'app.schemas.project', fromlist=['ProjectCreate']
            ).ProjectCreate(name='from-webui', local_path=str(work_dir)))
        tui = TuiApp._open_project(str(work_dir))
        assert tui.id == created.id
        listed = ProjectManager(base_dir=str(isolated_home)).get(tui.id)
        assert listed is not None
        assert Path(listed.path).resolve() == work_dir.resolve()

    def test_a2_webui_session_is_resumable_in_tui(self, isolated_home,
                                                  work_dir, webui):
        from app.schemas.project import ProjectCreate
        from app.schemas.session import SessionCreate

        project = webui.projects.create_project(
            ProjectCreate(name='shared', local_path=str(work_dir)))
        session = webui.sessions.create_session(
            SessionCreate(title='web chat', project_id=project.id))
        sdk = SessionManager(TuiApp._open_project(str(work_dir)))
        sdk.get_session_log(sdk.get(session.id)).append(
            {'role': 'user', 'content': 'hello from web'})

        tui_proj = TuiApp._open_project(str(work_dir))
        tui_sm = SessionManager(tui_proj)
        assert session.id in {s.id for s in tui_sm.list()}
        msgs = tui_sm.get_session_log(tui_sm.get(session.id)).get_all_messages()
        assert any(m.get('content') == 'hello from web' for m in msgs)

        app = TuiApp.__new__(TuiApp)
        app._sm = tui_sm
        app.session = None
        found = app._resume_target(session.id)
        assert found is not None and found.id == session.id
        by_index = app._resume_target('0')
        assert by_index is not None and by_index.id == session.id

    def test_a3_tui_session_shows_up_in_webui(self, isolated_home, work_dir,
                                              webui):
        from app.schemas.project import ProjectCreate

        tui_proj = TuiApp._open_project(str(work_dir))
        sess = SessionManager(tui_proj).create(name='from tui')
        SessionManager(tui_proj).get_session_log(sess).append(
            {'role': 'user', 'content': 'hello from tui first'})

        projects = webui.projects.list_projects()
        assert any(p.id == tui_proj.id for p in projects)
        # Opening the same folder through WebUI must not mint a second id.
        again = webui.projects.create_project(
            ProjectCreate(name='reopen', local_path=str(work_dir)))
        assert again.id == tui_proj.id
        ids = [s.id for s in webui.sessions.list_sessions(tui_proj.id)]
        assert sess.id in ids

    def test_a4_empty_home_does_not_mcp_todo_list(self, isolated_home,
                                                  work_dir):
        cfg = TuiApp._load_runtime_config(
            'unused.yaml', str(work_dir), explicit_config=False)
        cfg = TuiApp._prepare_config(cfg, None, str(work_dir))
        TuiApp._bind_todo_list_session(cfg, str(work_dir / 'sess'))
        assert cfg.tools.todo_list.mcp is False
        servers = Config.convert_mcp_servers_to_json(cfg)['mcpServers']
        assert 'todo_list' not in servers

    def test_a5_default_tui_uses_webui_default_model(self, isolated_home,
                                                     work_dir, webui):
        from app.backends.ms_agent import model_link

        model_link.set_active_model('openai', 'qwen3.7-plus')
        data = _settings(isolated_home)
        assert data.get('default_model') == 'openai/qwen3.7-plus'
        cfg = TuiApp._load_runtime_config(
            'unused.yaml', str(work_dir), explicit_config=False)
        cfg = TuiApp._prepare_config(cfg, None, str(work_dir))
        assert cfg.llm.service == 'openai'
        assert cfg.llm.model == 'qwen3.7-plus'

    def test_a6_explicit_config_not_overridden_by_settings(
            self, isolated_home, work_dir, tmp_path):
        (isolated_home / 'settings.json').write_text(
            json.dumps({
                'default_model': 'openai/qwen3.7-plus',
                'llm': {
                    'provider': 'openai',
                    'model': 'qwen3.7-plus',
                },
            }),
            encoding='utf-8')
        yaml_path = tmp_path / 'custom.yaml'
        yaml_path.write_text(
            'llm:\n  service: modelscope\n  model: from-yaml\n'
            'tools:\n  file_system:\n    mcp: false\n',
            encoding='utf-8')
        cfg = TuiApp._load_runtime_config(
            str(yaml_path), str(work_dir), explicit_config=True)
        assert cfg.llm.model == 'from-yaml'
        assert cfg.llm.service == 'modelscope'

    @pytest.mark.live
    def test_a5_live_first_turn_uses_seeded_model(self, isolated_home,
                                                  work_dir):
        key = os.environ.get('DASHSCOPE_API_KEY', '').strip()
        if not key:
            pytest.skip('DASHSCOPE_API_KEY missing')
        (isolated_home / 'settings.json').write_text(
            json.dumps({
                'default_model': 'dashscope/qwen3.7-plus',
                'llm': {
                    'provider': 'dashscope',
                    'model': 'qwen3.7-plus',
                },
                'providers': {
                    'dashscope': {
                        'api_key': key,
                        'protocol': 'openai',
                    },
                },
            }),
            encoding='utf-8')
        cfg = TuiApp._load_runtime_config(
            'unused.yaml', str(work_dir), explicit_config=False)
        cfg = TuiApp._prepare_config(cfg, None, str(work_dir))
        assert cfg.llm.model == 'qwen3.7-plus'
        assert cfg.llm.service == 'dashscope'
        OmegaConf.update(cfg, 'generation_config.stream', False, merge=True)
        OmegaConf.update(cfg, 'generation_config.max_tokens', 32, merge=True)
        from ms_agent.llm import LLM
        from ms_agent.llm.utils import Message

        llm = LLM.from_config(cfg)
        assert getattr(llm, 'model', '') in ('qwen3.7-plus', cfg.llm.model)
        reply = llm.generate(
            messages=[
                Message(role='user', content='Reply with exactly: pong'),
            ],
            tools=None)
        if hasattr(reply, '__iter__') and not hasattr(reply, 'content'):
            chunk = None
            for chunk in reply:
                pass
            reply = chunk
        assert reply is not None and reply.content
        assert 'sk-' not in (reply.content or '')


# ---------------------------------------------------------------------------
# B / period 3 — model providers
# ---------------------------------------------------------------------------


class TestModelLedger:
    def test_b1_list_hides_plaintext_key(self, isolated_home, work_dir,
                                               stub_llm_rebuild):
        rt = ModelRuntime(work_dir)
        run_slash(
            '/model provider add acme key=sk-secret-plaintext '
            'url=https://example.invalid/v1 protocol=openai',
            rt)
        listed = run_slash('/model list', rt)
        assert 'acme' in listed.content
        assert 'sk-secret-plaintext' not in listed.content
        assert 'key=set' in listed.content
        settings = _settings(isolated_home)
        assert settings['providers']['acme']['api_key'] == 'sk-secret-plaintext'

    def test_b2_switch_updates_default_model(self, isolated_home,
                                                   work_dir,
                                                   stub_llm_rebuild):
        rt = ModelRuntime(work_dir)
        run_slash(
            '/model provider add acme key=sk-acme '
            'url=https://example.invalid/v1 protocol=openai',
            rt)
        run_slash('/model catalog add acme a-1', rt)
        result = run_slash('/model acme/a-1', rt)
        assert 'a-1' in result.content
        data = _settings(isolated_home)
        assert data.get('default_model') == 'acme/a-1'
        shown = run_slash('/model', rt)
        assert 'a-1' in shown.content

    def test_b3_b7_provider_and_catalog_visible_to_webui(
            self, isolated_home, work_dir, stub_llm_rebuild, webui):
        rt = ModelRuntime(work_dir)
        run_slash(
            '/model provider add acme key=sk-test-acme '
            'url=https://example.invalid/v1 protocol=openai',
            rt)
        run_slash('/model catalog add acme a-1', rt)
        rows = {p.id: p for p in webui.providers.list_providers()}
        assert 'acme' in rows
        assert rows['acme'].base_url == 'https://example.invalid/v1'
        assert 'sk-test-acme' not in (rows['acme'].api_key_masked or '')
        data = _settings(isolated_home)
        assert data['providers']['acme']['models'] == ['a-1']

    def test_b4_key_update_and_b6_patch_preserves_other_fields(
            self, isolated_home, work_dir, stub_llm_rebuild):
        rt = ModelRuntime(work_dir)
        run_slash(
            '/model provider add acme key=sk-old '
            'url=https://example.invalid/v1 protocol=openai name=Acme',
            rt)
        run_slash('/model provider key acme sk-new', rt)
        run_slash('/model provider set acme protocol=anthropic', rt)
        entry = _settings(isolated_home)['providers']['acme']
        assert entry['api_key'] == 'sk-new'
        assert entry['base_url'] == 'https://example.invalid/v1'
        assert entry['protocol'] == 'anthropic'
        assert entry.get('name') == 'Acme'

    def test_b8_cannot_delete_builtin_openai(self, isolated_home,
                                                   work_dir,
                                                   stub_llm_rebuild):
        rt = ModelRuntime(work_dir)
        result = run_slash('/model provider remove openai', rt)
        assert 'Cannot remove' in result.content
        listed = run_slash('/model list', rt)
        assert 'openai' in listed.content
        run_slash('/model provider key openai sk-override', rt)
        cleared = run_slash('/model provider remove openai', rt)
        assert 'Builtin catalog remains' in cleared.content
        listed = run_slash('/model list', rt)
        assert 'openai' in listed.content
        assert 'sk-override' not in listed.content


# ---------------------------------------------------------------------------
# C / period 1 — search
# ---------------------------------------------------------------------------


class TestSearchLedger:
    def test_c1_default_engine_tavily(self, isolated_home):
        status = run_slash('/search')
        assert 'Engine: tavily' in status.content
        listed = run_slash('/search list')
        assert '* tavily' in listed.content

    def test_c2_c4_engine_switch_keeps_other_keys(self, isolated_home,
                                                        webui):
        run_slash('/search engine exa')
        run_slash('/search key sk-test-exa')
        run_slash('/search engine tavily')
        block = _settings(isolated_home)['tools']['web_search']
        assert block['engine'] == 'tavily'
        assert block['exa_api_key'] == 'sk-test-exa'
        ui = webui.search.get_settings()
        assert ui.provider == 'tavily'

        from app.schemas.search import SearchSettingsUpdate
        webui.search.update_settings(
            SearchSettingsUpdate(enabled=True, provider='exa'))
        status = run_slash('/search')
        assert 'Engine: exa' in status.content
        listed = run_slash('/search list')
        assert '* exa' in listed.content
        assert 'key=set' in listed.content

    def test_c3_arxiv_rejects_key(self, isolated_home, webui):
        run_slash('/search engine arxiv')
        result = run_slash('/search key nope')
        assert 'does not use an API key' in result.content
        block = _settings(isolated_home)['tools']['web_search']
        assert 'arxiv_api_key' not in block
        providers = {p.id: p for p in webui.search.list_providers()}
        assert providers['arxiv'].requires_key is False
        ui = webui.search.get_settings()
        assert ui.provider == 'arxiv'

    def test_c5_enable_disable(self, isolated_home, webui):
        run_slash('/search disable')
        assert _settings(isolated_home)['tools']['web_search']['enabled'] is False
        assert webui.search.get_settings().enabled is False
        run_slash('/search enable')
        assert webui.search.get_settings().enabled is True

    def test_c6_webui_to_tui_engine(self, isolated_home, webui):
        from app.schemas.search import SearchSettingsUpdate
        webui.search.update_settings(
            SearchSettingsUpdate(enabled=True, provider='serpapi'))
        status = run_slash('/search')
        assert 'Engine: serpapi' in status.content
        listed = run_slash('/search list')
        assert '* serpapi' in listed.content


# ---------------------------------------------------------------------------
# D / period 2 — instructions + profile
# ---------------------------------------------------------------------------


class TestInstructionAndProfile:
    def test_d1_d2_global_instruction_shared(self, isolated_home, webui):
        result = run_slash('/instruction global Always answer in French.')
        assert 'saved' in result.content.lower()
        text = (isolated_home / 'AGENTS.md').read_text(encoding='utf-8')
        assert 'Always answer in French.' in text
        assert text.lstrip().startswith('---')
        from app.schemas.instruction import InstructionUpsert
        ui = webui.instructions.get_instruction('global')
        assert 'Always answer in French.' in ui.content
        webui.instructions.upsert_instruction(
            'global', InstructionUpsert(content='Be terse.'))
        shown = run_slash('/instruction global')
        assert 'Be terse.' in shown.content

    def test_d3_project_instruction_never_writes_repo_root(
            self, isolated_home, work_dir, webui):
        root = work_dir / 'AGENTS.md'
        root.write_text('# team\nkeep me at root\n', encoding='utf-8')
        rt = runtime_for(work_dir)
        TuiApp._open_project(str(work_dir))
        run_slash('/instruction project This project uses FastAPI.', rt)
        private = work_dir / '.ms_agent' / 'AGENTS.md'
        assert private.read_text(encoding='utf-8').strip() == (
            'This project uses FastAPI.')
        assert root.read_text(encoding='utf-8') == '# team\nkeep me at root\n'
        shown = run_slash('/instruction', rt)
        assert 'FastAPI' in shown.content
        assert 'never writes' in shown.content.lower() or 'Repo-root' in shown.content

    def test_d4_d6_profile_fields_independent(self, isolated_home, webui):
        run_slash('/profile callme Alice')
        run_slash('/profile about I work on agents.')
        shown = run_slash('/profile')
        assert 'Alice' in shown.content
        assert 'I work on agents.' in shown.content
        ui = webui.profile.get_profile()
        assert ui.agent_calls_user == 'Alice'
        assert 'I work on agents.' in (ui.description or '')
        run_slash('/profile callme clear')
        call_text = (isolated_home / 'PROFILE.md').read_text(encoding='utf-8')
        assert 'Alice' not in call_text
        assert 'I work on agents.' in call_text
        ui = webui.profile.get_profile()
        assert not ui.agent_calls_user
        assert 'I work on agents.' in (ui.description or '')


# ---------------------------------------------------------------------------
# E / period 4 — MCP
# ---------------------------------------------------------------------------


class TestMcpLedger:
    def test_e1_e6_http_crud_matches_webui(self, isolated_home, webui):
        rt = runtime_for(Path('.'))
        added = run_slash(
            '/mcp add docs global url=https://example.invalid/mcp', rt)
        assert 'Added docs' in added.content
        listed = run_slash('/mcp list global', rt)
        assert 'docs' in listed.content
        assert 'https://example.invalid/mcp' in listed.content
        ui = {m.name: m for m in webui.mcps.list_mcps('global')}
        assert ui['docs'].endpoint == 'https://example.invalid/mcp'

        updated = run_slash(
            '/mcp update docs global url=https://example.invalid/v2', rt)
        assert 'Updated docs' in updated.content
        mcp_json = json.loads(
            (isolated_home / 'mcp.json').read_text(encoding='utf-8'))
        servers = mcp_json.get('mcpServers') or mcp_json
        assert servers['docs']['url'] == 'https://example.invalid/v2'
        ui = {m.name: m for m in webui.mcps.list_mcps('global')}
        assert ui['docs'].endpoint == 'https://example.invalid/v2'
        assert len(ui) == 1

        run_slash('/mcp disable docs global', rt)
        listed = run_slash('/mcp list global', rt)
        assert '[off] docs' in listed.content
        run_slash('/mcp remove docs global', rt)
        ui = {m.name: m for m in webui.mcps.list_mcps('global')}
        assert 'docs' not in ui

    def test_e3_stdio_splits_command_args(self, isolated_home):
        rt = runtime_for(Path('.'))
        run_slash(
            '/mcp add fetch global command="npx -y @mcp/server-fetch"', rt)
        mcp_json = json.loads(
            (isolated_home / 'mcp.json').read_text(encoding='utf-8'))
        servers = mcp_json.get('mcpServers') or mcp_json
        assert servers['fetch']['command'] == 'npx'
        assert servers['fetch']['args'] == ['-y', '@mcp/server-fetch']


# ---------------------------------------------------------------------------
# F / period 4 — skills
# ---------------------------------------------------------------------------


class TestSkillsLedger:
    def test_f1_f4_import_remove_keeps_source(self, isolated_home,
                                                    tmp_path, webui):
        src = tmp_path / 'demo-skill'
        src.mkdir()
        (src / 'SKILL.md').write_text(
            '---\nname: demo-skill\n---\n# Demo\n', encoding='utf-8')
        rt = runtime_for(tmp_path / 'work')
        (tmp_path / 'work').mkdir()
        added = run_slash(f'/skills add {src} global', rt)
        assert 'Imported' in added.content
        dest = isolated_home / 'skills' / 'demo-skill' / 'SKILL.md'
        assert dest.is_file()
        assert (src / 'SKILL.md').is_file()
        ui_names = {s.name for s in webui.skills.list_skills('global')}
        assert 'demo-skill' in ui_names
        removed = run_slash('/skills remove demo-skill global', rt)
        assert 'Removed managed skill' in removed.content
        assert not dest.parent.exists()
        assert (src / 'SKILL.md').is_file()

    def test_f5_remove_auto_discovered_refuses_rmtree(
            self, isolated_home, tmp_path, work_dir):
        discovered = work_dir / '.agents' / 'skills' / 'local-skill'
        discovered.mkdir(parents=True)
        (discovered / 'SKILL.md').write_text('# local\n', encoding='utf-8')
        rt = runtime_for(work_dir)
        result = run_slash('/skills remove local-skill global', rt)
        assert 'not a managed skill' in result.content.lower()
        assert (discovered / 'SKILL.md').is_file()


# ---------------------------------------------------------------------------
# G / period 5 — memory
# ---------------------------------------------------------------------------


class TestMemoryLedger:
    def test_g1_g3_global_default_inherits_on_new_folder(
            self, isolated_home, tmp_path, work_dir):
        status = run_slash('/memory')
        assert 'Global default:' in status.content
        assert 'Project:' in status.content
        run_slash('/memory global on')
        data = _settings(isolated_home)
        assert data['personalization']['memory_enabled'] is True
        existing = TuiApp._open_project(str(work_dir))
        run_slash('/memory global off')
        # Already-registered project must not flip with the global default.
        from ms_agent.project.manager import ProjectManager
        still = ProjectManager(base_dir=str(isolated_home)).get(existing.id)
        assert still.memory_enabled == existing.memory_enabled
        run_slash('/memory global on')
        fresh = tmp_path / 'brand-new'
        fresh.mkdir()
        inherited = TuiApp._open_project(str(fresh))
        assert inherited.memory_enabled is True

    def test_g2_g4_project_toggle_webui_and_config(
            self, isolated_home, work_dir, webui):
        TuiApp._open_project(str(work_dir))
        rt = runtime_for(work_dir)
        result = run_slash('/memory on', rt)
        assert 'Project memory → on' in result.content
        from ms_agent.project.manager import ProjectManager
        project = ProjectManager(base_dir=str(isolated_home)).find_by_path(
            str(work_dir))
        assert project.memory_enabled is True
        node = OmegaConf.select(rt.config, 'memory.unified_memory')
        assert node is not None
        ui = webui.projects.get_project(project.id)
        assert ui.memory_enabled is True

    def test_g5_vector_does_not_silent_file_fallback(
            self, isolated_home, work_dir):
        from ms_agent.project.manager import ProjectManager
        TuiApp._open_project(str(work_dir))
        rt = runtime_for(work_dir)
        run_slash('/memory backend vector', rt)
        data = _settings(isolated_home)
        assert data['personalization']['memory_backend'] == 'vector'
        pm = ProjectManager(base_dir=str(isolated_home))
        project = pm.find_by_path(str(work_dir))
        assert project.memory_backend != 'vector'
        run_slash('/memory project backend vector', rt)
        project = pm.find_by_path(str(work_dir))
        assert project.memory_backend == 'vector'
        run_slash('/memory on', rt)
        assert OmegaConf.select(rt.config, 'memory', default=None) is None
        memory_md = work_dir / '.ms_agent' / 'memory' / 'MEMORY.md'
        assert not memory_md.exists()

    def test_g6_webui_enables_project_memory_for_tui(
            self, isolated_home, work_dir, webui):
        from app.schemas.project import ProjectCreate, ProjectUpdate
        created = webui.projects.create_project(
            ProjectCreate(
                name='mem',
                local_path=str(work_dir),
                memory_enabled=True,
                memory_backend='file',
            ))
        webui.projects.update_project(
            created.id, ProjectUpdate(memory_enabled=True))
        tui = TuiApp._open_project(str(work_dir))
        assert tui.id == created.id
        assert tui.memory_enabled is True
        status = run_slash('/memory', runtime_for(work_dir))
        assert 'Project: on' in status.content

    def test_g7_disable_after_load_asks_for_new(self, isolated_home,
                                                      work_dir):
        TuiApp._open_project(str(work_dir))
        rt = runtime_for(work_dir)
        rt.memory_tools = ['already-loaded']
        result = run_slash('/memory off', rt)
        assert '/new' in result.content


class TestHttpEnvelope:
    def test_tui_mcp_is_visible_over_webui_http(self, isolated_home,
                                                      webui_client):
        run_slash(
            '/mcp add docs global url=https://example.invalid/mcp',
            runtime_for(Path('.')))
        resp = webui_client.get('/api/mcps', params={'scope': 'global'})
        assert resp.status_code == 200
        body = resp.json()
        assert body['code'] == 0
        names = [row['name'] for row in body['data']]
        assert 'docs' in names
        docs = next(row for row in body['data'] if row['name'] == 'docs')
        assert docs['endpoint'] == 'https://example.invalid/mcp'
        dumped = json.dumps(body)
        assert 'sk-' not in dumped
