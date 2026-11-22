#!/usr/bin/env python3
# Copyright (c) ModelScope Contributors. All rights reserved.
"""Run with a fresh wheel environment's Python, outside the SDK checkout."""
import argparse
import importlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webui_smoke as smoke
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def ports_closed(ports):
    for port in ports:
        with socket.socket() as probe:
            probe.settimeout(1)
            assert probe.connect_ex(('127.0.0.1', port)) != 0, port


def child_pid(parent, marker):
    listing = subprocess.check_output(['ps', '-eo', 'pid,ppid,args'],
                                      text=True)
    for line in listing.splitlines()[1:]:
        pid, ppid, command = line.strip().split(None, 2)
        if int(ppid) == parent and marker in command:
            return int(pid)
    raise AssertionError('Child process not found: ' + marker)


def check_unbuffered_proxy(frontend, env, log_path):
    """The second chunk is withheld until the first passes through Node."""
    received = threading.Event()

    class Handler(BaseHTTPRequestHandler):

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(b'data: {"type":"text","content":"first"}\n\n')
            self.wfile.flush()
            if received.wait(timeout=10):
                self.wfile.write(b'data: {"type":"done"}\n\n')
                self.wfile.flush()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = free_port()
    api = 'http://127.0.0.1:' + str(server.server_port)
    config = {
        **env, 'NODE_ENV': 'production',
        'HOST': '127.0.0.1',
        'PORT': str(port),
        'MS_AGENT_API_BASE_URL': api,
        'MS_AGENT_FRONTEND_API_BASE_URL': api
    }
    with log_path.open('w') as log:
        process = subprocess.Popen(
            ['node', str(frontend / 'server.js')],
            cwd=frontend,
            env=config,
            stdout=log,
            stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    with socket.create_connection(('127.0.0.1', port),
                                                  timeout=1):
                        break
                except OSError:
                    assert process.poll() is None and time.monotonic(
                    ) < deadline
                    time.sleep(0.1)
            with smoke.request('http://127.0.0.1:' + str(port),
                               '/api/chat/attach', {}) as response:
                assert response.headers.get('Content-Encoding') is None
                assert b'first' in response.readline()
                assert response.readline() == b'\n'
                received.set()
                assert b'"done"' in response.read()
        finally:
            received.set()
            process.terminate()
            process.wait(timeout=15)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    ports_closed((port, ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--logs', type=Path, required=True)
    args = parser.parse_args()
    args.logs.mkdir(parents=True, exist_ok=True)
    # The image shares these locked dependencies with the full SDK CLI.
    importlib.import_module('ms_agent.agent_hub')
    # Document conversion remains available without optional Python/Notebook tools.
    for module in ('bs4', 'lxml'):
        importlib.import_module(module)
    from ms_agent.cli.ui_resources import file_digest, find_webui

    bundled, installed = find_webui()
    assert installed, 'Use a fresh installed wheel, not an editable checkout'
    before = {
        str(p.relative_to(bundled)): file_digest(p)
        for p in bundled.rglob('*') if p.is_file()
    }
    modes = {p: p.stat().st_mode for p in bundled.rglob('*')}
    modes[bundled] = bundled.stat().st_mode
    with tempfile.TemporaryDirectory(
            prefix='ms-agent-installed-smoke-') as tmp:
        root = Path(tmp)
        env = {
            **os.environ, 'HOME': str(root / 'home'),
            'MS_AGENT_HOME': str(root / 'data'),
            'MS_AGENT_WEBUI_CACHE': str(root / 'cache'),
            'PYTHONDONTWRITEBYTECODE': '1',
            'MS_AGENT_LLM_MODEL': ''
        }
        env.pop('PYTHONPATH', None)
        Path(env['HOME']).mkdir()
        command = [
            sys.executable, '-m', 'ms_agent.cli.cli', 'ui', '--no-browser'
        ]
        try:
            for path in modes:
                path.chmod(0o555 if path.is_dir() else 0o444)
            with (args.logs / 'installed-prepare.log').open('w') as log:
                subprocess.run(
                    command + ['--prepare-only'],
                    cwd=root,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                    timeout=600)
            stamps = list(
                (root / 'cache').glob('*/frontend/.node-dependencies.json'))
            assert len(stamps) == 1
            stamp = stamps[0].stat().st_mtime_ns
            check_unbuffered_proxy(stamps[0].parent, env,
                                   args.logs / 'installed-sse-proxy.log')
            state = None
            # First start and restart, then independent backend/frontend deaths.
            for scenario in ('normal', 'restart', 'backend', 'frontend'):
                public, api = free_port(), free_port()
                while public == api:
                    api = free_port()
                base = 'http://127.0.0.1:' + str(public)
                with (args.logs /
                      ('installed-' + scenario + '.log')).open('w') as log:
                    process = subprocess.Popen(
                        command + [
                            '--skip-install', '--port',
                            str(public), '--backend-port',
                            str(api)
                        ],
                        cwd=root,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT)
                    try:
                        smoke.ready(base, timeout=90)
                        assert process.poll() is None
                        assert stamps[0].stat().st_mtime_ns == stamp
                        if scenario == 'normal':
                            state = smoke.create(base)
                        elif scenario == 'restart':
                            smoke.verify(base, state)
                            smoke.cleanup(base, state)
                        if scenario in ('backend', 'frontend'):
                            marker = '_run_api' if scenario == 'backend' else 'server.js'
                            os.kill(
                                child_pid(process.pid, marker), signal.SIGKILL)
                            assert process.wait(timeout=20) != 0
                        else:
                            process.send_signal(signal.SIGTERM)
                            assert process.wait(timeout=20) == 0
                    finally:
                        if process.poll() is None:
                            process.terminate()
                            process.wait(timeout=20)
                ports_closed((public, api))
            # Explicit occupied ports must fail before dependencies or children.
            with socket.socket() as occupied:
                occupied.bind(('127.0.0.1', 0))
                occupied.listen()
                result = subprocess.run(
                    command + [
                        '--skip-install', '--port',
                        str(occupied.getsockname()[1])
                    ],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=15)
                assert result.returncode != 0
                assert 'port' in (result.stdout + result.stderr).lower()
            after = {
                str(p.relative_to(bundled)): file_digest(p)
                for p in bundled.rglob('*') if p.is_file()
            }
            assert before == after, 'Startup wrote inside the installed bundle'
        finally:
            for path, mode in modes.items():
                path.chmod(mode)
    print(
        json.dumps({
            'installed_wheel': 'passed',
            'read_only_bundle': 'passed',
            'cache_reuse': 'passed',
            'crud_sse_restart': 'passed',
            'skills_watcher_restart': 'passed',
            'signal_and_child_failure': 'passed'
        }))


if __name__ == '__main__':
    main()
