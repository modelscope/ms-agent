"""TUI /memory writes PersonalizationSettings + project flags like WebUI."""
import json
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf

from ms_agent.command.builtin import register_builtin_commands
from ms_agent.command.router import CommandRouter
from ms_agent.command.types import CommandContext
from ms_agent.personalization.memory_apply import apply_project_memory
from ms_agent.personalization.settings import PersonalizationSettings
from ms_agent.personalization.types import PersonalizationConfig
from ms_agent.project.manager import ProjectManager
from ms_agent.tui.app import TuiApp


def make_router():
    router = CommandRouter()
    register_builtin_commands(router)
    return router


def make_ctx(text, runtime=None):
    cmd, args = CommandRouter.parse_input(text)
    return CommandContext(
        raw_input=text,
        command_name=cmd,
        args=args,
        source='cli',
        runtime=runtime,
        extra={'router': make_router()},
    )


class MockRuntime:
    def __init__(self, work):
        self.config = OmegaConf.create({'output_dir': str(work)})
        self.memory_tools = []

    async def load_memory(self):
        self.memory_tools.append('loaded')


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    return home


class TestMemoryCommand:
    @pytest.mark.asyncio
    async def test_global_default_persists(self, isolate_home):
        result = await make_router().dispatch(make_ctx('/memory global on'))
        assert 'Global memory default → on' in result.content
        loaded = PersonalizationSettings().load()
        assert loaded.memory_enabled is True
        data = json.loads((isolate_home / 'settings.json').read_text())
        assert data['personalization']['memory_enabled'] is True

    @pytest.mark.asyncio
    async def test_project_toggle_writes_meta_and_config(
            self, tmp_path, isolate_home):
        work = tmp_path / 'repo'
        work.mkdir()
        ProjectManager(base_dir=str(isolate_home)).open_folder(str(work))
        runtime = MockRuntime(work)
        result = await make_router().dispatch(
            make_ctx('/memory on', runtime))
        assert 'Project memory → on' in result.content
        project = ProjectManager(base_dir=str(isolate_home)).find_by_path(
            str(work))
        assert project.memory_enabled is True
        node = OmegaConf.select(runtime.config, 'memory.unified_memory')
        assert node is not None
        assert node.storage.backend == 'file'
        assert runtime.memory_tools == ['loaded']

    @pytest.mark.asyncio
    async def test_project_toggle_sees_work_dir_on_agent_runtime(
            self, tmp_path, isolate_home):
        from types import SimpleNamespace
        work = tmp_path / 'repo'
        work.mkdir()
        ProjectManager(base_dir=str(isolate_home)).open_folder(str(work))
        runtime = SimpleNamespace(
            config=None,
            llm=SimpleNamespace(
                config=OmegaConf.create({'output_dir': str(work)})),
            memory_tools=[],
        )
        result = await make_router().dispatch(
            make_ctx('/memory on', runtime))
        assert 'Project memory → on' in result.content

    @pytest.mark.asyncio
    async def test_backend_without_scope_is_global_only(
            self, tmp_path, isolate_home):
        work = tmp_path / 'repo'
        work.mkdir()
        pm = ProjectManager(base_dir=str(isolate_home))
        project = pm.open_folder(str(work), memory_backend='file')
        runtime = MockRuntime(work)
        result = await make_router().dispatch(
            make_ctx('/memory backend vector', runtime))
        assert 'Global memory backend default → vector' in result.content
        assert 'this project is unchanged' in result.content
        loaded = PersonalizationSettings().load()
        assert loaded.memory_backend == 'vector'
        still = pm.get(project.id)
        assert still.memory_backend == 'file'

    @pytest.mark.asyncio
    async def test_project_backend_does_not_rewrite_global(
            self, tmp_path, isolate_home):
        work = tmp_path / 'repo'
        work.mkdir()
        pm = ProjectManager(base_dir=str(isolate_home))
        project = pm.open_folder(str(work), memory_backend='file')
        runtime = MockRuntime(work)
        result = await make_router().dispatch(
            make_ctx('/memory project backend vector', runtime))
        assert 'Project memory backend → vector' in result.content
        loaded = PersonalizationSettings().load()
        assert loaded.memory_backend != 'vector'
        updated = pm.get(project.id)
        assert updated.memory_backend == 'vector'

    @pytest.mark.asyncio
    async def test_global_backend_alias(self, isolate_home):
        result = await make_router().dispatch(
            make_ctx('/memory global backend file'))
        assert 'Global memory backend default → file' in result.content
        loaded = PersonalizationSettings().load()
        assert loaded.memory_backend == 'file'

    @pytest.mark.asyncio
    async def test_vector_does_not_silent_file_fallback(
            self, tmp_path, isolate_home):
        work = tmp_path / 'repo'
        work.mkdir()
        pm = ProjectManager(base_dir=str(isolate_home))
        project = pm.open_folder(str(work))
        pm.update(project.id, memory_enabled=True, memory_backend='vector')
        runtime = MockRuntime(work)
        result = await make_router().dispatch(
            make_ctx('/memory on', runtime))
        assert 'vector' in result.content.lower()
        assert OmegaConf.select(
            runtime.config, 'memory', default=None) is None


def test_apply_project_memory_file_node():
    cfg = OmegaConf.create({})
    project = SimpleNamespace(
        id='abc', memory_enabled=True, memory_backend='file')
    assert apply_project_memory(cfg, project) == 'file'
    assert cfg.memory.unified_memory.user_id == 'abc'


def test_open_folder_inherits_global_memory_default(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    PersonalizationSettings().save(
        PersonalizationConfig(memory_enabled=True, memory_backend='file'))
    work = tmp_path / 'fresh'
    work.mkdir()
    project = TuiApp._open_project(str(work))
    assert project.memory_enabled is True
    again = TuiApp._open_project(str(work))
    assert again.id == project.id


def test_prepare_config_injects_unified_memory(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    cfg = OmegaConf.create({})
    project = SimpleNamespace(
        id='p1', instruction='', memory_enabled=True, memory_backend='file')
    out = TuiApp._prepare_config(cfg, None, str(tmp_path / 'work'), project)
    assert out.memory.unified_memory.storage.backend == 'file'
