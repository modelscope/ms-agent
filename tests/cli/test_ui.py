from argparse import ArgumentParser
from types import SimpleNamespace

import pytest

from ms_agent.cli import ui


def _frontend_package_json():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    return json.loads((root / 'webui/frontend/package.json').read_text())


def _parse_ui_args(*extra_args):
    parser = ArgumentParser()
    subparsers = parser.add_subparsers()
    ui.UICMD.define_args(subparsers)
    return parser.parse_args(['ui'] + list(extra_args))



def test_ui_parser_defaults_use_automatic_ssr_ports():
    args = _parse_ui_args()

    assert args.host == '127.0.0.1'
    assert args.port is None
    assert args.backend_port is None
    assert args.reload is False
    assert args.skip_install is False
    assert args.production is False
    assert args.no_browser is False



@pytest.mark.parametrize('value', ['0', '-1', '65536', 'not-a-port'])
def test_ui_parser_rejects_invalid_ports(value):
    with pytest.raises(SystemExit):
        _parse_ui_args('--port', value)



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



def test_tool_versions_accept_supported_node_and_pnpm(monkeypatch, tmp_path):
    versions = {
        '/tools/node': (22, 22, 0),
        '/tools/pnpm': (10, 17, 1),
    }
    probes = []

    def fake_version(executable, flag, label, cwd=None):
        probes.append({'executable': executable, 'label': label, 'cwd': cwd})
        return versions[executable]

    monkeypatch.setattr(ui, '_read_semantic_version', fake_version)

    ui._check_tool_versions(
        {
            'node': '/tools/node',
            'pnpm': '/tools/pnpm',
        },
        frontend_dir=tmp_path,
    )

    # Assert what was measured, not merely that nothing raised: an empty body in
    # _check_tool_versions used to satisfy this test.
    assert [p['label'] for p in probes] == ['Node.js', 'pnpm']
    # pnpm MUST be probed inside webui/frontend — `packageManager` there makes
    # pnpm self-manage, so a probe from another cwd measures the wrong binary.
    assert probes[1]['cwd'] == tmp_path
    assert probes[0]['cwd'] is None



def test_tool_versions_do_not_require_pnpm_when_install_is_skipped(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ui,
        '_read_semantic_version',
        lambda executable, flag, label, cwd=None: calls.append(label) or
        (22, 22, 0),
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
        lambda executable, flag, label, cwd=None: versions[executable],
    )

    with pytest.raises(ui.UIError, match=message):
        ui._check_tool_versions({'node': 'node', 'pnpm': 'pnpm'})



@pytest.mark.parametrize(
    ('stdout', 'expected'),
    [
        ('v22.22.0\n', (22, 22, 0)),
        ('10.17.1\n', (10, 17, 1)),
        ('22.22\n', (22, 22, 0)),
        # Node prints deprecation notices; the old first-match-anywhere regex
        # read "20.1" here and rejected a valid pnpm as "found 20.1.0".
        ('WARN Node.js 20.1 is deprecated\n10.17.1\n', (10, 17, 1)),
        # Corepack announces the download of the pinned pnpm before printing it.
        ('! Corepack is about to download pnpm-10.17.1.tgz\n10.17.1\n',
         (10, 17, 1)),
        # uv tells you a newer version exists; that is not the version you have.
        ('warning: uv 0.12.9 is available (you have 0.12.1)\nuv 0.12.1\n',
         (0, 12, 1)),
        # A version-manager / conda preamble with a dotted number.
        ('Anaconda3 2024.02 activated\n10.17.1\n', (10, 17, 1)),
        ('  \n\nv26.0.0\n  \n', (26, 0, 0)),
    ],
)
def test_semantic_version_ignores_preamble_noise(stdout, expected):
    assert ui._parse_semantic_version(stdout, 'pnpm', '/tools/pnpm') == expected



def test_semantic_version_error_names_the_executable():
    with pytest.raises(ui.UIError, match=r'/tools/pnpm'):
        ui._parse_semantic_version('no version here\n', 'pnpm', '/tools/pnpm')



def test_min_node_version_matches_package_json_engines():
    """ui.MIN_NODE_VERSION duplicates engines.node by necessity (the launcher
    gates before any Node tooling can read the manifest). This lock is what
    keeps the two from drifting apart silently."""
    import re
    engines = _frontend_package_json()['engines']['node']
    match = re.fullmatch(r'>=(\d+)\.(\d+)\.(\d+)', engines)
    assert match, f'unexpected engines.node format: {engines!r}'
    assert tuple(int(p) for p in match.groups()) == ui.MIN_NODE_VERSION



def test_pnpm_major_gate_matches_package_manager_pin():
    """The launcher accepts any pnpm 10.x; the manifest pins 10.17.1 and bounds
    engines.pnpm to >=10 <11. All three must agree on the major."""
    pkg = _frontend_package_json()
    pinned = pkg['packageManager']
    assert pinned.startswith('pnpm@10.'), pinned
    assert pkg['engines']['pnpm'] == '>=10 <11'



def test_tool_versions_reject_old_uv_with_path(monkeypatch):
    versions = {
        '/tools/node': (22, 22, 0),
        '/tools/uv': (0, 4, 9),
    }
    monkeypatch.setattr(
        ui,
        '_read_semantic_version',
        lambda executable, flag, label, cwd=None: versions[executable],
    )

    with pytest.raises(ui.UIError) as excinfo:
        ui._check_tool_versions({
            'node': '/tools/node',
            'uv': '/tools/uv',
        })

    message = str(excinfo.value)
    assert 'uv 0.5.0 or newer' in message
    # The resolved path is the actionable part: "installed it, but PATH found
    # another one" is indistinguishable from a bare version number.
    assert '/tools/uv' in message



def test_production_flag_is_a_compatibility_alias():
    args = _parse_ui_args('--production', '--prepare-only')
    assert args.production and args.prepare_only


def test_reload_fails_with_development_instructions(capsys):
    with pytest.raises(SystemExit) as error:
        ui.UICMD(_parse_ui_args('--reload')).execute()
    assert error.value.code == 1
    assert 'pnpm dev' in capsys.readouterr().err


def _prepare_installed_kwargs(monkeypatch, trace_env=None):
    """Drive execute() far enough to capture what it hands prepare_installed.

    `--prepare-only` returns before ports and the launcher, so the WebUI backend
    never has to be importable here: a stub `app.processes` satisfies the single
    import execute() makes for its own signal handling.
    """
    import contextlib
    import sys
    import types
    from pathlib import Path

    package = types.ModuleType('app')
    package.__path__ = []

    @contextlib.contextmanager
    def interruptible():
        yield

    processes = types.ModuleType('app.processes')
    processes.interruptible = interruptible
    monkeypatch.setitem(sys.modules, 'app', package)
    monkeypatch.setitem(sys.modules, 'app.processes', processes)

    if trace_env is None:
        monkeypatch.delenv(ui.TRACE_RUNTIME_ENV, raising=False)
    else:
        monkeypatch.setenv(ui.TRACE_RUNTIME_ENV, trace_env)

    captured = {}
    monkeypatch.setattr(ui, 'find_webui', lambda: (Path('/webui'), True))
    monkeypatch.setattr(ui, 'load_common', lambda webui: SimpleNamespace())
    monkeypatch.setattr(ui, '_require_executable', lambda name: '/tools/' + name)
    monkeypatch.setattr(ui, '_check_tool_versions',
                        lambda tools, frontend=None: None)
    monkeypatch.setattr(ui, '_read_semantic_version',
                        lambda *args, **kwargs: (22, 22, 0))

    def fake_prepare(webui, common, node_version, **kwargs):
        captured.update(kwargs)
        return webui

    monkeypatch.setattr(ui, 'prepare_installed', fake_prepare)
    ui.UICMD(_parse_ui_args('--prepare-only', '--no-browser')).execute()
    return captured


def test_runtime_tracing_is_off_unless_the_environment_asks(monkeypatch):
    assert _prepare_installed_kwargs(monkeypatch)['trace_runtime'] is None


def test_runtime_tracing_env_reaches_preparation(monkeypatch):
    kwargs = _prepare_installed_kwargs(monkeypatch, trace_env='1')
    assert callable(kwargs['trace_runtime'])


@pytest.mark.parametrize('value', ['0', '', 'true', 'yes', 'false'])
def test_only_an_exact_1_enables_runtime_tracing(monkeypatch, value):
    """A truthiness check here would trace on `=0`, and the cost of that (a full
    devDependency install plus a tracing pass) lands on whoever set the variable
    specifically to turn the feature off."""
    kwargs = _prepare_installed_kwargs(monkeypatch, trace_env=value)
    assert kwargs['trace_runtime'] is None
