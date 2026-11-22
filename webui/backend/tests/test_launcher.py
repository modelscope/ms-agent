"""Port, build and readiness regressions for every WebUI launch entry."""

import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app import launcher
from app.frontend import BuildError, validate_build
from app.processes import _spawn, _terminate_process_tree


@pytest.mark.parametrize("value", ["0", "-1", "65536", "abc"])
def test_invalid_port_fails_before_preparation(value):
    with pytest.raises(SystemExit) as error:
        launcher.main(["--port", value])
    assert error.value.code == 2


def test_explicit_busy_port_fails():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(launcher.LaunchError, match="already in use"):
            launcher.select_ports("127.0.0.1", listener.getsockname()[1], None)


def test_default_ports_skip_busy_ports_and_explicit_backend(monkeypatch):
    monkeypatch.setattr(launcher, "_port_in_use", lambda host, port: port == 8001)
    assert launcher.select_ports("127.0.0.1", None, 8000) == (8002, 8000)
    assert launcher.select_ports("127.0.0.1", None, None) == (8000, 8002)


def test_same_explicit_ports_are_rejected(monkeypatch):
    monkeypatch.setattr(launcher, "_port_in_use", lambda *args: False)
    with pytest.raises(launcher.LaunchError, match="different"):
        launcher.select_ports("127.0.0.1", 9000, 9000)


def test_upper_port_boundary_does_not_overflow(monkeypatch):
    monkeypatch.setattr(launcher, "_port_in_use", lambda *args: False)
    assert launcher.select_ports("127.0.0.1", 65535, None) == (65535, 8000)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("0.0.0.0", "http://127.0.0.1:8000"),
        ("::", "http://[::1]:8000"),
        ("[::1]", "http://[::1]:8000"),
        ("2001:db8::1", "http://[2001:db8::1]:8000"),
    ],
)
def test_public_url(host, expected):
    assert launcher.public_url(host, 8000) == expected


def _record_build_manifest(cwd):
    """Run the real producer of build/webui-build.json, so the Python validator is
    always checked against the script `pnpm build` actually uses. It is TypeScript,
    so it goes through the frontend's own tsx; both paths are absolute because the
    manifest is recorded with `cwd` set to the frontend being described."""
    tsx = Path(launcher.FRONTEND_DIR) / "node_modules/.bin/tsx"
    script = Path(launcher.FRONTEND_DIR) / "scripts/buildManifest.ts"
    subprocess.run([str(tsx), str(script)], cwd=cwd, check=True)


@pytest.fixture
def built_frontend(tmp_path):
    frontend = tmp_path / "frontend"
    files = {
        "server.js": "// server",
        "package.json": "{}",
        "app/root.tsx": "// app",
        "build/server/index.js": "// built SSR",
        "build/client/assets/antd.test.css": "body { color: black; }",
        "build/client/antd/manifest.json": json.dumps(
            {"href": "/assets/antd.test.css"}
        ),
    }
    for rel, content in files.items():
        target = frontend / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    _record_build_manifest(frontend)
    return frontend


def test_build_manifest_matches_node_producer(built_frontend):
    assert validate_build(built_frontend) == "/assets/antd.test.css"


def test_runtime_cache_marker_is_not_a_frontend_source(built_frontend):
    marker = built_frontend / ".node-dependencies.json"
    marker.write_text('{"production": true}')
    assert validate_build(built_frontend) == "/assets/antd.test.css"
    _record_build_manifest(built_frontend)
    manifest = json.loads((built_frontend / "build/webui-build.json").read_text())
    assert marker.name not in manifest["inputs"]
    marker.write_text('{"production": false}')
    assert validate_build(built_frontend) == "/assets/antd.test.css"


@pytest.mark.parametrize("change", ["added", "modified", "removed"])
def test_changed_source_requires_rebuild(built_frontend, change):
    if change == "added":
        (built_frontend / "app/new.ts").write_text("// new")
    elif change == "modified":
        (built_frontend / "app/root.tsx").write_text("// changed")
    else:
        (built_frontend / "app/root.tsx").unlink()
    with pytest.raises(BuildError, match="sources changed"):
        validate_build(built_frontend)


@pytest.mark.parametrize(
    "rel",
    [
        "build/client/assets/antd.test.css",
        "build/client/antd/manifest.json",
        "build/server/index.js",
        "build/webui-build.json",
    ],
)
def test_missing_build_resources_fail(built_frontend, rel):
    (built_frontend / rel).unlink()
    with pytest.raises(BuildError):
        validate_build(built_frontend)


def test_changed_css_fails_even_when_sources_unchanged(built_frontend):
    (built_frontend / "build/client/assets/antd.test.css").write_text("")
    with pytest.raises(BuildError, match="output changed"):
        validate_build(built_frontend)


def _traced_copy(frontend, tmp_path):
    """What `pnpm build:image` assembles: build/ copied verbatim beside the server
    entry, with no app/ — the sources stay behind in the checkout."""
    traced = tmp_path / "build-runtime"
    shutil.copytree(frontend / "build", traced / "build")
    shutil.copyfile(frontend / "server.js", traced / "server.js")
    shutil.copyfile(frontend / "package.json", traced / "package.json")
    return traced


def test_traced_tree_serves_without_the_sources_it_was_built_from(
    built_frontend, tmp_path, monkeypatch
):
    traced = _traced_copy(built_frontend, tmp_path)
    monkeypatch.setattr(launcher, "FRONTEND_DIR", built_frontend)
    launcher._check_traced_tree(traced)
    assert validate_build(traced, check_sources=False) == "/assets/antd.test.css"


def test_traced_tree_from_an_older_build_is_rejected(
    built_frontend, tmp_path, monkeypatch
):
    traced = _traced_copy(built_frontend, tmp_path)
    (built_frontend / "app/root.tsx").write_text("// changed")
    _record_build_manifest(built_frontend)
    monkeypatch.setattr(launcher, "FRONTEND_DIR", built_frontend)
    # The blind spot this guard covers: on its own the stale copy passes, because
    # the manifest it is checked against was copied along with the outputs.
    assert validate_build(traced, check_sources=False) == "/assets/antd.test.css"
    with pytest.raises(BuildError, match="traced from a different build"):
        launcher._check_traced_tree(traced)


def test_installed_settings_do_not_load_parent_dotenv(tmp_path):
    settings_file = Path(launcher.REPO_DIR) / "backend/app/core/settings.py"
    target = tmp_path / "webui/backend/app/core/settings.py"
    target.parent.mkdir(parents=True)
    shutil.copyfile(settings_file, target)
    (tmp_path / ".env").write_text("WEBUI_TEST_UNEXPECTED_ENV=wrong\n")
    (tmp_path / "webui/backend/.env").write_text("WEBUI_TEST_UNEXPECTED_ENV=wrong\n")
    env = {**os.environ, "MS_AGENT_WEBUI_INSTALLED": "1"}
    env.pop("WEBUI_TEST_UNEXPECTED_ENV", None)
    code = (
        "import os, runpy; state=runpy.run_path(" + repr(str(target)) + "); "
        'assert not state["_ENV_FILES"]; assert "WEBUI_TEST_UNEXPECTED_ENV" not in os.environ'
    )
    subprocess.run([sys.executable, "-c", code], env=env, check=True)


def test_readiness_rejects_html_masquerading_as_css(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>fallback</html>")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # A bad proxy must not divert loopback readiness probes.
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    try:
        with pytest.raises(launcher.LaunchError, match="unexpected css response"):
            launcher._wait_for_http(
                f"http://127.0.0.1:{server.server_port}/style.css",
                [],
                time.monotonic() + 0.1,
                kind="css",
                expected=hashlib.sha256(b"<html>fallback</html>").hexdigest(),
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_child_failure_is_not_reported_as_readiness_timeout():
    child = subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"])
    child.wait(timeout=5)
    with pytest.raises(launcher.LaunchError, match=r"backend.*exit code 7"):
        launcher._wait_for_http(
            "http://127.0.0.1:1",
            [("backend", child)],
            time.monotonic() + 10,
            kind="health",
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group integration")
def test_cleanup_stops_child_and_its_descendant(tmp_path):
    pid_file = tmp_path / "child.pid"
    program = (
        "import subprocess, sys, time; from pathlib import Path; "
        'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
        f"Path({str(pid_file)!r}).write_text(str(p.pid)); time.sleep(60)"
    )
    child = _spawn([sys.executable, "-c", program], cwd=tmp_path, env=os.environ.copy())
    try:
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pid_file.exists()
        grandchild = int(pid_file.read_text())
        _terminate_process_tree(child, grace_seconds=1)
        assert child.poll() is not None
        # Linux can briefly retain a re-parented zombie; it is no longer running.
        result = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(grandchild)], capture_output=True, text=True
        )
        assert not result.stdout.strip() or result.stdout.strip().startswith("Z")
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=5)
