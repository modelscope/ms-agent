"""`/model list live` must keep the event loop free and still read /models.

The TUI and the WebUI share this command. The HTTP client stays synchronous
so a direct probe still returns ids; the async command runs that call on a
worker thread.
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dataclasses import dataclass, field

import pytest
from omegaconf import OmegaConf

from ms_agent.command.builtin import register_builtin_commands
from ms_agent.command.router import CommandRouter
from ms_agent.command.types import CommandContext


def _config():
    return OmegaConf.create({
        'llm': {
            'service': 'openai',
            'model': 'qwen-plus',
            'openai_api_key': 'sk-test',
        },
    })


@dataclass
class MockRuntime:
    should_stop: bool = False
    round: int = 0
    tag: str = 'test'
    llm: object = field(default_factory=lambda: type('L', (), {
        'model': 'qwen-plus',
        'config': _config(),
    })())


class _Catalog(BaseHTTPRequestHandler):
    delay = 1.2

    def do_GET(self):
        if self.path.rstrip('/').endswith('/models'):
            import time
            time.sleep(self.delay)
            body = json.dumps({'data': [{'id': 'qwen-plus'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        return


@pytest.fixture
def catalog_server():
    server = ThreadingHTTPServer(('127.0.0.1', 0), _Catalog)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f'http://{host}:{port}/v1'
    finally:
        server.shutdown()
        thread.join(timeout=3)


def _ctx(text, runtime):
    router = CommandRouter()
    register_builtin_commands(router)
    cmd, args = CommandRouter.parse_input(text)
    return CommandContext(
        raw_input=text,
        command_name=cmd,
        args=args,
        source='tui',
        runtime=runtime,
        extra={'router': router, 'messages': []},
    )


@pytest.mark.asyncio
async def test_live_list_returns_ids_without_blocking_the_loop(
        tmp_path, monkeypatch, catalog_server):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path / 'home'))
    runtime = MockRuntime()
    router = CommandRouter()
    register_builtin_commands(router)
    added = await router.dispatch(
        _ctx(
            f'/model provider add reviewslow key=sk-test '
            f'url={catalog_server} protocol=openai',
            runtime))
    assert added is not None
    assert 'saved' in added.content.lower()

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    task = asyncio.create_task(ticker())
    result = await router.dispatch(
        _ctx('/model list live reviewslow', runtime))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert ticks >= 8
    assert 'qwen-plus' in result.content
    assert 'live: 1 chat' in result.content

    from ms_agent.llm.model_discovery import probe_model_catalog
    probe = probe_model_catalog(catalog_server, 'openai', 'sk-test')
    assert probe.outcome == 'ok'
    assert probe.ids == ['qwen-plus']
