"""直接执行双语文档中的示例；仅使用隔离文件和本地模拟模型。"""
import asyncio
import base64
import json
import os
import pytest
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

pytest.importorskip('omegaconf')
ROOT = Path(__file__).resolve().parents[2]


def block(lang, page, kind, index=0):
    text = (ROOT / 'docs' / lang / (page + '.md')).read_text()
    return re.findall(r'```' + kind + r'\n(.*?)\n```', text, re.S)[index]


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    for key in list(os.environ):
        if any(word in key.upper() for word in ('API_KEY', 'TOKEN', 'SECRET',
                                                'TRY_EXP_FRAMEWORKS')):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('MS_AGENT_HOME', str(home / '.ms_agent'))
    monkeypatch.setenv('PYTHON_DOTENV_DISABLED', '1')
    monkeypatch.setenv('MS_AGENT_MODEL_CATALOG', 'bundled')
    monkeypatch.setenv('PYTHONPATH', str(ROOT))
    monkeypatch.setenv(
        'PATH',
        str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH'])
    return tmp_path


def run(args, root, data=None):
    result = subprocess.run(
        args, cwd=root, input=data, text=True, capture_output=True, timeout=60)
    return result


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_handler_module_and_trust(lang, isolated, monkeypatch):
    from ms_agent import LLMAgent
    from ms_agent.config import Config
    root = isolated
    (root / 'reviewed_handler.py').write_text(
        block(lang, 'development/configuration-reference', 'python'))
    (root / 'agent.yaml').write_text(
        block(lang, 'development/configuration-reference', 'yaml'))
    monkeypatch.setattr(sys, 'argv', ['check'])
    config = Config.from_task(str(root / 'agent.yaml'))
    assert Path(config.local_dir) == root
    from omegaconf import OmegaConf
    config.llm = OmegaConf.create({})
    config.output_dir = str(root / 'work')
    try:
        with pytest.raises(AssertionError):
            LLMAgent(config=config)
        agent = LLMAgent(config=config, trust_remote_code=True)
        assert agent.config_handler.task_begin(config, 'demo') is config
    finally:
        sys.modules.pop('reviewed_handler', None)
        if str(root) in sys.path:
            sys.path.remove(str(root))


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_hub_default_conversion_dry_run(lang, isolated):
    root = isolated
    src = root / 'source'
    skill = src / 'skills/greeting'
    skill.mkdir(parents=True)
    (src / 'AGENTS.md').write_text('# Instructions\nOnly greet the user.\n')
    (skill / 'SKILL.md').write_text(
        '---\nname: greeting\ndescription: Say hello without tools.\n---\n# Greeting\nReply with Hello.\n'
    )
    before = {
        p.relative_to(src): p.read_bytes()
        for p in src.rglob('*') if p.is_file()
    }
    cli = str(Path(sys.executable).parent / 'ms-agent')
    result = run([
        cli, 'agent', 'convert', '--from-framework', 'ms-agent',
        '--target-framework', 'qwenpaw', '--local-dir',
        str(src), '--out-dir',
        str(root / 'converted'), '--dry-run'
    ], root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'qwenpaw' in result.stdout.lower()
    assert not (root / 'converted').exists()
    assert before == {
        p.relative_to(src): p.read_bytes()
        for p in src.rglob('*') if p.is_file()
    }
    assert '--target-framework qwenpaw' in (ROOT / 'docs' / lang
                                            / 'core/agent-hub.md').read_text()


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_hook_script_and_executor(lang, isolated):
    root = isolated
    (root / 'agent.yaml').write_text(block(lang, 'core/hooks', 'yaml'))
    (root / 'hook_check.py').write_text(block(lang, 'core/hooks', 'python'))
    (root / 'verify_hook.py').write_text(
        block(lang, 'core/hooks', 'python', 1))
    result = run([sys.executable, 'hook_check.py'], root,
                 '{"event":"SessionStart","session_id":"demo"}')
    assert result.returncode == 0
    assert json.loads(
        result.stdout)['additional_context'] == 'Hook demo started.'
    result = run([sys.executable, 'hook_check.py'], root,
                 '{"event":"PreToolUse","tool_args":{"path":"blocked.txt"}}')
    assert result.returncode == 2 and 'reserved' in result.stderr
    result = run([sys.executable, 'verify_hook.py'], root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PreToolUse=pass/deny' in result.stdout


@pytest.mark.parametrize('fail_closed,expected', [(False, 'error'),
                                                  (True, 'deny')])
@pytest.mark.parametrize('mode', ['timeout', 'nonzero', 'missing'])
def test_hook_failure_contract(mode, fail_closed, expected, isolated):
    from ms_agent.hooks.executors.command import (CommandHookExecutor,
                                                  HookExecutionContext)
    from ms_agent.hooks.registry import HookHandlerConfig
    root = isolated
    script = root / 'failure.py'
    script.write_text('import time,sys\ntime.sleep(1)\n' if mode ==
                      'timeout' else 'import sys\nsys.exit(3)\n')
    command = f'{sys.executable} {script}' if mode != 'missing' else str(
        root / 'missing-program')
    handler = HookHandlerConfig(
        type='command', command=command, timeout=0.05, fail_closed=fail_closed)
    result = asyncio.run(
        CommandHookExecutor(working_dir=str(root)).execute(
            handler, {'event': 'PreToolUse'},
            HookExecutionContext('demo', str(root))))
    assert result.action == expected


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_plugin_full_lifecycle_and_discovery(lang, isolated):
    root = isolated
    source = root / 'my-plugin'
    (source / '.claude-plugin').mkdir(parents=True)
    (source / 'skills/greeting').mkdir(parents=True)
    (root / 'project').mkdir()
    (source / '.claude-plugin/plugin.json').write_text(
        block(lang, 'core/plugins', 'json'))
    (source / 'skills/greeting/SKILL.md').write_text(
        block(lang, 'core/plugins', 'markdown'))
    checker = root / 'verify_plugin.py'
    checker.write_text(block(lang, 'core/plugins', 'python'))
    cli = str(Path(sys.executable).parent / 'ms-agent')

    def command(*args):
        result = run(
            [cli, 'plugin', *args, '--project-path',
             str(root / 'project')], root)
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    def check(status):
        result = run(
            [sys.executable,
             str(checker),
             str(root / 'project'), status], root)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    command('install', str(source), '--disabled')
    record = json.loads(command('list', '--json').stdout)['plugins'][0]
    assert record['plugin_id'] == 'docs-demo' and not record['enabled']
    assert 'not loaded' in check('disabled')
    command('toggle', 'docs-demo', '--enable')
    assert 'full content' in check('enabled')
    command('toggle', 'docs-demo', '--disable')
    assert 'not loaded' in check('disabled')
    command('uninstall', 'docs-demo', '--purge')
    assert json.loads(command('list', '--json').stdout)['plugins'] == []
    assert (source / 'skills/greeting/SKILL.md').exists()


@pytest.fixture
def model_server():
    seen = []

    class Handler(BaseHTTPRequestHandler):

        def log_message(self, *args):
            pass

        def do_POST(self):
            data = json.loads(
                self.rfile.read(int(self.headers['Content-Length'])))
            seen.append(data)
            self.send_response(200)
            if data.get('stream'):
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                for delta, finish in [({
                        'role': 'assistant',
                        'content': 'A red square.'
                }, None), ({}, 'stop')]:
                    item = {
                        'id':
                        'local-response',
                        'object':
                        'chat.completion.chunk',
                        'model':
                        data['model'],
                        'choices': [{
                            'index': 0,
                            'delta': delta,
                            'finish_reason': finish
                        }]
                    }
                    self.wfile.write(
                        ('data: ' + json.dumps(item) + '\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n')
            else:
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                item = {
                    'id':
                    'local-response',
                    'object':
                    'chat.completion',
                    'model':
                    data['model'],
                    'choices': [{
                        'index': 0,
                        'message': {
                            'role': 'assistant',
                            'content': 'A red square.'
                        },
                        'finish_reason': 'stop'
                    }],
                    'usage': {
                        'prompt_tokens': 50,
                        'completion_tokens': 5,
                        'total_tokens': 55
                    }
                }
                self.wfile.write(json.dumps(item).encode())

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('lang', ['zh', 'en'])
@pytest.mark.parametrize('flags',
                         [[], ['--stream'], ['--stream', '--follow-up']])
def test_multimodal_full_sdk_example(lang, flags, isolated, model_server,
                                     monkeypatch):
    from PIL import Image
    root = isolated
    url, seen = model_server
    monkeypatch.setenv('OPENAI_BASE_URL', url)
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-placeholder')
    monkeypatch.setenv('VISION_MODEL', 'offline-vision-model')
    image = root / 'sample.png'
    Image.new('RGB', (160, 160), 'red').save(image)
    script = root / 'multimodal_demo.py'
    script.write_text(block(lang, 'core/multimodal', 'python'))
    result = run([sys.executable, str(script), str(image), *flags], root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'A red square.' in result.stdout
    assert len(seen) == (2 if '--follow-up' in flags else 1)
    for request in seen:
        content = next(message['content'] for message in request['messages']
                       if message['role'] == 'user'
                       and isinstance(message['content'], list))
        images = [item for item in content if item.get('type') == 'image_url']
        assert len(images) == 1
        decoded = base64.b64decode(images[0]['image_url']['url'].split(',',
                                                                       1)[1])
        assert decoded.startswith(b'\x89PNG')
    assert image.exists()


@pytest.mark.parametrize('lang', ['zh', 'en'])
@pytest.mark.parametrize('blocked', [False, True])
def test_hook_actual_agent_lifecycle(lang, blocked, isolated, monkeypatch):
    from omegaconf import OmegaConf

    from ms_agent import LLMAgent
    from ms_agent.config import Config
    from ms_agent.llm.llm import LLM
    from ms_agent.llm.utils import Message
    root = isolated
    (root / 'hook_check.py').write_text(block(lang, 'core/hooks', 'python'))
    (root / 'agent.yaml').write_text(block(lang, 'core/hooks', 'yaml'))
    (root / 'work').mkdir()
    path = root / 'work' / ('blocked.txt' if blocked else 'notes.txt')
    path.write_text('Only a synthetic note.')
    monkeypatch.setattr(sys, 'argv', ['check'])
    config = Config.from_task(str(root / 'agent.yaml'))
    config.llm = OmegaConf.create({
        'service': 'openai',
        'use_provider_router': True,
        'api_key': 'offline-placeholder',
        'base_url': 'http://127.0.0.1:1/v1',
        'model': 'offline-model'
    })
    config.generation_config = OmegaConf.create({'stream': False})
    config.tools = OmegaConf.create(
        {'file_system': {
            'mcp': False,
            'include': ['read_file']
        }})
    config.permission = OmegaConf.create({'mode': 'full-access'})
    config.max_chat_round = 3
    config.interactive = False
    config.output_dir = str(root / 'work')
    config.callbacks = []
    events = []
    calls = []

    def generate(self, messages, *args, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            return Message(
                role='assistant',
                tool_calls=[{
                    'id': 'demo-call',
                    'type': 'function',
                    'tool_name': 'file_system---read_file',
                    'arguments': json.dumps({'path': str(path)}),
                }])
        return Message(role='assistant', content='Demo complete.')

    original_factory = LLM.from_config

    def mock_factory(config):
        from types import MethodType
        client = original_factory(config)
        client.generate = MethodType(generate, client)
        return client

    monkeypatch.setattr(LLM, 'from_config', staticmethod(mock_factory))

    class ObservedAgent(LLMAgent):

        async def prepare_tools(self, *args, **kwargs):
            await super().prepare_tools(*args, **kwargs)

            async def capture(event):
                events.append(event)

            self._hook_runtime.on_hook_event = capture

    async def exercise():
        agent = ObservedAgent(config=config)
        try:
            return await agent.run(messages='Read the synthetic note.')
        finally:
            await agent.cleanup_tools()

    result = asyncio.run(exercise())
    assert result
    assert any(event['hook_event'] == 'SessionStart' for event in events)
    assert any(event['hook_event'] == 'PreToolUse' and event['action'] == (
        'deny' if blocked else 'pass') for event in events)
    tools = [message for message in result if message.role == 'tool']
    assert tools
    if blocked:
        assert 'reserved by this demo' in tools[0].content
        assert 'Only a synthetic note.' not in tools[0].content
    else:
        assert 'Only a synthetic note.' in tools[0].content


@pytest.mark.parametrize('failure', ['error', 'cancel'])
def test_multimodal_example_cleanup_on_failure(failure, isolated, monkeypatch):
    from PIL import Image

    import ms_agent
    root = isolated
    image = root / 'sample.png'
    Image.new('RGB', (16, 16), 'red').save(image)
    monkeypatch.setenv('OPENAI_BASE_URL', 'http://127.0.0.1:1/v1')
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-placeholder')
    monkeypatch.setenv('VISION_MODEL', 'offline-model')
    cleaned = []

    class FakeAgent:

        def __init__(self, config):
            self.config = config

        async def run(self, **kwargs):
            if failure == 'cancel':
                raise asyncio.CancelledError()
            raise RuntimeError('Synthetic failure')

        async def cleanup_tools(self):
            cleaned.append(True)

    monkeypatch.setattr(ms_agent, 'LLMAgent', FakeAgent)
    monkeypatch.setattr(sys, 'argv', ['multimodal_demo.py', str(image)])
    namespace = {'__name__': 'demo_test'}
    exec(
        compile(
            block('zh', 'core/multimodal', 'python'), 'multimodal_demo.py',
            'exec'), namespace)
    with pytest.raises(asyncio.CancelledError if failure ==
                       'cancel' else RuntimeError):
        asyncio.run(namespace['main']())
    assert cleaned == [True]
    assert image.exists()


@pytest.mark.parametrize('kind', ['http', 'prompt', 'agent'])
def test_hook_parsed_types_are_not_executors(kind, isolated):
    from omegaconf import OmegaConf

    from ms_agent.hooks.executors.command import HookExecutionContext
    from ms_agent.hooks.factory import build_hook_runtime
    handler = {
        'type': kind,
        'url': 'http://127.0.0.1:1/hook',
        'prompt': 'No external calls.'
    }
    config = OmegaConf.create({
        'output_dir': str(isolated),
        'local_dir': str(isolated),
        'hooks': {
            'PreToolUse': [{
                'hooks': [handler]
            }]
        }
    })
    assert build_hook_runtime(config).is_empty
    config.hooks.enabled_executors = ['command', kind]
    runtime = build_hook_runtime(config)
    parsed = runtime.registry.get_handlers('PreToolUse', 'demo')[0]
    result = asyncio.run(
        runtime.executor.execute(parsed, {'event': 'PreToolUse'},
                                 HookExecutionContext('demo', str(isolated))))
    assert result.action == 'error'
