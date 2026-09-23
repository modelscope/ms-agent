"""TUI binds a work dir through ProjectManager.open_folder (same as WebUI)."""
import os
from pathlib import Path
from types import SimpleNamespace

from omegaconf import OmegaConf

from ms_agent.personalization.settings import PersonalizationSettings
from ms_agent.personalization.types import PersonalizationConfig
from ms_agent.project import SessionManager
from ms_agent.project.manager import ProjectManager
from ms_agent.project.paths import project_key
from ms_agent.tui.app import TuiApp
from ms_agent.tui.state import TuiState


def test_tui_open_project_registers_path_key(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    work = tmp_path / 'repo'
    work.mkdir()

    project = TuiApp._open_project(str(work))
    assert project.id == project_key(str(work))
    assert project.path == str(work.resolve())
    listed = ProjectManager(base_dir=str(home)).get(project.id)
    assert listed is not None
    assert listed.path == project.path


def test_tui_open_project_reuses_webui_create_id(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    work = tmp_path / 'from-webui'
    work.mkdir()
    created = ProjectManager(base_dir=str(home)).create(
        name='WebUI project', path=str(work), init_workspace=False)

    project = TuiApp._open_project(str(work))
    assert project.id == created.id
    assert project.id != project_key(str(work))
    assert Path(project.path).resolve() == work.resolve()


def test_tui_and_webui_share_session_tree(tmp_path, monkeypatch):
    """Same folder, one project id: WebUI sessions show up in TUI /sessions."""
    home = tmp_path / 'home'
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    work = tmp_path / 'shared'
    work.mkdir()
    created = ProjectManager(base_dir=str(home)).create(
        name='WebUI', path=str(work), init_workspace=False)
    web_sm = SessionManager(created)
    web_sess = web_sm.create(name='from webui')
    web_sm.get_session_log(web_sess).append(
        {'role': 'user', 'content': 'hello from web'})

    tui_proj = TuiApp._open_project(str(work))
    tui_sm = SessionManager(tui_proj)
    assert tui_proj.id == created.id
    assert web_sess.id in {s.id for s in tui_sm.list()}
    msgs = tui_sm.get_session_log(web_sess).get_all_messages()
    assert any(m.get('content') == 'hello from web' for m in msgs)

    tui_sess = tui_sm.create(name='from tui')
    tui_sm.get_session_log(tui_sess).append(
        {'role': 'user', 'content': 'hello from tui'})
    listed_again = SessionManager(created).list()
    assert tui_sess.id in {s.id for s in listed_again}


def test_prepare_config_merges_personalization(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    PersonalizationSettings().save(
        PersonalizationConfig(global_instruction='Be brief.'))
    cfg = OmegaConf.create({})
    project = SimpleNamespace(instruction='Use FastAPI.')
    out = TuiApp._prepare_config(cfg, None, str(tmp_path / 'work'), project)
    assert out.personalization.project_instruction == 'Use FastAPI.'
    assert out.personalization.global_instruction == 'Be brief.'


def test_apply_session_binds_plan_to_session_dir(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    work = tmp_path / 'repo'
    work.mkdir()
    app = TuiApp.__new__(TuiApp)
    app._project = TuiApp._open_project(str(work))
    app._sm = SessionManager(app._project)
    session = app._sm.create(name='chat')
    app.agent = SimpleNamespace(
        config=OmegaConf.create({}),
        load_cache=False,
    )
    app.state = TuiState(model='m', perm='auto', work_dir=str(work))
    app._apply_session(session, resume=False)
    sess_dir = str(app._sm.sessions_dir / session.id)
    plan_json = os.path.join(sess_dir, 'plan.json')
    plan_md = os.path.join(sess_dir, 'plan.md')
    assert app.agent.config.tools.todo_list.plan_filename == plan_json
    assert app.agent.config.tools.todo_list.plan_md_filename == plan_md
    assert app.agent.config.tools.todo_list.mcp is False
    assert app.agent.config.session_log.dir == sess_dir
    from ms_agent.config.config import Config
    servers = Config.convert_mcp_servers_to_json(
        app.agent.config)['mcpServers']
    assert 'todo_list' not in servers


def test_prune_empty_only_drops_owned_sessions(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    work = tmp_path / 'repo'
    work.mkdir()
    app = TuiApp.__new__(TuiApp)
    app._project = TuiApp._open_project(str(work))
    app._sm = SessionManager(app._project)
    app._owned_session_ids = set()
    web = app._sm.create(name='from webui')
    owned = app._sm.create(name='tui leftover')
    app._owned_session_ids.add(owned.id)
    app._prune_if_empty(web)
    app._prune_if_empty(owned)
    ids = {s.id for s in app._sm.list()}
    assert web.id in ids
    assert owned.id not in ids
