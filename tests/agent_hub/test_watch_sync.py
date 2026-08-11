"""Integration tests for bidirectional watch sync.

Tests run the REAL ``watch_loop`` in child processes (via multiprocessing),
make local and remote changes, wait for sync cycles, then send SIGTERM to
stop the watcher and verify results.

Scenarios covered:
    - qoder (file-per-agent + shared) with --name all: local->remote push
    - qoder all: remote->local pull
    - qwenpaw (root-per-agent) with --name all: bidirectional sync
    - qwenpaw with specific sub-agent: individual watch
    - Conflict resolution: both sides changed -> remote wins + backup
    - Multi-process concurrent watches on different repos/frameworks
    - Delete propagation: local delete -> remote, remote delete -> local
    - First sync: empty baseline -> initial push
    - No-op: nothing changed -> state unchanged
    - file-per-agent watch guard
    - Add new file locally
    - State persistence

Usage:
    python -m pytest tests/agent/test_watch_sync.py -v
"""
import multiprocessing
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import pytest

from modelscope_hub.agent._api import AgentApi
from modelscope_hub.errors import APIError
from ms_agent.agent_hub._cache import load_sync_state, save_sync_state, sync_state_file
from ms_agent.agent_hub._commands import build_spec, cmd_watch
from ms_agent.agent_hub._workspace import (
    ALL_AGENT_NAME,
    FRAMEWORK_REGISTRY,
)

from . import skip_if_server_rejects

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SERVER = os.environ.get("MODELSCOPE_ENDPOINT", "http://www.modelscope.cn")
TOKEN = os.environ.get("TOKEN", "")
AGENT_PREFIX = f"test-watch-{int(time.time())}"
REQUEST_INTERVAL = int(os.environ.get("REQUEST_INTERVAL", "8"))

# Short interval for watch loops in tests (seconds)
WATCH_INTERVAL = 5


def _wait(seconds: int = 5):
    print(f"    (waiting {seconds}s...)")
    time.sleep(seconds)


# ---------------------------------------------------------------------------
# Child process target: runs the real watch_loop
# ---------------------------------------------------------------------------

def _watch_process_target(
    server: str,
    token: str,
    data_dir: str,
    framework: str,
    agent_name: str,
    local_dir: str,
    repo_name: str,
    interval: int,
    push_only: bool = True,
):
    """Run watch_loop in a child process. Stopped by SIGTERM."""
    os.environ["MODELSCOPE_CACHE"] = data_dir

    from modelscope_hub.agent._api import AgentApi
    from ms_agent.agent_hub._watcher import watch_loop
    from ms_agent.agent_hub._workspace import FRAMEWORK_REGISTRY

    spec_cls = FRAMEWORK_REGISTRY[framework]
    spec = spec_cls(agent_name=agent_name, local_dir=Path(local_dir))
    client = AgentApi(server, token)
    username = client._openapi.get_current_username()

    watch_loop(spec, client, username, repo_name, framework, interval=interval, push_only=push_only)


# ===========================================================================
# Test case
# ===========================================================================

@pytest.mark.remote
class TestWatchSync(unittest.TestCase):
    """Integration tests for bidirectional watch sync using real watch_loop."""

    client: AgentApi = None  # type: ignore
    username: str = ""
    _data_dir: str = ""

    @classmethod
    def setUpClass(cls):
        # Point the agent cache at an isolated dir and reset the cached global
        # config singleton so cache_dir() re-reads MODELSCOPE_CACHE here. An
        # earlier test may have already resolved (and cached) a different dir;
        # the watch subprocess persists sync state under this dir, so the test
        # process must read it from the same place.
        cls._data_dir = tempfile.mkdtemp(prefix="agent_test_watch_data_")
        os.environ["MODELSCOPE_CACHE"] = cls._data_dir
        from modelscope_hub.config import set_default_config
        set_default_config(None)
        cls.client = AgentApi(SERVER, TOKEN)
        cls.username = cls.client._openapi.get_current_username()
        assert cls.username, "login failed"
        print(f"    Logged in as {cls.username}")

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("MODELSCOPE_CACHE", None)
        from modelscope_hub.config import set_default_config
        set_default_config(None)
        shutil.rmtree(cls._data_dir, ignore_errors=True)

    def setUp(self):
        time.sleep(REQUEST_INTERVAL)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------
    def _create_local(self, files: dict) -> str:
        """Write files into a temp dir, return path."""
        tmpdir = tempfile.mkdtemp(prefix="agent_test_watch_")
        for rel, content in files.items():
            fp = Path(tmpdir) / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
        return tmpdir

    def _create_local_root(self, framework: str, name: str, files: dict) -> str:
        """Write files into the framework's real workspace_root under a fresh
        temp data-root, returning that root (to pass as ``local_dir``)."""
        root = tempfile.mkdtemp(prefix="agent_test_watch_")
        ws = build_spec(framework, name, root).workspace_root
        for rel, content in files.items():
            fp = ws / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
        return root

    def _cleanup(self, path: str):
        shutil.rmtree(path, ignore_errors=True)

    def _upload_remote(self, name: str, framework: str, files: dict):
        """Upload files directly to remote (simulates remote-side changes).

        Uses push_incremental with correct create/update/delete actions so
        that files already on the remote are updated and files removed from
        the set are deleted on the remote.
        """
        skip_if_server_rejects(framework)
        from ms_agent.agent_hub._sync import push_resources, push_incremental
        byte_files = {
            k: (v.encode("utf-8") if isinstance(v, str) else v)
            for k, v in files.items()
        }
        # Ensure repo exists (idempotent)
        try:
            if not self.client.check_repo(self.username, name):
                self.client.create_repo(self.username, name, framework=framework)
        except Exception:
            pass
        # Determine which files already exist on remote
        try:
            existing = set(self.client.list_repo_files(self.username, name))
        except Exception:
            existing = set()
        if existing:
            # Build changed dict: new/modified files + deletions (None)
            changed: dict = {}
            for k, v in byte_files.items():
                changed[k] = v
            # Files on remote but NOT in the new set → delete
            for path in existing:
                if path not in byte_files and not path.startswith("."):
                    changed[path] = None
            push_incremental(self.client, self.username, name, changed, existing)
        else:
            push_resources(self.client, self.username, name, framework, byte_files)

    def _start_watch(self, framework: str, agent_name: str, local_dir: str, repo_name: str, push_only: bool = True) -> multiprocessing.Process:
        """Start a watch_loop in a child process, return the Process."""
        skip_if_server_rejects(framework)
        p = multiprocessing.Process(
            target=_watch_process_target,
            args=(SERVER, TOKEN, self._data_dir, framework, agent_name, local_dir, repo_name, WATCH_INTERVAL, push_only),
            daemon=True,
        )
        p.start()
        return p

    def _stop_watch(self, proc: multiprocessing.Process, timeout: int = 15):
        """Send SIGTERM to stop the watch process."""
        if proc.is_alive():
            os.kill(proc.pid, signal.SIGTERM)
            proc.join(timeout=timeout)
        if proc.is_alive():
            proc.terminate()

    def _wait_cycles(self, n: int = 2):
        """Wait for n watch cycles to complete."""
        time.sleep(WATCH_INTERVAL * n + 5)

    def _eventually(self, check, *, timeout: int = 90, interval: int = 5,
                    desc: str = "condition"):
        """Poll ``check`` until it returns truthy, or fail after ``timeout``.

        Watch sync is asynchronous (a background daemon pushes/pulls on its own
        cycle) and the remote has eventual-consistency lag, so reading state
        once right after a fixed sleep is inherently racy. Retrying until the
        expected state appears absorbs both the daemon cadence and server lag.
        Any exception raised by ``check`` (e.g. a transient 404 while the repo
        is still materializing) is treated as "not ready yet".
        """
        deadline = time.time() + timeout
        last_exc = None
        while time.time() < deadline:
            try:
                result = check()
                if result:
                    return result
            except Exception as e:  # transient server lag / 404 during sync
                last_exc = e
            time.sleep(interval)
        # Final attempt so the failure message reflects the latest state.
        try:
            if check():
                return True
        except Exception as e:
            last_exc = e
        self.fail(f"Timed out after {timeout}s waiting for {desc}"
                  + (f" (last error: {last_exc})" if last_exc else ""))

    # -----------------------------------------------------------------------
    # 01. qoder all: local change -> push to remote
    # -----------------------------------------------------------------------
    def test_01_qoder_all_local_push(self):
        """Local file change should be pushed to remote via watch_loop."""
        repo_name = f"{AGENT_PREFIX}-qoder-push"
        files = {
            "AGENTS.md": "# Agents\nInitial version.\n",
            "agents/reviewer.md": "# Reviewer\nReview code.\n",
            "rules/style.md": "# Style\nUse 4 spaces.\n",
        }
        local_dir = self._create_local(files)
        proc = None
        try:
            proc = self._start_watch("qoder", ALL_AGENT_NAME, local_dir, repo_name)

            # Wait until the daemon's initial push is visible on the remote.
            self._eventually(
                lambda: {"AGENTS.md", "agents/reviewer.md"}.issubset(
                    set(self.client.list_repo_files(self.username, repo_name))),
                desc="initial files pushed to remote")

            (Path(local_dir) / "AGENTS.md").write_text("# Agents\nUpdated version.\n", encoding="utf-8")

            self._eventually(
                lambda: "Updated version" in self.client.download_repo_file(
                    self.username, repo_name, "AGENTS.md"),
                desc="AGENTS.md update pushed to remote")
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 02. qoder all: remote change -> pull to local (bidirectional mode)
    # -----------------------------------------------------------------------
    def test_02_qoder_all_remote_pull(self):
        """Remote change should be pulled to local via watch_loop (push_only=False)."""
        repo_name = f"{AGENT_PREFIX}-qoder-pull"
        files = {
            "AGENTS.md": "# Agents\nOriginal.\n",
            "agents/coder.md": "# Coder\nWrite code.\n",
            "commands/build.md": "# Build\nBuild project.\n",
        }
        local_dir = self._create_local(files)
        proc = None
        try:
            proc = self._start_watch("qoder", ALL_AGENT_NAME, local_dir, repo_name, push_only=False)
            self._wait_cycles(2)

            updated_files = dict(files)
            updated_files["AGENTS.md"] = "# Agents\nRemotely modified.\n"
            updated_files["commands/deploy.md"] = "# Deploy\nNew remote file.\n"
            self._upload_remote(repo_name, "qoder", updated_files)
            _wait(5)

            self._wait_cycles(2)

            local_content = (Path(local_dir) / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("Remotely modified", local_content)
            new_file = Path(local_dir) / "commands" / "deploy.md"
            self.assertTrue(new_file.exists(), "new remote file should be pulled")
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 03. qwenpaw all: bidirectional sync (push_only=False)
    # -----------------------------------------------------------------------
    def test_03_qwenpaw_all_bidirectional(self):
        """qwenpaw all mode: local push then remote pull via watch_loop (push_only=False)."""
        repo_name = f"{AGENT_PREFIX}-qwenpaw-bi"
        files = {
            "bot-a/SOUL.md": "# Soul\nBot A identity.\n",
            "bot-a/PROFILE.md": "# Profile\nBot A profile.\n",
            "bot-b/SOUL.md": "# Soul\nBot B identity.\n",
        }
        local_dir = self._create_local_root("qwenpaw", ALL_AGENT_NAME, files)
        ws = build_spec("qwenpaw", ALL_AGENT_NAME, local_dir).workspace_root
        proc = None
        try:
            proc = self._start_watch("qwenpaw", ALL_AGENT_NAME, local_dir, repo_name, push_only=False)
            self._wait_cycles(2)

            # Poll instead of a single bare read: a freshly created repo may
            # 404 for a few seconds on the server side (eventual consistency).
            remote = self._eventually(
                lambda: (lambda fl: fl if "bot-a/SOUL.md" in fl and "bot-b/SOUL.md" in fl else None)(
                    self.client.list_repo_files(self.username, repo_name)),
                desc="initial push visible on remote")
            self.assertIn("bot-a/SOUL.md", remote)
            self.assertIn("bot-b/SOUL.md", remote)

            updated_files = dict(files)
            updated_files["bot-a/MEMORY.md"] = "# Memory\nBot A learned something.\n"
            self._upload_remote(repo_name, "qwenpaw", updated_files)
            _wait(5)

            self._wait_cycles(2)

            mem_file = ws / "bot-a" / "MEMORY.md"
            self.assertTrue(mem_file.exists())
            self.assertIn("learned something", mem_file.read_text(encoding="utf-8"))
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 04. qwenpaw individual sub-agent watch
    # -----------------------------------------------------------------------
    def test_04_qwenpaw_individual_watch(self):
        """qwenpaw supports watching a specific sub-agent via watch_loop."""
        repo_name = f"{AGENT_PREFIX}-qwenpaw-ind"
        files = {
            "SOUL.md": "# Soul\nMy bot identity.\n",
            "PROFILE.md": "# Profile\nCreative writer.\n",
        }
        local_dir = self._create_local_root("qwenpaw", repo_name, files)
        ws = build_spec("qwenpaw", repo_name, local_dir).workspace_root
        proc = None
        try:
            proc = self._start_watch("qwenpaw", repo_name, local_dir, repo_name)

            self._eventually(
                lambda: "SOUL.md" in self.client.list_repo_files(
                    self.username, repo_name),
                desc="SOUL.md pushed to remote")

            (ws / "PROFILE.md").write_text(
                "# Profile\nCreative writer. Loves sci-fi.\n", encoding="utf-8"
            )

            self._eventually(
                lambda: "Loves sci-fi" in self.client.download_repo_file(
                    self.username, repo_name, "PROFILE.md"),
                desc="PROFILE.md update pushed to remote")
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 05. Conflict: both sides changed -> remote wins (push_only=False)
    # -----------------------------------------------------------------------
    def test_05_conflict_remote_wins(self):
        """When both local and remote change, remote should win (push_only=False)."""
        repo_name = f"{AGENT_PREFIX}-conflict"
        files = {
            "AGENTS.md": "# Agents\nBaseline.\n",
            "rules/naming.md": "# Naming\nUse snake_case.\n",
        }
        local_dir = self._create_local(files)
        proc = None
        try:
            self._upload_remote(repo_name, "qoder", files)
            _wait(8)

            proc = self._start_watch("qoder", ALL_AGENT_NAME, local_dir, repo_name, push_only=False)
            self._wait_cycles(2)

            self._stop_watch(proc)
            proc = None
            _wait(REQUEST_INTERVAL)

            remote_files = dict(files)
            remote_files["AGENTS.md"] = "# Agents\nRemote version wins.\n"
            self._upload_remote(repo_name, "qoder", remote_files)
            _wait(8)

            (Path(local_dir) / "AGENTS.md").write_text(
                "# Agents\nLocal version loses.\n", encoding="utf-8"
            )

            proc = self._start_watch("qoder", ALL_AGENT_NAME, local_dir, repo_name, push_only=False)
            self._wait_cycles(3)

            local_content = (Path(local_dir) / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("Remote version wins", local_content)
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 06. Delete propagation: local delete -> remote
    # -----------------------------------------------------------------------
    def test_06_local_delete_pushes(self):
        """Deleting a local file should remove it from remote via watch_loop."""
        repo_name = f"{AGENT_PREFIX}-del-local"
        files = {
            "AGENTS.md": "# Agents\nKeep this.\n",
            "rules/obsolete.md": "# Obsolete\nRemove me.\n",
        }
        local_dir = self._create_local(files)
        proc = None
        try:
            self._upload_remote(repo_name, "qoder", files)
            _wait(8)

            proc = self._start_watch("qoder", ALL_AGENT_NAME, local_dir, repo_name)
            self._wait_cycles(2)

            remote = self.client.list_repo_files(self.username, repo_name)
            self.assertIn("rules/obsolete.md", remote)

            (Path(local_dir) / "rules" / "obsolete.md").unlink()

            self._wait_cycles(2)

            remote = self.client.list_repo_files(self.username, repo_name)
            self.assertNotIn("rules/obsolete.md", remote)
            self.assertIn("AGENTS.md", remote)
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 07. Delete propagation: remote delete -> local (push_only=False)
    # -----------------------------------------------------------------------
    def test_07_remote_delete_pulls(self):
        """Remote file removal should delete local file via watch_loop (push_only=False)."""
        repo_name = f"{AGENT_PREFIX}-del-remote"
        files = {
            "AGENTS.md": "# Agents\nStay.\n",
            "commands/temp.md": "# Temp\nWill be removed remotely.\n",
        }
        local_dir = self._create_local(files)
        proc = None
        try:
            proc = self._start_watch("qoder", ALL_AGENT_NAME, local_dir, repo_name, push_only=False)

            # Ensure the initial push landed first, otherwise the remote
            # reduction below sees no commands/temp.md and becomes a no-op.
            self._eventually(
                lambda: "commands/temp.md" in self.client.list_repo_files(
                    self.username, repo_name),
                desc="initial push includes commands/temp.md")

            reduced_files = {"AGENTS.md": "# Agents\nStay.\n"}
            self._upload_remote(repo_name, "qoder", reduced_files)

            temp_path = Path(local_dir) / "commands" / "temp.md"
            self._eventually(
                lambda: not temp_path.exists(),
                desc="local commands/temp.md removed by remote-delete pull")
            self.assertTrue((Path(local_dir) / "AGENTS.md").exists())
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 08. Multi-process: concurrent watches on different repos
    # -----------------------------------------------------------------------
    def test_08_multi_process_concurrent_watches(self):
        """Multiple watch processes for different repos sync independently."""
        repo1 = f"{AGENT_PREFIX}-mt-qoder"
        files1 = {
            "AGENTS.md": "# MT1\nMulti-thread test 1.\n",
            "agents/bot1.md": "# Bot1\nFirst bot.\n",
        }
        local1 = self._create_local(files1)

        repo2 = f"{AGENT_PREFIX}-mt-qwenpaw"
        files2 = {
            "SOUL.md": "# MT2\nMulti-thread test 2.\n",
            "PROFILE.md": "# Profile\nSecond bot.\n",
        }
        local2 = self._create_local_root("qwenpaw", repo2, files2)
        ws2 = build_spec("qwenpaw", repo2, local2).workspace_root

        proc1 = None
        proc2 = None
        try:
            proc1 = self._start_watch("qoder", ALL_AGENT_NAME, local1, repo1, push_only=False)
            proc2 = self._start_watch("qwenpaw", repo2, local2, repo2, push_only=False)

            self._wait_cycles(3)

            (Path(local1) / "AGENTS.md").write_text(
                "# MT1\nUpdated by watch process.\n", encoding="utf-8"
            )

            updated2 = dict(files2)
            updated2["SOUL.md"] = "# MT2\nRemotely updated.\n"
            self._upload_remote(repo2, "qwenpaw", updated2)

            self._wait_cycles(3)

            content1 = self.client.download_repo_file(self.username, repo1, "AGENTS.md")
            self.assertIn("Updated by watch process", content1)

            soul2 = (ws2 / "SOUL.md").read_text(encoding="utf-8")
            self.assertIn("Remotely updated", soul2)
        finally:
            if proc1:
                self._stop_watch(proc1)
            if proc2:
                self._stop_watch(proc2)
            self._cleanup(local1)
            self._cleanup(local2)

    # -----------------------------------------------------------------------
    # 09. First sync with empty baseline -> push everything
    # -----------------------------------------------------------------------
    def test_09_first_sync_empty_baseline(self):
        """First watch start with no prior state should push all local files."""
        repo_name = f"{AGENT_PREFIX}-first-sync"
        files = {
            "SOUL.md": "# Soul\nBrand new agent.\n",
            "PROFILE.md": "# Profile\nNew profile.\n",
        }
        local_dir = self._create_local_root("qwenpaw", repo_name, files)
        proc = None
        try:
            sf = sync_state_file(repo_name)
            if sf.exists():
                sf.unlink()

            proc = self._start_watch("qwenpaw", repo_name, local_dir, repo_name)

            # A freshly created repo can still be materializing, so poll instead
            # of reading once after a fixed sleep (see ``_eventually``).
            self._eventually(
                lambda: {"SOUL.md", "PROFILE.md"}.issubset(
                    set(self.client.list_repo_files(self.username, repo_name))),
                desc="all local files pushed on first sync")
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 10. No-op cycle: nothing changed
    # -----------------------------------------------------------------------
    def test_10_noop_no_changes(self):
        """When nothing changed, watch_loop should not modify files."""
        repo_name = f"{AGENT_PREFIX}-noop"
        files = {"SOUL.md": "# Soul\nStable content.\n"}
        local_dir = self._create_local(files)
        proc = None
        try:
            proc = self._start_watch("qwenpaw", repo_name, local_dir, repo_name)
            self._wait_cycles(2)

            soul_path = Path(local_dir) / "SOUL.md"
            mtime_before = soul_path.stat().st_mtime

            self._wait_cycles(2)

            mtime_after = soul_path.stat().st_mtime
            self.assertEqual(mtime_before, mtime_after, "file should not be modified in no-op")
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 11. file-per-agent watch guard: qoder individual -> rejected
    # -----------------------------------------------------------------------
    def test_11_qoder_individual_watch_rejected(self):
        """qoder individual watch (not 'all') should be blocked by cmd_watch."""
        rc = cmd_watch(
            framework="qoder", name="reviewer",
            endpoint=SERVER, token=TOKEN, username=self.username,
        )
        self.assertEqual(rc, 1, "qoder individual watch should be rejected")

    # -----------------------------------------------------------------------
    # 12. qwenpaw individual watch -> allowed
    # -----------------------------------------------------------------------
    def test_12_qwenpaw_individual_watch_allowed(self):
        """qwenpaw supports individual sub-agent watch (supports_individual_watch=True)."""
        spec_cls = FRAMEWORK_REGISTRY["qwenpaw"]
        spec = spec_cls(agent_name="test-bot")
        self.assertTrue(spec.supports_individual_watch)

    # -----------------------------------------------------------------------
    # 13. Add new file locally -> appears on remote
    # -----------------------------------------------------------------------
    def test_13_add_new_file_locally(self):
        """Adding a new file locally should push it to remote via watch_loop."""
        repo_name = f"{AGENT_PREFIX}-add-file"
        files = {"SOUL.md": "# Soul\nBase.\n"}
        local_dir = self._create_local_root("qwenpaw", repo_name, files)
        ws = build_spec("qwenpaw", repo_name, local_dir).workspace_root
        proc = None
        try:
            proc = self._start_watch("qwenpaw", repo_name, local_dir, repo_name)
            self._wait_cycles(2)

            new_path = ws / "MEMORY.md"
            new_path.write_text("# Memory\nSomething new.\n", encoding="utf-8")

            self._wait_cycles(2)

            remote = self.client.list_repo_files(self.username, repo_name)
            self.assertIn("MEMORY.md", remote)
            content = self.client.download_repo_file(self.username, repo_name, "MEMORY.md")
            self.assertIn("Something new", content)
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 14. Sync state persistence across restarts
    # -----------------------------------------------------------------------
    def test_14_state_persistence(self):
        """Sync state persists to disk - second watch start reuses baseline."""
        repo_name = f"{AGENT_PREFIX}-persist"
        files = {"SOUL.md": "# Soul\nPersist test.\n"}
        local_dir = self._create_local_root("qwenpaw", repo_name, files)
        ws = build_spec("qwenpaw", repo_name, local_dir).workspace_root
        proc = None
        try:
            proc = self._start_watch("qwenpaw", repo_name, local_dir, repo_name)
            self._wait_cycles(2)
            self._stop_watch(proc)
            proc = None

            state = load_sync_state(repo_name)
            # State persistence is sha256-based: the remote_files map is the
            # baseline used for change detection across restarts.
            self.assertIn("SOUL.md", state["remote_files"])
            self.assertTrue(state["remote_files"]["SOUL.md"])

            _wait(REQUEST_INTERVAL)

            soul_path = ws / "SOUL.md"
            mtime_before = soul_path.stat().st_mtime

            proc = self._start_watch("qwenpaw", repo_name, local_dir, repo_name)
            self._wait_cycles(2)

            mtime_after = soul_path.stat().st_mtime
            self.assertEqual(mtime_before, mtime_after)
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)
            sf = sync_state_file(repo_name)
            if sf.exists():
                sf.unlink()

    # -----------------------------------------------------------------------
    # 15. Common prefix preserved
    # -----------------------------------------------------------------------
    def test_15_common_prefix_preserved(self):
        """When ALL files share a top-level prefix, the zip wrapper ensures
        the server does not strip that prefix after upload."""
        repo_name = f"{AGENT_PREFIX}-prefix"
        files = {
            "skills/lint/SKILL.md": "# Lint\nRun linter.\n",
            "skills/lint/scripts/run.sh": "#!/bin/bash\nflake8 .\n",
            "skills/format/SKILL.md": "# Format\nAuto-format code.\n",
        }
        local_dir = self._create_local(files)
        proc = None
        try:
            proc = self._start_watch("qoder", ALL_AGENT_NAME, local_dir, repo_name)

            expected = {"skills/lint/SKILL.md", "skills/lint/scripts/run.sh",
                        "skills/format/SKILL.md"}
            self._eventually(
                lambda: expected.issubset(
                    set(self.client.list_repo_files(self.username, repo_name))),
                desc="skills/ prefix preserved on remote")

            self._eventually(
                lambda: "Run linter" in self.client.download_repo_file(
                    self.username, repo_name, "skills/lint/SKILL.md"),
                desc="skills/lint/SKILL.md content readable")
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 16. Modify a file under common prefix
    # -----------------------------------------------------------------------
    def test_16_common_prefix_modify_push(self):
        """Modify a file under a shared prefix, verify the push preserves paths."""
        repo_name = f"{AGENT_PREFIX}-prefix-mod"
        files = {
            "skills/lint/SKILL.md": "# Lint\nVersion 1.\n",
            "skills/format/SKILL.md": "# Format\nVersion 1.\n",
        }
        local_dir = self._create_local(files)
        proc = None
        try:
            proc = self._start_watch("qoder", ALL_AGENT_NAME, local_dir, repo_name)
            self._wait_cycles(2)

            (Path(local_dir) / "skills" / "lint" / "SKILL.md").write_text(
                "# Lint\nVersion 2 - updated.\n", encoding="utf-8"
            )

            self._wait_cycles(2)

            content = self.client.download_repo_file(
                self.username, repo_name, "skills/lint/SKILL.md")
            self.assertIn("Version 2", content)

            content2 = self.client.download_repo_file(
                self.username, repo_name, "skills/format/SKILL.md")
            self.assertIn("Version 1", content2)
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 17. push_only=True: remote changes do NOT pull to local
    # -----------------------------------------------------------------------
    def test_17_push_only_ignores_remote_changes(self):
        """With push_only=True (default), remote changes should NOT be pulled."""
        repo_name = f"{AGENT_PREFIX}-push-only"
        files = {
            "AGENTS.md": "# Agents\nLocal original.\n",
            "rules/style.md": "# Style\nLocal rule.\n",
        }
        local_dir = self._create_local(files)
        proc = None
        try:
            proc = self._start_watch("qoder", ALL_AGENT_NAME, local_dir, repo_name, push_only=True)
            self._wait_cycles(2)

            remote_files = dict(files)
            remote_files["AGENTS.md"] = "# Agents\nRemote modification.\n"
            remote_files["commands/new.md"] = "# New\nAdded remotely.\n"
            self._upload_remote(repo_name, "qoder", remote_files)
            _wait(8)

            self._wait_cycles(3)

            local_content = (Path(local_dir) / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("Local original", local_content)
            self.assertNotIn("Remote modification", local_content)

            new_file = Path(local_dir) / "commands" / "new.md"
            self.assertFalse(new_file.exists(), "remote-only file should NOT be pulled in push_only mode")
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 18. push_only=True: remote delete does NOT delete local files
    # -----------------------------------------------------------------------
    def test_18_push_only_prevents_local_deletion(self):
        """With push_only=True, files deleted on remote should NOT be deleted locally."""
        repo_name = f"{AGENT_PREFIX}-push-only-del"
        files = {
            "AGENTS.md": "# Agents\nKeep me safe.\n",
            "rules/important.md": "# Important\nMust not be deleted.\n",
            "agents/coder.md": "# Coder\nValuable local file.\n",
        }
        local_dir = self._create_local(files)
        proc = None
        try:
            proc = self._start_watch("qoder", ALL_AGENT_NAME, local_dir, repo_name, push_only=True)
            self._wait_cycles(2)

            reduced_remote = {"AGENTS.md": "# Agents\nOnly this survives on remote.\n"}
            self._upload_remote(repo_name, "qoder", reduced_remote)
            _wait(8)

            self._wait_cycles(3)

            self.assertTrue(
                (Path(local_dir) / "rules" / "important.md").exists(),
                "push_only must protect local files from remote-side deletion"
            )
            self.assertTrue(
                (Path(local_dir) / "agents" / "coder.md").exists(),
                "push_only must protect local files from remote-side deletion"
            )
            self.assertTrue(
                (Path(local_dir) / "AGENTS.md").exists(),
                "AGENTS.md must still exist locally"
            )

            content = (Path(local_dir) / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("Keep me safe", content)
            self.assertNotIn("Only this survives", content)
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)

    # -----------------------------------------------------------------------
    # 19. push_only=True: conflict scenario -> local push wins
    # -----------------------------------------------------------------------
    def test_19_push_only_conflict_local_wins(self):
        """With push_only=True, local push wins (remote never overwrites local)."""
        repo_name = f"{AGENT_PREFIX}-push-only-conflict"
        files = {
            "AGENTS.md": "# Agents\nBaseline.\n",
        }
        local_dir = self._create_local(files)
        proc = None
        try:
            proc = self._start_watch("qoder", ALL_AGENT_NAME, local_dir, repo_name, push_only=True)
            self._wait_cycles(2)

            self._stop_watch(proc)
            proc = None
            _wait(REQUEST_INTERVAL)

            self._upload_remote(repo_name, "qoder", {"AGENTS.md": "# Agents\nRemote version.\n"})
            _wait(8)

            (Path(local_dir) / "AGENTS.md").write_text(
                "# Agents\nLocal version should win.\n", encoding="utf-8"
            )

            proc = self._start_watch("qoder", ALL_AGENT_NAME, local_dir, repo_name, push_only=True)
            self._wait_cycles(3)

            local_content = (Path(local_dir) / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("Local version should win", local_content)
            self.assertNotIn("Remote version", local_content)

            remote_content = self.client.download_repo_file(self.username, repo_name, "AGENTS.md")
            self.assertIn("Local version should win", remote_content)
        finally:
            if proc:
                self._stop_watch(proc)
            self._cleanup(local_dir)


class TestStopDaemonTargeting(unittest.TestCase):
    """``agent stop`` must only ever signal OUR watch daemon (BUG-014).

    Offline: uses throwaway ``sleep`` child processes with crafted argv and
    a temp-dir pid/stop file, no network or real daemon involved.
    """

    def _stop(self, tmp, pid_content=None):
        from unittest import mock

        from ms_agent.agent_hub import _watcher
        tmp = Path(tmp)
        if pid_content is not None:
            (tmp / "watch.pid").write_text(str(pid_content))
        with mock.patch.object(_watcher, "pid_file",
                               return_value=tmp / "watch.pid"), \
                mock.patch.object(_watcher, "stop_file",
                                  return_value=tmp / "watch.stop"):
            return _watcher.stop_daemon()

    def test_unrelated_process_with_watch_text_survives(self):
        """Regression: argv merely CONTAINING 'agent watch' used to get
        SIGTERMed by the pgrep sweep."""
        proc = subprocess.Popen([
            sys.executable, "-c", "import time; time.sleep(60)", "ms-agent",
            "agent", "watch", "-f", "nanobot"
        ])
        try:
            time.sleep(0.5)
            with tempfile.TemporaryDirectory() as td:
                rc = self._stop(td)
            time.sleep(0.5)
            self.assertFalse(rc)  # cmd_stop prints 'No watch process running'
            self.assertIsNone(proc.poll(), "unrelated process was killed")
        finally:
            proc.kill()

    def test_real_daemon_marker_is_found_and_stopped(self):
        """A process carrying the daemon's exact argv marker IS stopped."""
        proc = subprocess.Popen([
            sys.executable, "-c", "import time; time.sleep(60)",
            "ms_agent.agent_hub._watcher", "_daemon", "/tmp/x.json"
        ])
        try:
            time.sleep(0.5)
            with tempfile.TemporaryDirectory() as td:
                rc = self._stop(td)
            time.sleep(1)
            self.assertTrue(rc)
            self.assertIsNotNone(proc.poll(), "daemon-marked process survived")
        finally:
            proc.kill()

    def test_stale_pid_file_pointing_at_foreign_process(self):
        """A recycled pid in the pid file must not be signalled."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            time.sleep(0.5)
            with tempfile.TemporaryDirectory() as td:
                rc = self._stop(td, pid_content=proc.pid)
            time.sleep(0.5)
            self.assertFalse(rc)
            self.assertIsNone(proc.poll(), "foreign pid-file pid was killed")
        finally:
            proc.kill()


if __name__ == "__main__":
    unittest.main(verbosity=2)
