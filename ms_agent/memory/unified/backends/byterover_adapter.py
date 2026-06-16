"""ByteRoverBackend — adapter for the ByteRover CLI context tree.

Persistent memory via the ``brv`` CLI. Organizes knowledge into a
hierarchical context tree with tiered retrieval (fuzzy text -> LLM-driven
search). Local-first with optional cloud sync.

Requires: ``brv`` CLI installed::

    npm install -g byterover-cli
    # or
    curl -fsSL https://byterover.dev/install.sh | sh

Configuration::

    memory:
      unified_memory:
        storage:
          backend: "byterover"
        byterover:
          working_dir: ".brv"
          query_timeout: 10
          curate_timeout: 120
          min_query_length: 10
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import MemoryConfig
from ..protocols import BaseMemoryBackend, MemoryEntry
from ..registry import backend_registry

logger = logging.getLogger(__name__)

_QUERY_TIMEOUT = 10
_CURATE_TIMEOUT = 120
_MIN_QUERY_LEN = 10
_MIN_OUTPUT_LEN = 20

# Thread-safe binary path caching
_brv_path_lock = threading.Lock()
_cached_brv_path: Optional[str] = None


def _resolve_brv_path() -> Optional[str]:
    """Find the brv binary on PATH or well-known install locations."""
    global _cached_brv_path
    with _brv_path_lock:
        if _cached_brv_path is not None:
            return _cached_brv_path if _cached_brv_path != "" else None

    found = shutil.which("brv")
    if not found:
        home = Path.home()
        candidates = [
            home / ".brv-cli" / "bin" / "brv",
            Path("/usr/local/bin/brv"),
            home / ".npm-global" / "bin" / "brv",
        ]
        for c in candidates:
            if c.exists():
                found = str(c)
                break

    with _brv_path_lock:
        if _cached_brv_path is not None:
            return _cached_brv_path if _cached_brv_path != "" else None
        _cached_brv_path = found or ""
    return found


def _run_brv(
    args: List[str],
    timeout: int = _QUERY_TIMEOUT,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a brv CLI command.  Returns ``{success, output, error}``."""
    brv_path = _resolve_brv_path()
    if not brv_path:
        return {
            "success": False,
            "error": "brv CLI not found. Install: npm install -g byterover-cli",
        }

    cmd = [brv_path] + args
    if cwd:
        Path(cwd).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    brv_bin_dir = str(Path(brv_path).parent)
    env["PATH"] = brv_bin_dir + os.pathsep + env.get("PATH", "")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=cwd, env=env,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode == 0:
            return {"success": True, "output": stdout}
        return {
            "success": False,
            "error": stderr or stdout or f"brv exited {result.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"brv timed out after {timeout}s"}
    except FileNotFoundError:
        with _brv_path_lock:
            global _cached_brv_path
            _cached_brv_path = None
        return {"success": False, "error": "brv CLI not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# -- Tool schemas ----------------------------------------------------------

_QUERY_SCHEMA = {
    "tool_name": "brv_query",
    "description": (
        "Search ByteRover's persistent knowledge tree for relevant context. "
        "Returns memories, project knowledge, architectural decisions, and "
        "patterns from previous sessions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for.",
            },
        },
        "required": ["query"],
    },
}

_CURATE_SCHEMA = {
    "tool_name": "brv_curate",
    "description": (
        "Store important information in ByteRover's persistent knowledge tree. "
        "Use for architectural decisions, bug fixes, user preferences, project "
        "patterns — anything worth remembering across sessions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The information to remember.",
            },
        },
        "required": ["content"],
    },
}

_STATUS_SCHEMA = {
    "tool_name": "brv_status",
    "description": (
        "Check ByteRover status: CLI version, context tree stats, "
        "cloud sync state."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}


class ByteRoverBackend(BaseMemoryBackend):
    """MemoryBackend adapter for the ByteRover CLI.

    Maps MemoryBackend methods to ``brv`` CLI commands:
    - inject()          -> brv query -> inject results
    - on_messages()     -> brv curate (background)
    - on_pre_compress() -> brv curate (synchronous flush)
    - tools             -> brv_query, brv_curate, brv_status
    """

    def __init__(self, config: MemoryConfig) -> None:
        self._config = config
        opts = config.backend_options.get("byterover", {})
        self._working_dir = opts.get("working_dir", ".brv")
        self._query_timeout = opts.get("query_timeout", _QUERY_TIMEOUT)
        self._curate_timeout = opts.get("curate_timeout", _CURATE_TIMEOUT)
        self._min_query_len = opts.get("min_query_length", _MIN_QUERY_LEN)
        self._cwd: Optional[str] = None
        self._sync_thread: Optional[threading.Thread] = None
        self._available = False

    # -- Lifecycle ---------------------------------------------------------

    async def start(self, **kwargs: Any) -> None:
        base = kwargs.get("base_dir", self._config.base_dir)
        self._cwd = str(Path(base) / self._working_dir)
        Path(self._cwd).mkdir(parents=True, exist_ok=True)

        if _resolve_brv_path() is None:
            logger.warning(
                "[byterover_backend] brv CLI not found. "
                "Install: npm install -g byterover-cli")
            return

        result = _run_brv(["status"], timeout=15, cwd=self._cwd)
        if result["success"]:
            self._available = True
            logger.info("[byterover_backend] brv initialized at %s", self._cwd)
        else:
            logger.warning(
                "[byterover_backend] brv status check failed: %s",
                result.get("error"))

    async def close(self) -> None:
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=10.0)

    # -- inject ------------------------------------------------------------

    async def inject(
        self, messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not self._available:
            return messages

        query = self._extract_last_user_content(messages)
        if not query or len(query.strip()) < self._min_query_len:
            return messages

        result = _run_brv(
            ["query", "--", query.strip()[:5000]],
            timeout=self._query_timeout, cwd=self._cwd,
        )

        if not result["success"] or not result.get("output"):
            return messages

        output = result["output"].strip()
        if len(output) < _MIN_OUTPUT_LEN:
            return messages

        if len(output) > 8000:
            output = output[:8000] + "\n\n[... truncated]"

        messages = list(messages)

        # Inject into system prompt
        if messages and messages[0].get("role") == "system":
            sys_msg = {**messages[0]}
            block = (
                "\n\n<long-term-memory>\n"
                "# ByteRover Context\n"
                f"{output}\n"
                "</long-term-memory>"
            )
            if "<long-term-memory>" not in (sys_msg.get("content") or ""):
                sys_msg["content"] = (sys_msg.get("content") or "") + block
                messages[0] = sys_msg

        return messages

    # -- on_messages -------------------------------------------------------

    async def on_messages(
        self, messages: List[Dict[str, Any]], **kwargs: Any,
    ) -> None:
        if not self._available:
            return

        user_content = ""
        assistant_content = ""
        for m in messages:
            if m.get("role") == "user":
                user_content = str(m.get("content", ""))
            elif m.get("role") == "assistant":
                assistant_content = str(m.get("content", ""))

        if len(user_content.strip()) < self._min_query_len:
            return

        combined = (
            f"User: {user_content[:2000]}\n"
            f"Assistant: {assistant_content[:2000]}"
        )
        self._background_curate(combined)

    # -- on_pre_compress ---------------------------------------------------

    async def on_pre_compress(
        self, messages: List[Dict[str, Any]],
    ) -> None:
        if not self._available or not messages:
            return

        parts = []
        for msg in messages[-10:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip() and role in ("user", "assistant"):
                parts.append(f"{role}: {content[:500]}")

        if not parts:
            return

        combined = "\n".join(parts)
        self._background_curate(
            f"[Pre-compression context]\n{combined}",
            wait=True,
        )

    # -- Tools -------------------------------------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        if not self._available:
            return []
        return [_QUERY_SCHEMA, _CURATE_SCHEMA, _STATUS_SCHEMA]

    async def handle_tool_call(
        self, tool_name: str, arguments: Dict[str, Any],
    ) -> str:
        if tool_name == "brv_query":
            return self._tool_query(arguments)
        elif tool_name == "brv_curate":
            return self._tool_curate(arguments)
        elif tool_name == "brv_status":
            return self._tool_status()
        return json.dumps({"error": f"unknown tool: {tool_name}"})

    # -- Search ------------------------------------------------------------

    async def search(
        self, query: str, limit: int = 10,
    ) -> List[MemoryEntry]:
        if not self._available or not query:
            return []

        result = _run_brv(
            ["query", "--", query.strip()[:5000]],
            timeout=self._query_timeout, cwd=self._cwd,
        )

        if not result["success"] or not result.get("output"):
            return []

        output = result["output"].strip()
        if len(output) < _MIN_OUTPUT_LEN:
            return []

        return [MemoryEntry(content=output, source="byterover")]

    # -- Cache -------------------------------------------------------------

    def invalidate(self) -> None:
        pass

    # -- Internal helpers --------------------------------------------------

    @staticmethod
    def _extract_last_user_content(
        messages: List[Dict[str, Any]],
    ) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content", "")
                return str(content)[:200] if content else ""
        return ""

    def _background_curate(self, content: str, wait: bool = False) -> None:
        """Run ``brv curate`` in a background thread."""
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)

        def _curate():
            try:
                _run_brv(
                    ["curate", "--", content],
                    timeout=self._curate_timeout, cwd=self._cwd,
                )
            except Exception as e:
                logger.debug("[byterover_backend] curate failed: %s", e)

        self._sync_thread = threading.Thread(
            target=_curate, daemon=True, name="brv-curate")
        self._sync_thread.start()

        if wait:
            self._sync_thread.join(timeout=float(self._curate_timeout))

    def _tool_query(self, args: Dict[str, Any]) -> str:
        query = args.get("query", "")
        if not query:
            return json.dumps({"error": "query is required"})

        result = _run_brv(
            ["query", "--", query.strip()[:5000]],
            timeout=self._query_timeout, cwd=self._cwd,
        )

        if not result["success"]:
            return json.dumps({"error": result.get("error", "Query failed")})

        output = result.get("output", "").strip()
        if not output or len(output) < _MIN_OUTPUT_LEN:
            return json.dumps({"result": "No relevant memories found."})

        if len(output) > 8000:
            output = output[:8000] + "\n\n[... truncated]"

        return json.dumps({"result": output})

    def _tool_curate(self, args: Dict[str, Any]) -> str:
        content = args.get("content", "")
        if not content:
            return json.dumps({"error": "content is required"})

        result = _run_brv(
            ["curate", "--", content],
            timeout=self._curate_timeout, cwd=self._cwd,
        )

        if not result["success"]:
            return json.dumps({"error": result.get("error", "Curate failed")})

        return json.dumps({"result": "Memory curated successfully."})

    def _tool_status(self) -> str:
        result = _run_brv(["status"], timeout=15, cwd=self._cwd)
        if not result["success"]:
            return json.dumps(
                {"error": result.get("error", "Status check failed")})
        return json.dumps({"status": result.get("output", "")})


# -- Self-register ---------------------------------------------------------

backend_registry.register("byterover", ByteRoverBackend)
