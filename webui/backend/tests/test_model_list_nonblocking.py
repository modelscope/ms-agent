"""WebUI `/model list live` must not stall /api/health.

The chat command and the health route share one worker. A slow /models
response used to freeze health for the whole probe. The catalog request
still has to complete, and health has to answer while it is in flight.
"""
import json
import socket
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import uvicorn

from app.core.settings import settings


class _SlowCatalog(BaseHTTPRequestHandler):
    window = []

    def do_GET(self):
        if self.path.rstrip('/').endswith('/models'):
            start = time.perf_counter()
            time.sleep(2.0)
            self.window.append((start, time.perf_counter()))
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


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_webui_health_stays_fast_during_live_model_list(tmp_path, monkeypatch):
    import ms_agent.command.builtin.config_cmds as cmds
    repo = Path(__file__).resolve().parents[3]
    if not Path(cmds.__file__).resolve().is_relative_to(repo):
        pytest.skip('this check follows the worktree SDK, not the installed copy')
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    monkeypatch.setattr(settings, 'ms_agent_llm_model', '')
    _SlowCatalog.window = []
    catalog = ThreadingHTTPServer(('127.0.0.1', 0), _SlowCatalog)
    catalog_thread = threading.Thread(target=catalog.serve_forever, daemon=True)
    catalog_thread.start()
    catalog_root = f'http://{catalog.server_address[0]}:{catalog.server_address[1]}/v1'

    from app.main import create_app
    app = create_app()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(
        app, host='127.0.0.1', port=port, log_level='warning'))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            if httpx.get(f'http://127.0.0.1:{port}/api/health', timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        catalog.shutdown()
        pytest.fail('webui did not start')

    base = f'http://127.0.0.1:{port}'
    samples = []
    stop = threading.Event()

    def poll_health():
        while not stop.is_set():
            started = time.perf_counter()
            try:
                response = httpx.get(f'{base}/api/health', timeout=5)
                samples.append((started, time.perf_counter() - started, response.status_code))
            except httpx.HTTPError as exc:
                samples.append((started, time.perf_counter() - started, str(exc)))
            time.sleep(0.05)

    try:
        with httpx.Client(base_url=base, timeout=60) as client:
            assert client.post('/api/providers', json={
                'id': 'reviewslow',
                'name': 'reviewslow',
                'base_url': catalog_root,
                'protocol': 'openai',
            }).status_code == 201
            assert client.patch('/api/providers/reviewslow', json={
                'api_key': 'sk-test',
            }).status_code == 200
            model = client.post('/api/models', json={
                'provider_id': 'reviewslow', 'name': 'qwen-plus'})
            assert model.status_code == 201
            mid = model.json()['data']['id']
            assert client.patch('/api/agent-settings', json={
                'default_model_id': mid}).status_code == 200
            session = client.post('/api/sessions', json={'title': 'live'})
            assert session.status_code == 201
            session_id = session.json()['data']['id']

            poller = threading.Thread(target=poll_health, daemon=True)
            poller.start()
            with client.stream('POST', '/api/chat', json={
                'session_id': session_id,
                'message': {
                    'role': 'user',
                    'content': '/model list live reviewslow',
                },
            }) as response:
                body = response.read().decode('utf-8', errors='replace')
            stop.set()
            poller.join(timeout=2)
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)
        catalog.shutdown()
        catalog_thread.join(timeout=3)

    assert _SlowCatalog.window, body[:1500]
    probe_start, probe_end = _SlowCatalog.window[-1]
    assert probe_end - probe_start >= 1.5
    during = [
        latency for started, latency, code in samples
        if probe_start <= started <= probe_end and code == 200
    ]
    assert len(during) >= 3, (
        f'health did not keep answering during the probe; '
        f'samples={samples[-8:]} body={body[:800]}')
    assert max(during) < 0.8, during
    assert '"type":"done"' in body
    assert '"type":"error"' not in body
