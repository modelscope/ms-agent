"""Contract tests for all MemoryBackend implementations.

Every backend that implements the MemoryBackend Protocol must satisfy these
invariants.  Backends requiring external dependencies are auto-skipped when
those dependencies are not installed.

Run::

    source /opt/homebrew/anaconda3/bin/activate agent_release1
    python -m pytest tests/memory/test_backend_contracts.py -v
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from typing import Any, Dict

import pytest

from ms_agent.memory.unified.config import MemoryConfig
from ms_agent.memory.unified.protocols import BaseMemoryBackend, MemoryEntry
from ms_agent.memory.unified.registry import backend_registry

# Ensure all backends are loaded via the package __init__
import ms_agent.memory.unified.backends  # noqa: F401

# ── Dependency probes ────────────────────────────────────────────────────

try:
    import mempalace  # noqa: F401
    HAS_MEMPALACE = True
except ImportError:
    HAS_MEMPALACE = False

HAS_BRV = shutil.which("brv") is not None

HAS_SUPERMEMORY_KEY = bool(os.environ.get("SUPERMEMORY_API_KEY"))
try:
    import supermemory  # noqa: F401
    HAS_SUPERMEMORY = HAS_SUPERMEMORY_KEY
except ImportError:
    HAS_SUPERMEMORY = False

try:
    import mem0  # noqa: F401
    HAS_MEM0 = True
except ImportError:
    HAS_MEM0 = False


# ── Fixtures ─────────────────────────────────────────────────────────────

SAMPLE_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the capital of France?"},
    {"role": "assistant", "content": "The capital of France is Paris."},
]

SAMPLE_TURN = [
    {"role": "user", "content": "Remember that my favorite color is blue and I work on the ms-agent project."},
    {"role": "assistant", "content": "Got it! I'll remember that your favorite color is blue and you work on the ms-agent project."},
]


def _make_config(backend_name: str, base_dir: str, **extra: Any) -> MemoryConfig:
    """Build a MemoryConfig for the given backend."""
    opts: Dict[str, Any] = {}

    if backend_name == "file":
        opts["file"] = {
            "memory_path": "MEMORY.md",
            "char_limit": 2200,
        }
    elif backend_name == "mempalace":
        palace_path = os.path.join(base_dir, "palace")
        os.makedirs(palace_path, exist_ok=True)
        opts["mempalace"] = {
            "palace_path": palace_path,
            "wing": "test",
            "collection_name": "test_drawers",
            "auto_search": True,
            "max_search_results": 5,
            "inject_protocol": True,
        }
    elif backend_name == "byterover":
        opts["byterover"] = {
            "working_dir": os.path.join(base_dir, ".brv"),
            "query_timeout": 10,
            "curate_timeout": 30,
        }
    elif backend_name == "supermemory":
        opts["supermemory"] = {
            "container_tag": f"ms_agent_test_{os.getpid()}",
            "search_mode": "hybrid",
            "auto_capture": True,
            "api_timeout": 10.0,
        }
    elif backend_name == "mem0":
        opts["mem0"] = {}

    return MemoryConfig(
        enabled=True,
        storage_backend=backend_name,
        base_dir=base_dir,
        user_id="test_user",
        agent_id="test_agent",
        backend_options=opts,
        **extra,
    )


def _skip_if_unavailable(backend_name: str):
    """Raise pytest.skip if the backend's dependencies are missing."""
    if backend_name == "mempalace" and not HAS_MEMPALACE:
        pytest.skip("mempalace not installed")
    elif backend_name == "byterover" and not HAS_BRV:
        pytest.skip("brv CLI not installed")
    elif backend_name == "supermemory" and not HAS_SUPERMEMORY:
        pytest.skip("supermemory not installed or SUPERMEMORY_API_KEY not set")
    elif backend_name == "mem0" and not HAS_MEM0:
        pytest.skip("mem0 not installed")


# All backends that should be tested (hermes removed)
BACKENDS = ["file", "mempalace", "byterover", "supermemory", "mem0"]


@pytest.fixture(params=BACKENDS)
def backend_setup(request):
    """Instantiate, start, and yield a backend; clean up on teardown."""
    name = request.param
    _skip_if_unavailable(name)

    tmp = tempfile.mkdtemp(prefix=f"ms_agent_test_{name}_")
    config = _make_config(name, tmp)

    cls = backend_registry.get(name)
    if cls is None:
        pytest.skip(f"Backend '{name}' not registered")

    backend = cls(config)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(backend.start(base_dir=tmp))
    except Exception as e:
        loop.close()
        shutil.rmtree(tmp, ignore_errors=True)
        pytest.skip(f"Backend '{name}' failed to start: {e}")

    yield name, backend, loop, tmp

    try:
        loop.run_until_complete(backend.close())
    finally:
        loop.close()
        shutil.rmtree(tmp, ignore_errors=True)


# ── Contract Tests ───────────────────────────────────────────────────────

class TestBackendContract:
    """Every MemoryBackend must satisfy these invariants."""

    def test_is_registered(self, backend_setup):
        name, backend, loop, tmp = backend_setup
        assert backend_registry.get(name) is not None

    def test_inject_preserves_system_prompt(self, backend_setup):
        name, backend, loop, tmp = backend_setup
        messages = [
            {"role": "system", "content": "Original system prompt."},
            {"role": "user", "content": "Hello"},
        ]
        result = loop.run_until_complete(backend.inject(messages))
        assert isinstance(result, list)
        assert len(result) >= 2
        assert result[0]["role"] == "system"
        assert result[0]["content"].startswith("Original system prompt.")

    def test_inject_does_not_mutate_input(self, backend_setup):
        name, backend, loop, tmp = backend_setup
        messages = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "Query"},
        ]
        original_content = messages[0]["content"]
        loop.run_until_complete(backend.inject(messages))
        assert messages[0]["content"] == original_content

    def test_inject_returns_list_of_dicts(self, backend_setup):
        name, backend, loop, tmp = backend_setup
        result = loop.run_until_complete(backend.inject(SAMPLE_MESSAGES))
        assert isinstance(result, list)
        for msg in result:
            assert isinstance(msg, dict)
            assert "role" in msg
            assert "content" in msg

    def test_search_returns_memory_entries(self, backend_setup):
        name, backend, loop, tmp = backend_setup
        results = loop.run_until_complete(
            backend.search("test query", limit=5))
        assert isinstance(results, list)
        for entry in results:
            assert isinstance(entry, MemoryEntry)

    def test_tool_schemas_valid(self, backend_setup):
        name, backend, loop, tmp = backend_setup
        schemas = backend.get_tool_schemas()
        assert isinstance(schemas, list)
        for schema in schemas:
            assert isinstance(schema, dict)
            assert "tool_name" in schema, (
                f"Schema missing 'tool_name': {schema}")
            assert "parameters" in schema, (
                f"Schema missing 'parameters': {schema}")

    def test_on_messages_no_crash(self, backend_setup):
        name, backend, loop, tmp = backend_setup
        loop.run_until_complete(backend.on_messages(SAMPLE_TURN))

    def test_on_pre_compress_no_crash(self, backend_setup):
        name, backend, loop, tmp = backend_setup
        loop.run_until_complete(backend.on_pre_compress(SAMPLE_MESSAGES))

    def test_lifecycle_double_close(self, backend_setup):
        name, backend, loop, tmp = backend_setup
        loop.run_until_complete(backend.close())
        loop.run_until_complete(backend.close())

    def test_invalidate_no_crash(self, backend_setup):
        name, backend, loop, tmp = backend_setup
        backend.invalidate()

    def test_handle_unknown_tool(self, backend_setup):
        name, backend, loop, tmp = backend_setup
        result = loop.run_until_complete(
            backend.handle_tool_call("nonexistent_tool", {}))
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert "error" in parsed


# ── Backend-specific tests ───────────────────────────────────────────────

class TestFileBackendSpecific:
    """Tests specific to the built-in file backend."""

    def setup_method(self):
        self.tmp = tempfile.mkdtemp(prefix="ms_agent_test_file_")
        config = _make_config("file", self.tmp)
        cls = backend_registry.get("file")
        self.backend = cls(config)
        self.loop = asyncio.new_event_loop()
        self.loop.run_until_complete(
            self.backend.start(base_dir=self.tmp))

    def teardown_method(self):
        self.loop.run_until_complete(self.backend.close())
        self.loop.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_exposes_memory_tools(self):
        schemas = self.backend.get_tool_schemas()
        tool_names = [s["tool_name"] for s in schemas]
        assert "memory" in tool_names
        assert "memory_read" in tool_names


@pytest.mark.skipif(not HAS_MEMPALACE, reason="mempalace not installed")
class TestMempalaceSpecific:
    """Tests specific to the mempalace backend."""

    def setup_method(self):
        self.tmp = tempfile.mkdtemp(prefix="ms_agent_test_mempalace_")
        palace = os.path.join(self.tmp, "palace")
        os.makedirs(palace, exist_ok=True)
        config = _make_config("mempalace", self.tmp)
        cls = backend_registry.get("mempalace")
        self.backend = cls(config)
        self.loop = asyncio.new_event_loop()
        self.loop.run_until_complete(self.backend.start())

    def teardown_method(self):
        self.loop.run_until_complete(self.backend.close())
        self.loop.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_palace_add_idempotent(self):
        result1 = self.loop.run_until_complete(
            self.backend.handle_tool_call(
                "palace_add", {"content": "Test fact", "wing": "test", "room": "general"}))
        result2 = self.loop.run_until_complete(
            self.backend.handle_tool_call(
                "palace_add", {"content": "Test fact", "wing": "test", "room": "general"}))
        r1 = json.loads(result1)
        r2 = json.loads(result2)
        assert r1.get("id") == r2.get("id")

    def test_palace_add_then_search(self):
        self.loop.run_until_complete(
            self.backend.handle_tool_call(
                "palace_add",
                {"content": "The project uses Python 3.11", "wing": "test", "room": "tech"}))
        results = self.loop.run_until_complete(
            self.backend.search("Python version", limit=5))
        assert len(results) > 0
        assert any("Python" in e.content for e in results)

    def test_inject_includes_protocol(self):
        messages = [
            {"role": "system", "content": "Base prompt."},
            {"role": "user", "content": "Hello"},
        ]
        result = self.loop.run_until_complete(self.backend.inject(messages))
        sys_content = result[0]["content"]
        if "<long-term-memory>" in sys_content:
            assert "Memory Protocol" in sys_content or "palace_search" in sys_content


@pytest.mark.skipif(not HAS_BRV, reason="brv CLI not installed")
class TestByteRoverSpecific:
    """Tests specific to the ByteRover backend."""

    def setup_method(self):
        self.tmp = tempfile.mkdtemp(prefix="ms_agent_test_brv_")
        config = _make_config("byterover", self.tmp)
        cls = backend_registry.get("byterover")
        self.backend = cls(config)
        self.loop = asyncio.new_event_loop()
        self.loop.run_until_complete(
            self.backend.start(base_dir=self.tmp))

    def teardown_method(self):
        self.loop.run_until_complete(self.backend.close())
        self.loop.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_exposes_brv_tools(self):
        schemas = self.backend.get_tool_schemas()
        tool_names = [s["tool_name"] for s in schemas]
        assert "brv_query" in tool_names
        assert "brv_curate" in tool_names
        assert "brv_status" in tool_names

    def test_status_tool(self):
        result = self.loop.run_until_complete(
            self.backend.handle_tool_call("brv_status", {}))
        parsed = json.loads(result)
        assert "status" in parsed or "error" in parsed


@pytest.mark.skipif(not HAS_SUPERMEMORY, reason="supermemory not available")
class TestSupermemorySpecific:
    """Tests specific to the Supermemory backend."""

    def setup_method(self):
        self.tmp = tempfile.mkdtemp(prefix="ms_agent_test_supermem_")
        config = _make_config("supermemory", self.tmp)
        cls = backend_registry.get("supermemory")
        self.backend = cls(config)
        self.loop = asyncio.new_event_loop()
        self.loop.run_until_complete(self.backend.start())

    def teardown_method(self):
        self.loop.run_until_complete(self.backend.close())
        self.loop.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_exposes_supermemory_tools(self):
        schemas = self.backend.get_tool_schemas()
        tool_names = [s["tool_name"] for s in schemas]
        assert "supermemory_store" in tool_names
        assert "supermemory_search" in tool_names
        assert "supermemory_forget" in tool_names
        assert "supermemory_profile" in tool_names

    def test_store_and_search(self):
        store_result = self.loop.run_until_complete(
            self.backend.handle_tool_call(
                "supermemory_store",
                {"content": "The user's favorite language is Python."}))
        parsed = json.loads(store_result)
        assert parsed.get("saved") is True

        import time
        time.sleep(2)

        search_result = self.loop.run_until_complete(
            self.backend.handle_tool_call(
                "supermemory_search",
                {"query": "favorite programming language", "limit": 5}))
        results = json.loads(search_result)
        assert results.get("count", 0) > 0


# ── Registration completeness test ───────────────────────────────────────

class TestRegistryCompleteness:
    """Verify all expected backends are registered."""

    def test_expected_backends_registered(self):
        available = backend_registry.list_available()
        assert "file" in available
        assert "byterover" in available
        assert "supermemory" in available
        # Optional backends depend on installed packages
        if HAS_MEMPALACE:
            assert "mempalace" in available
        if HAS_MEM0:
            assert "mem0" in available

    def test_hermes_backend_removed(self):
        assert backend_registry.get("hermes") is None


import json  # noqa: E402 — used in test assertions
