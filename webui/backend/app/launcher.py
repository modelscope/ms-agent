"""Run FastAPI and the built Node frontend with one supervisor and public URL."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from app.frontend import BuildError, sha256, validate_build
from app.processes import ProcessError, _spawn, _terminate_process_tree, interruptible

REPO_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_DIR / "frontend"
DEFAULT_PORT = 8000
PORT_SPAN = 32
READY_TIMEOUT_S = 120.0
MIN_NODE_VERSION = (22, 22, 0)
_LOOPBACK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class LaunchError(RuntimeError):
    pass


def port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _port_in_use(host: str, port: int) -> bool:
    for family, socktype, proto, _canon, addr in socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    ):
        with socket.socket(family, socktype, proto) as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(addr)
            except OSError:
                return True
    return False


def _choose_port(
    host: str, explicit: int | None, preferred: int, label: str, exclude: set[int]
) -> int:
    if explicit is not None:
        if explicit in exclude:
            raise LaunchError("The frontend and backend ports must be different")
        if _port_in_use(host, explicit):
            raise LaunchError(f"{label} port {explicit} is already in use on {host}")
        return explicit
    if preferred > 65535:
        preferred = DEFAULT_PORT
    for port in range(preferred, min(65536, preferred + PORT_SPAN)):
        if port not in exclude and not _port_in_use(host, port):
            return port
    raise LaunchError(
        f"No free {label} port near {preferred}; specify --port / --backend-port"
    )


def select_ports(host: str, public: int | None, backend: int | None) -> tuple[int, int]:
    public = _choose_port(
        host,
        public,
        DEFAULT_PORT,
        "frontend",
        {backend} if backend is not None else set(),
    )
    backend = _choose_port("127.0.0.1", backend, public + 1, "backend", {public})
    return public, backend


def public_url(host: str, port: int) -> str:
    host = host.strip().removeprefix("[").removesuffix("]")
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    display = f"[{host}]" if ":" in host else host
    return f"http://{display}:{port}"


def _require_node() -> str:
    node = shutil.which("node")
    if not node:
        raise LaunchError("Node.js >=22.22.0 is required to run the WebUI")
    result = subprocess.run(
        [node, "--version"], capture_output=True, text=True, check=True, timeout=10
    )
    match = re.search(r"(?m)^v(\d+)\.(\d+)\.(\d+)", result.stdout)
    if not match or tuple(map(int, match.groups())) < MIN_NODE_VERSION:
        raise LaunchError(
            f"Node.js >=22.22.0 is required; found {result.stdout.strip()} at {node}"
        )
    return node


def _check_children(processes) -> None:
    for label, process in processes:
        code = process.poll()
        if code is not None:
            raise LaunchError(f"{label} exited unexpectedly (exit code {code})")


def _wait_for_http(
    url: str, processes, deadline: float, *, kind: str, expected: str | None = None
) -> None:
    last_error = "not ready"
    while time.monotonic() < deadline:
        _check_children(processes)
        try:
            with _LOOPBACK_OPENER.open(url, timeout=2) as response:
                content = response.read()
                valid = response.status == 200
                if kind == "health":
                    payload = json.loads(content)
                    valid = valid and isinstance(payload, dict) and payload.get("status") == "ok"
                elif kind == "css":
                    valid = (
                        valid
                        and "text/css" in response.headers.get("Content-Type", "")
                        and hashlib.sha256(content).hexdigest() == expected
                    )
                else:
                    valid = valid and expected.encode() in content
                if valid:
                    return
                last_error = f"unexpected {kind} response"
        except (OSError, urllib.error.URLError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise LaunchError(f"Timed out waiting for {kind} at {url}: {last_error}")


def _run_api() -> None:
    class BannerFilter(logging.Filter):
        def filter(self, record):
            return "Uvicorn running on" not in record.getMessage()

    logging.getLogger("uvicorn.error").addFilter(BannerFilter())
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=int(os.environ["PORT"]),
        timeout_graceful_shutdown=5,
    )


def _check_traced_tree(frontend: Path) -> None:
    """Reject a `pnpm build:image` tree that no longer matches the checkout.

    Such a tree is a copy of `build/` next to a traced `node_modules`, and it has no
    `app/` — so `validate_build` skips the source comparison and finds the copied
    manifest agreeing with the copied outputs, which it always will. Editing a
    component, rebuilding, and forgetting to re-trace would then serve the previous
    UI with every check green. The checkout's manifest is the second opinion, and it
    is only consulted when it exists: the image ships the traced tree alone.
    """
    if frontend == FRONTEND_DIR or (frontend / "app").is_dir():
        return
    manifest = FRONTEND_DIR / "build/webui-build.json"
    traced = frontend / "build/webui-build.json"
    if not manifest.is_file() or not traced.is_file():
        return
    if sha256(manifest) != sha256(traced):
        raise BuildError(
            f"{frontend} was traced from a different build than {FRONTEND_DIR}/build"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the MS-Agent WebUI on one public port"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=port_number,
        help="Public port; by default choose a free port from 8000",
    )
    parser.add_argument(
        "--backend-port",
        type=port_number,
        help="Internal loopback port; by default choose the next free port",
    )
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument(
        "--frontend-dir",
        type=Path,
        default=FRONTEND_DIR,
        help="Frontend tree to serve; pass frontend/build-runtime to run what the "
        "image ships instead of the checkout (see `pnpm build:image`)",
    )
    parser.add_argument("--startup-timeout", type=float, default=READY_TIMEOUT_S)
    args = parser.parse_args(argv)
    if not math.isfinite(args.startup_timeout) or args.startup_timeout <= 0:
        parser.error("--startup-timeout must be positive and finite")
    host = args.host.strip().removeprefix("[").removesuffix("]")
    if not host:
        parser.error("--host cannot be empty")
    frontend = Path(args.frontend_dir).expanduser().resolve()
    processes = []
    exit_code = 0
    with interruptible():
        try:
            public, backend = select_ports(host, args.port, args.backend_port)
            # A traced tree carries no `app/`, so validate_build cannot tell whether
            # it still matches the sources — it only sees its own copied manifest and
            # calls itself consistent. Compare the two manifests while the checkout is
            # next door, or an edited component would be served from a stale copy with
            # every check passing.
            _check_traced_tree(frontend)
            css_href = validate_build(
                frontend, check_sources=(frontend / "app").is_dir()
            )
            node = _require_node()
            # Load source dotenv before copying the child environment; installed
            # mode disables dotenv discovery outside a checkout.
            from app.core import settings as _settings  # noqa: F401

            env = os.environ.copy()
            env.update(
                PYTHONUTF8="1",
                PYTHONIOENCODING="utf-8",
                HOST="127.0.0.1",
                PORT=str(backend),
            )
            deadline = time.monotonic() + args.startup_timeout
            api_url = f"http://127.0.0.1:{backend}"
            processes.append(
                (
                    "backend",
                    _spawn(
                        [
                            sys.executable,
                            "-c",
                            "from app.launcher import _run_api; _run_api()",
                        ],
                        cwd=REPO_DIR / "backend",
                        env=env,
                    ),
                )
            )
            _wait_for_http(api_url + "/api/health", processes, deadline, kind="health")
            env.update(
                HOST=host,
                PORT=str(public),
                NODE_ENV="production",
                MS_AGENT_WEBUI_BANNER="0",
                MS_AGENT_API_BASE_URL=api_url,
                MS_AGENT_FRONTEND_API_BASE_URL=api_url,
            )
            processes.append(
                (
                    "frontend",
                    _spawn(
                        [node, str(frontend / "server.js")],
                        cwd=frontend,
                        env=env,
                    ),
                )
            )
            url = public_url(host, public)
            _wait_for_http(url + "/api/health", processes, deadline, kind="health")
            _wait_for_http(
                url + "/", processes, deadline, kind="page", expected=css_href
            )
            _wait_for_http(
                url + css_href,
                processes,
                deadline,
                kind="css",
                expected=sha256(frontend / "build/client" / css_href.lstrip("/")),
            )
            _check_children(processes)
            print(f"\nMS-Agent WebUI ready: {url}\n", flush=True)
            if not args.no_open:
                try:
                    webbrowser.open(url)
                except (OSError, webbrowser.Error):
                    print(f"Open {url} in your browser", file=sys.stderr)
            while True:
                _check_children(processes)
                time.sleep(0.25)
        except KeyboardInterrupt:
            print("\nStopping WebUI...", flush=True)
        except (
            LaunchError,
            BuildError,
            ProcessError,
            OSError,
            subprocess.SubprocessError,
        ) as exc:
            print(f"Cannot start WebUI: {exc}", file=sys.stderr, flush=True)
            if isinstance(exc, BuildError):
                hint = "build:image" if frontend != FRONTEND_DIR else "build"
                print(f"Run `pnpm {hint}` in {FRONTEND_DIR}", file=sys.stderr)
            exit_code = 1
        finally:
            for _label, process in reversed(processes):
                _terminate_process_tree(process)
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
