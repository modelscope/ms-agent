"""关闭/删除 MCP 后,活会话必须在下一轮重建。

webui 的 agent 不带 MCPRuntime,实时 enable/disable 对它是空转;此前"下次构建
生效"的承诺缺少触发器,活会话一直用冻结的工具表 —— 管理页关掉的服务照样应答。
"""
from app.backends.ms_agent.runtime import registry


class _Rt:

    def __init__(self):
        self.needs_rebuild = False
        self.agent = None


def test_toggle_marks_live_runtimes_for_rebuild(monkeypatch):
    rt_a, rt_b = _Rt(), _Rt()
    monkeypatch.setattr(registry, "_runtimes", {"s1": rt_a, "s2": rt_b},
                        raising=False)
    monkeypatch.setattr(registry, "_loop", None, raising=False)

    registry.toggle_mcp("some-server", False)

    assert rt_a.needs_rebuild and rt_b.needs_rebuild


def test_toggle_with_no_live_sessions_is_a_no_op(monkeypatch):
    monkeypatch.setattr(registry, "_runtimes", {}, raising=False)
    monkeypatch.setattr(registry, "_loop", None, raising=False)
    registry.toggle_mcp("some-server", True)  # must not raise


def test_mcp_fingerprint_tracks_config_file_edits(tmp_path, monkeypatch):
    """管理路由之外的改动(agent 自己 edit mcp.json、用户手改)也要触发下一轮
    重建 —— 指纹必须随文件内容变化。"""
    import json

    from app.backends.ms_agent import common
    from app.backends.ms_agent.runtime import _mcp_fingerprint

    home = tmp_path / "home"
    proj = tmp_path / "proj"
    (proj / ".ms_agent").mkdir(parents=True)
    home.mkdir()
    monkeypatch.setattr(common, "home", lambda: str(home))

    class _P:
        path = str(proj)

    before = _mcp_fingerprint(_P())
    (proj / ".ms_agent" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"s": {"command": "uvx", "args": ["x"]}}}))
    after = _mcp_fingerprint(_P())
    assert before and after and before != after


async def test_reconnect_is_scoped_and_never_cancels_active_turn(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from ms_agent.config import MCPConfigManager
    from app.backends.ms_agent import common
    from app.backends.ms_agent.runtime import RuntimeRegistry

    monkeypatch.setattr(common, 'home', lambda: str(tmp_path / 'home'))
    config = {'command': 'python3', 'args': []}
    gm = MCPConfigManager(global_root=common.home())
    gm.add('same', config, scope='global')
    runtimes = {}
    for pid in ('inherits', 'overrides', 'disabled', 'unrelated'):
        path = tmp_path / pid
        path.mkdir()
        mm = MCPConfigManager(global_root=common.home(), project_root=str(path))
        if pid == 'overrides':
            mm.add('same', {'command': 'local', 'args': []}, scope='project')
        if pid == 'disabled':
            mm.add('same', dict(config, enabled=False), scope='project')
        lock = asyncio.Lock()
        await lock.acquire()  # Simulate an active turn.
        runtimes[pid] = SimpleNamespace(project=SimpleNamespace(id=pid, path=str(path)),
            agent=SimpleNamespace(mcp_config={'mcpServers': {'same': config} if pid != 'unrelated' else {}}),
            needs_rebuild=False, turn_lock=lock)
    registry = RuntimeRegistry()
    registry._runtimes = runtimes
    assert await registry.reconnect_mcp('global', 'same') == 1
    assert runtimes['inherits'].needs_rebuild
    assert not any(runtimes[p].needs_rebuild for p in ('overrides', 'disabled', 'unrelated'))
    assert all(rt.turn_lock.locked() for rt in runtimes.values())
    assert await registry.reconnect_mcp('project:overrides', 'same') == 1
    assert runtimes['overrides'].needs_rebuild
