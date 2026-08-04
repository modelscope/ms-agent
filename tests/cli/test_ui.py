import signal
import subprocess
from argparse import ArgumentParser
from types import SimpleNamespace

import pytest

from ms_agent.cli import ui


def _parse_ui_args(*extra_args):
    parser = ArgumentParser()
    subparsers = parser.add_subparsers()
    ui.UICMD.define_args(subparsers)
    return parser.parse_args(['ui'] + list(extra_args))


def test_ui_parser_defaults_are_local_and_non_production():
    args = _parse_ui_args()

    assert args.host == '127.0.0.1'
    assert args.port == 7860
    assert args.backend_port == 8000
    assert args.reload is False
    assert args.mock is False
    assert args.skip_install is False
    assert args.production is False
    assert args.no_browser is False


@pytest.mark.parametrize('value', ['0', '-1', '65536', 'not-a-port'])
def test_ui_parser_rejects_invalid_ports(value):
    with pytest.raises(SystemExit):
        _parse_ui_args('--port', value)


@pytest.mark.parametrize(
    ('host', 'port', 'expected'),
    [
        ('127.0.0.1', 7860, 'http://127.0.0.1:7860'),
        ('0.0.0.0', 9000, 'http://127.0.0.1:9000'),
        ('::', 7860, 'http://[::1]:7860'),
        ('[::]', 7860, 'http://[::1]:7860'),
        ('::1', 7860, 'http://[::1]:7860'),
        ('2001:db8::1', 8080, 'http://[2001:db8::1]:8080'),
        (' localhost ', 7000, 'http://localhost:7000'),
    ],
)
def test_public_url_is_browser_safe(host, port, expected):
    assert ui._public_url(host, port) == expected


@pytest.mark.parametrize(
    ('host', 'expected'),
    [
        ('127.0.0.1', True),
        ('LOCALHOST', True),
        ('[::1]', True),
        ('0.0.0.0', False),
        ('192.168.1.20', False),
    ],
)
def test_loopback_host_detection(host, expected):
    assert ui._is_loopback_host(host) is expected


@pytest.mark.parametrize(
    ('host', 'expected'),
    [('[::1]', '::1'), ('[::]', '::'), (' localhost ', 'localhost')],
)
def test_bind_host_removes_url_only_ipv6_brackets(host, expected):
    assert ui._bind_host(host) == expected


def test_read_semantic_version_accepts_node_prefix(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout='v22.22.0\n')

    monkeypatch.setattr(ui.subprocess, 'run', fake_run)

    assert ui._read_semantic_version('/tools/node', '--version',
                                     'Node.js') == (22, 22, 0)
    assert calls == [
        (
            ['/tools/node', '--version'],
            {
                'capture_output': True,
                'check': True,
                'text': True,
                'encoding': 'utf-8',
                'errors': 'replace',
                'timeout': 10,
            },
        )
    ]


def test_read_semantic_version_rejects_unparseable_output(monkeypatch):
    monkeypatch.setattr(
        ui.subprocess,
        'run',
        lambda *args, **kwargs: SimpleNamespace(stdout='not-a-version\n'),
    )

    with pytest.raises(ui.UIError, match='Could not parse the pnpm version'):
        ui._read_semantic_version('pnpm', '--version', 'pnpm')


def test_windows_command_script_uses_native_shell_for_version(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout='10.17.1\n')

    monkeypatch.setattr(ui, 'IS_WINDOWS', True)
    monkeypatch.setattr(ui.subprocess, 'run', fake_run)

    assert ui._read_semantic_version(
        r'C:\Program Files\nodejs\pnpm.cmd', '--version', 'pnpm') == (
            10, 17, 1)
    assert calls[0][1]['shell'] is True


def test_windows_command_script_uses_native_shell_for_setup(
    monkeypatch,
    tmp_path,
):
    calls = []
    monkeypatch.setattr(ui, 'IS_WINDOWS', True)

    class FinishedProcess:

        @staticmethod
        def wait():
            return 0

    monkeypatch.setattr(
        ui,
        '_spawn',
        lambda command, **kwargs: calls.append((command, kwargs))
        or FinishedProcess(),
    )

    ui._run_setup(
        [r'C:\Program Files\nodejs\pnpm.cmd', 'install'],
        cwd=tmp_path,
        label='frontend setup',
    )

    assert calls == [
        (
                [r'C:\Program Files\nodejs\pnpm.cmd', 'install'],
                {
                    'cwd': tmp_path,
                'env': None,
                'shell': True,
            },
        )
    ]


@pytest.mark.parametrize(
    ('wait_result', 'raised'),
    [('interrupt', KeyboardInterrupt), (7, ui.UIError)],
)
def test_setup_failure_cleans_its_process_tree(
    monkeypatch,
    tmp_path,
    wait_result,
    raised,
):
    process = SimpleNamespace(pid=1234)

    def wait():
        if wait_result == 'interrupt':
            raise KeyboardInterrupt
        return wait_result

    process.wait = wait
    cleanup_calls = []
    monkeypatch.setattr(ui, '_spawn', lambda *args, **kwargs: process)
    monkeypatch.setattr(
        ui,
        '_terminate_process_tree',
        lambda child: cleanup_calls.append(child),
    )

    with pytest.raises(raised):
        ui._run_setup(['tool', 'sync'], tmp_path, 'dependency setup')

    assert cleanup_calls == [process]


def test_tool_versions_accept_supported_node_and_pnpm(monkeypatch):
    versions = {
        '/tools/node': (22, 22, 0),
        '/tools/pnpm': (10, 17, 1),
    }

    monkeypatch.setattr(
        ui,
        '_read_semantic_version',
        lambda executable, flag, label: versions[executable],
    )

    ui._check_tool_versions({
        'node': '/tools/node',
        'pnpm': '/tools/pnpm',
    })


def test_tool_versions_do_not_require_pnpm_when_install_is_skipped(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ui,
        '_read_semantic_version',
        lambda executable, flag, label: calls.append(label) or (22, 22, 0),
    )

    ui._check_tool_versions({'node': '/tools/node'})

    assert calls == ['Node.js']


@pytest.mark.parametrize(
    ('node_version', 'pnpm_version', 'message'),
    [
        ((22, 21, 9), (10, 17, 1), 'Node.js 22.22.0 or newer'),
        ((22, 22, 0), (9, 15, 0), 'pnpm 10.x is required'),
        ((24, 0, 0), (11, 0, 0), 'pnpm 10.x is required'),
    ],
)
def test_tool_versions_reject_unsupported_versions(
    monkeypatch,
    node_version,
    pnpm_version,
    message,
):
    versions = {
        'node': node_version,
        'pnpm': pnpm_version,
    }
    monkeypatch.setattr(
        ui,
        '_read_semantic_version',
        lambda executable, flag, label: versions[executable],
    )

    with pytest.raises(ui.UIError, match=message):
        ui._check_tool_versions({'node': 'node', 'pnpm': 'pnpm'})


def test_dependency_sync_uses_frozen_project_local_commands(
    tmp_path,
    monkeypatch,
):
    backend_dir = tmp_path / 'webui' / 'backend'
    frontend_dir = tmp_path / 'webui' / 'frontend'
    backend_dir.mkdir(parents=True)
    frontend_dir.mkdir(parents=True)
    calls = []

    monkeypatch.setattr(ui, '_child_environment', lambda: {'BASE': 'value'})

    def fake_run_setup(command, cwd, label, env=None):
        calls.append({
            'command': command,
            'cwd': cwd,
            'label': label,
            'env': None if env is None else env.copy(),
        })

    monkeypatch.setattr(ui, '_run_setup', fake_run_setup)

    ui._ensure_dependencies(
        backend_dir,
        frontend_dir,
        {
            'uv': '/tools/uv',
            'pnpm': '/tools/pnpm',
        },
        skip_install=False,
    )

    assert calls == [
        {
            'command': ['/tools/uv', 'sync', '--frozen', '--no-dev'],
            'cwd': backend_dir,
            'label': 'backend dependency synchronization',
            'env': {
                'BASE': 'value',
                'UV_PROJECT_ENVIRONMENT': str(backend_dir / '.venv'),
            },
        },
        {
            'command': [
                '/tools/pnpm',
                'install',
                '--frozen-lockfile',
            ],
            'cwd': frontend_dir,
            'label': 'frontend dependency synchronization',
            'env': None,
        },
    ]


def test_skip_install_reports_all_missing_local_dependencies(
    tmp_path,
    monkeypatch,
):
    backend_dir = tmp_path / 'backend'
    frontend_dir = tmp_path / 'frontend'
    backend_dir.mkdir()
    frontend_dir.mkdir()
    monkeypatch.setattr(
        ui,
        '_run_setup',
        lambda *args, **kwargs: pytest.fail('setup must not run'),
    )

    with pytest.raises(ui.UIError) as error:
        ui._ensure_dependencies(
            backend_dir,
            frontend_dir,
            {
                'uv': 'uv',
                'pnpm': 'pnpm',
            },
            skip_install=True,
        )

    message = str(error.value)
    assert 'webui/backend/.venv' in message
    assert 'webui/frontend/node_modules' in message


@pytest.mark.parametrize('is_windows', [False, True])
def test_spawn_uses_platform_process_group(monkeypatch, tmp_path, is_windows):
    calls = []
    process = object()

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return process

    monkeypatch.setattr(ui, 'IS_WINDOWS', is_windows)
    monkeypatch.setattr(ui.subprocess, 'Popen', fake_popen)
    env = {'KEY': 'value'}

    result = ui._spawn(['tool', '--flag'], cwd=tmp_path, env=env)

    expected_kwargs = {
        'cwd': str(tmp_path),
        'env': env,
    }
    if is_windows:
        expected_kwargs['creationflags'] = ui.CREATE_NEW_PROCESS_GROUP
    else:
        expected_kwargs['start_new_session'] = True
    assert result is process
    assert calls == [(['tool', '--flag'], expected_kwargs)]


class _FakeProcess:

    def __init__(self, pid, wait_results, poll_result=None):
        self.pid = pid
        self._wait_results = list(wait_results)
        self.poll_result = poll_result
        self.sent_signals = []
        self.wait_timeouts = []
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return self.poll_result

    def send_signal(self, event):
        self.sent_signals.append(event)

    def terminate(self):
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1

    def wait(self, timeout):
        self.wait_timeouts.append(timeout)
        result = self._wait_results.pop(0)
        if result == 'timeout':
            raise subprocess.TimeoutExpired('child', timeout)
        return result


def test_windows_process_tree_cleanup_escalates_to_taskkill(monkeypatch):
    process = _FakeProcess(4321, ['timeout', 0])
    taskkill_calls = []
    monkeypatch.setattr(ui, 'IS_WINDOWS', True)
    monkeypatch.setattr(
        ui,
        '_taskkill',
        lambda pid, force: taskkill_calls.append((pid, force)) or True,
    )

    ui._terminate_process_tree(process, grace_seconds=0.25)

    assert process.sent_signals == [ui.CTRL_BREAK_EVENT]
    assert process.wait_timeouts == [0.25, 0.25]
    assert taskkill_calls == [(4321, True)]
    assert process.terminate_calls == 0
    assert process.kill_calls == 0


def test_posix_cleanup_targets_group_after_leader_already_exited(monkeypatch):
    process = _FakeProcess(7654, [], poll_result=1)
    killpg_calls = []
    wait_calls = []
    monkeypatch.setattr(ui, 'IS_WINDOWS', False)
    monkeypatch.setattr(
        ui.os,
        'killpg',
        lambda pid, event: killpg_calls.append((pid, event)),
        raising=False,
    )
    monkeypatch.setattr(
        ui,
        '_wait_for_posix_group_exit',
        lambda pid, timeout: wait_calls.append((pid, timeout)) or True,
    )

    ui._terminate_process_tree(process)

    assert killpg_calls == [(7654, signal.SIGTERM)]
    assert wait_calls == [(7654, 5.0)]
    assert process.wait_timeouts == []


def test_posix_cleanup_force_kills_stubborn_orphan_group(monkeypatch):
    process = _FakeProcess(7755, [], poll_result=1)
    killpg_calls = []
    wait_results = iter((False, True))
    monkeypatch.setattr(ui, 'IS_WINDOWS', False)
    monkeypatch.setattr(
        ui.os,
        'killpg',
        lambda pid, event: killpg_calls.append((pid, event)),
        raising=False,
    )
    monkeypatch.setattr(
        ui,
        '_wait_for_posix_group_exit',
        lambda pid, timeout: next(wait_results),
    )

    ui._terminate_process_tree(process, grace_seconds=0.1)

    assert killpg_calls == [
        (7755, signal.SIGTERM),
        (7755, signal.SIGKILL),
    ]


def test_windows_cleanup_attempts_tree_kill_after_leader_exited(monkeypatch):
    process = _FakeProcess(8765, [], poll_result=1)
    taskkill_calls = []
    warning_calls = []
    monkeypatch.setattr(ui, 'IS_WINDOWS', True)
    monkeypatch.setattr(
        ui,
        '_taskkill',
        lambda pid, force: taskkill_calls.append((pid, force)) or False,
    )
    monkeypatch.setattr(ui, '_warn_cleanup', warning_calls.append)

    ui._terminate_process_tree(process)

    assert taskkill_calls == [(8765, True)]
    assert warning_calls == [8765]
    assert process.wait_timeouts == []


def test_posix_process_tree_cleanup_escalates_process_group(monkeypatch):
    process = _FakeProcess(9876, ['timeout', 0])
    killpg_calls = []
    sigkill = getattr(signal, 'SIGKILL', 9)
    monkeypatch.setattr(ui, 'IS_WINDOWS', False)
    monkeypatch.setattr(ui.signal, 'SIGKILL', sigkill, raising=False)
    monkeypatch.setattr(
        ui.os,
        'killpg',
        lambda pid, event: killpg_calls.append((pid, event)),
        raising=False,
    )

    ui._terminate_process_tree(process, grace_seconds=0.5)

    assert killpg_calls == [
        (9876, signal.SIGTERM),
        (9876, sigkill),
    ]
    assert process.wait_timeouts == [0.5, 0.5]
    assert process.sent_signals == []
    assert process.terminate_calls == 0
    assert process.kill_calls == 0
