"""Opt-in check of the built frontend, API proxy and real launcher.

Build frontend with `pnpm build`, then run:
RUN_WEBUI_STACK=1 uv run pytest tests/test_auth_stack.py -q
No provider credentials or model calls are needed.
"""
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from app.core.auth import COOKIE_NAME

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_WEBUI_STACK") != "1", reason="requires pnpm build and Node"
)
BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "test-only-stack-password"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(params=[False, True], ids=["hosted-without-login", "with-login"])
def stack(request, tmp_path):
    enabled = request.param
    port, api_port = free_port(), free_port()
    while port == api_port:
        api_port = free_port()
    env = {
        **os.environ,
        "MS_AGENT_HOME": str(tmp_path / "data"),
        "MS_AGENT_WEBUI_INSTALLED": "1",  # ignore a developer's dotenv
        "MS_AGENT_WEBUI_AUTH_ENABLED": str(enabled).lower(),
        "MS_AGENT_WEBUI_USERNAME": "owner",
        "MS_AGENT_WEBUI_PASSWORD": PASSWORD if enabled else "",
        "MS_AGENT_FRONTEND_HOSTED_MODE": "0" if enabled else "1",
        "MS_AGENT_LLM_MODEL": "",
        "LOG_LEVEL": "ERROR",
    }
    log_path = tmp_path / "stack.log"
    with log_path.open("w") as log, httpx.Client(
        base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=15,
    ) as client:
        process = subprocess.Popen(
            [sys.executable, "-c", "from app.launcher import main; main()",
             "--no-open", "--host", "0.0.0.0", "--port", str(port),
             "--backend-port", str(api_port)],
            cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 60
            while "MS-Agent WebUI ready:" not in log_path.read_text():
                assert process.poll() is None, log_path.read_text()
                assert time.monotonic() < deadline, log_path.read_text()
                time.sleep(0.1)
            if not enabled:
                assert "authentication is disabled" in log_path.read_text()
            yield client, enabled, api_port
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_pages_proxy_files_streams_and_visitor_isolation(stack):
    client, enabled, api_port = stack
    status = client.get("/api/auth/status").json()["data"]
    assert status["enabled"] is enabled
    assert status["authenticated"] is not enabled
    assert client.get("/api/health").status_code == 200
    if enabled:
        for path in ("/", "/settings/models"):
            response = client.get(path)
            assert response.status_code == 302, (path, response.text)
            assert response.headers["location"].startswith("/login?next=")
        # React Router encodes .data redirects in its Single Fetch protocol.
        data = client.get("/settings/models.data")
        assert data.status_code == 202
        assert "SingleFetchRedirect" in data.text and "/login?next=" in data.text
        assert client.get("/api/projects").status_code == 401
        # The internal loopback API has the same protection.
        with httpx.Client(trust_env=False) as direct:
            assert direct.get(f"http://127.0.0.1:{api_port}/api/projects").status_code == 401
        page = client.get("/login?__language=zh")
        assert page.status_code == 200 and 'name="password"' in page.text
        assert PASSWORD not in page.text
        assert client.post("/api/auth/login", json={
            "username": "owner", "password": PASSWORD,
        }, headers={"Origin": str(client.base_url).rstrip("/")}).status_code == 200
        assert COOKIE_NAME in client.cookies
    else:
        assert client.get("/login").headers["location"] == "/"
    assert client.get("/").status_code == 200
    assert client.get("/settings/models.data").status_code == 200
    project = client.post("/api/projects", json={
        "name": "private-auth-stack-project", "memory_enabled": False,
    }).json()["data"]
    pid = project["id"]
    try:
        path = f"/api/projects/{pid}/workspace"
        upload = client.post(path + "/files/upload", files={
            "file": ("auth-check.txt", b"authenticated upload", "text/plain"),
        })
        assert upload.status_code == 201, upload.text
        assert client.get(path + "/raw/auth-check.txt").text == "authenticated upload"
        session = client.post("/api/sessions", json={
            "title": "auth-stack-session", "project_id": pid,
        }).json()["data"]
        stream = client.post("/api/chat/attach", json={"session_id": session["id"]})
        assert stream.status_code == 200
        assert "text/event-stream" in stream.headers["content-type"]
        assert b'"done"' in stream.content and b"\n\n" in stream.content
        assert "content-encoding" not in stream.headers
        page = client.get("/")
        assert "private-auth-stack-project" in page.text
        assert PASSWORD not in page.text
        if enabled:
            # Alternating visitors in parallel must not share SSR credentials.
            with httpx.Client(base_url=client.base_url, trust_env=False) as anonymous:
                def visit(i):
                    visitor = client if i % 2 else anonymous
                    response = visitor.get("/")
                    assert response.status_code == (200 if i % 2 else 302)
                    assert ("private-auth-stack-project" in response.text) is bool(i % 2)

                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(visit, range(16)))
                assert anonymous.get(path + "/raw/auth-check.txt").status_code == 401
                assert anonymous.post("/api/chat/attach", json={"session_id": session["id"]}).status_code == 401
        assert client.delete(f"/api/sessions/{session['id']}").status_code == 200
    finally:
        assert client.delete(f"/api/projects/{pid}").status_code == 200
    if enabled:
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/").status_code == 302
        assert client.get("/api/projects").status_code == 401
