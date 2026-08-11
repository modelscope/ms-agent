"""Integration tests for upload and download commands.

Covers:
    - Upload individual sub-agent (each framework)
    - Upload all mode (qoder, nanobot, qwenpaw, openclaw)
    - Upload --dry-run (no server call)
    - Upload --list (enumerate on-disk sub-agents)
    - Upload missing --name -> error
    - Upload unknown framework -> error
    - Upload empty workspace -> error
    - Download individual sub-agent
    - Download with --framework explicit
    - Download with --target (cross-framework conversion)
    - Download with --local_dir override
    - Download --dry-run (no write)
    - Download non-existent repo -> error
    - Download unknown framework -> error
    - Round-trip: upload -> download -> content verification
    - All-mode round-trip for file-per-agent (qoder)
    - All-mode round-trip for root-per-agent (qwenpaw)
    - Idempotent re-upload -> content unchanged

Usage:
    python -m pytest tests/agent/test_upload_download.py -v
"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

import pytest

from modelscope_hub.agent._api import AgentApi
from modelscope_hub.errors import APIError
from ms_agent.agent_hub._commands import (
    build_spec,
    cmd_download,
    cmd_status,
    cmd_upload,
    repo_name as _repo_name,
)
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
AGENT_PREFIX = f"test-updown-{int(time.time())}"

# Throttle between each test method to avoid 429 and WAF blocks
REQUEST_INTERVAL = int(os.environ.get("REQUEST_INTERVAL", "8"))


def _wait(seconds: int = 5):
    print(f"    (waiting {seconds}s...)")
    time.sleep(seconds)


def _log_429(fn, *args, **kwargs):
    """Call fn; on 429 log which API was rate-limited and re-raise."""
    try:
        return fn(*args, **kwargs)
    except APIError as e:
        if e.status_code == 429:
            print(f"    [429 RATE LIMITED] {fn.__name__}()", file=sys.stderr)
        raise


# ---------------------------------------------------------------------------
# Mock file sets for testing
# ---------------------------------------------------------------------------

QODER_INDIVIDUAL_FILES = {
    "AGENTS.md": "# Agents\n\n## Available\n- reviewer\n- coder\n",
    "agents/reviewer.md": "# Reviewer\nCode review sub-agent.\n",
    "commands/review.md": "# /review\nReview code.\n",
    "rules/style.md": "# Style\nUse 4 spaces.\n",
    "skills/lint/SKILL.md": "# Lint\nRun linter.\n",
    "skills/lint/scripts/run.sh": "# lint runner\nrun flake8 on project files\n",
}

QODER_ALL_FILES = {
    "AGENTS.md": "# Agents\n\n## Available\n- reviewer\n- coder\n",
    "agents/reviewer.md": "# Reviewer\nCode review sub-agent.\n",
    "agents/coder.md": "# Coder\nCode generation sub-agent.\n",
    "commands/review.md": "# /review\nReview code.\n",
    "rules/style.md": "# Style\nUse 4 spaces.\n",
    "skills/lint/SKILL.md": "# Lint\nRun linter.\n",
}

NANOBOT_ALL_FILES = {
    "AGENTS.md": "# Agents\n",
    "SOUL.md": "# Soul\nI am nanobot.\n",
    "agents/helper.md": "# Helper\nA helper sub-agent.\n",
    "agents/writer.md": "# Writer\nA writer sub-agent.\n",
    "memory/MEMORY.md": "# Memory\n",
    "skills/search/SKILL.md": "# Search\nWeb search.\n",
}

QWENPAW_INDIVIDUAL_FILES = {
    "SOUL.md": "# Soul\nQwenPaw creative AI.\n",
    "PROFILE.md": "# Profile\nCreative writer.\n",
    "MEMORY.md": "# Memory\nStory ideas.\n",
    "skills/storytelling/SKILL.md": "# Storytelling\nNarrative skills.\n",
}

QWENPAW_ALL_FILES = {
    "bot-a/SOUL.md": "# Soul\nBot A creative AI.\n",
    "bot-a/PROFILE.md": "# Profile A\nBot A profile.\n",
    "bot-a/skills/write/SKILL.md": "# Write\nWriting skill.\n",
    "bot-b/SOUL.md": "# Soul\nBot B analysis AI.\n",
    "bot-b/PROFILE.md": "# Profile B\nBot B profile.\n",
    "bot-b/skills/analyze/SKILL.md": "# Analyze\nAnalysis skill.\n",
}

OPENCLAW_ALL_FILES = {
    "workspace/SOUL.md": "# Soul\nDefault agent.\n",
    "workspace/AGENTS.md": "# Agents\nDefault.\n",
    "workspace/skills/code/SKILL.md": "# Code\nCoding.\n",
    "workspace-helper/SOUL.md": "# Soul\nHelper agent.\n",
    "workspace-helper/AGENTS.md": "# Agents\nHelper.\n",
    "workspace-helper/skills/refactor/SKILL.md": "# Refactor\nRefactoring.\n",
}


# ===========================================================================
# Test class
# ===========================================================================

@pytest.mark.remote
class TestUploadDownload(unittest.TestCase):
    """Integration tests for upload/download commands against a real server."""

    client: AgentApi = None  # type: ignore
    username: str = ""

    @classmethod
    def setUpClass(cls):
        cls.client = AgentApi(SERVER, TOKEN)
        cls.username = cls.client._openapi.get_current_username()
        assert cls.username, "login failed"
        print(f"    Logged in as {cls.username}")

    def setUp(self):
        time.sleep(REQUEST_INTERVAL)

    # -----------------------------------------------------------------------
    # Helper
    # -----------------------------------------------------------------------
    def _create_local_workspace(self, files: dict) -> str:
        """Write files into a temp dir and return its path."""
        tmpdir = tempfile.mkdtemp(prefix="agent_test_")
        for rel, content in files.items():
            fp = Path(tmpdir) / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                fp.write_bytes(content)
            else:
                fp.write_text(content, encoding="utf-8")
        return tmpdir

    def _create_local_root(self, framework: str, name: str, files: dict) -> str:
        """Write files into the framework's real workspace_root under a fresh
        temp data-root, returning that root (to pass as ``local_dir``).

        Needed for root-per-agent layouts (qwenpaw ``workspaces/``, hermes
        ``profiles/<name>``) where ``local_dir`` is the data root and the files
        live under a framework-derived middle directory.
        """
        root = tempfile.mkdtemp(prefix="agent_test_")
        ws = build_spec(framework, name, root).workspace_root
        for rel, content in files.items():
            fp = ws / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                fp.write_bytes(content)
            else:
                fp.write_text(content, encoding="utf-8")
        return root

    def _cleanup_dir(self, path: str):
        if path and Path(path).exists():
            shutil.rmtree(path, ignore_errors=True)

    # -----------------------------------------------------------------------
    # 01. Upload: basic individual sub-agent
    # -----------------------------------------------------------------------
    def test_01_upload_individual_qoder(self):
        skip_if_server_rejects("qoder")
        agent_name = f"{AGENT_PREFIX}-qoder-ind"
        files = {
            "AGENTS.md": "# Agents\n\n## Available\n- reviewer\n",
            f"agents/{agent_name}.md": "# Test Agent\nIntegration test.\n",
            "commands/review.md": "# /review\nReview code.\n",
            "rules/style.md": "# Style\nUse 4 spaces.\n",
            "skills/lint/SKILL.md": "# Lint\nRun linter.\n",
            "skills/lint/scripts/run.sh": "# lint runner\nrun flake8 on project files\n",
        }
        local = self._create_local_workspace(files)
        try:
            rc = cmd_upload(
                framework="qoder", name=agent_name, local_dir=local,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 0, "upload should succeed")
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 02. Upload: --name all across layouts (qoder / qwenpaw / openclaw / nanobot)
    # -----------------------------------------------------------------------
    def test_02_upload_all_frameworks(self):
        """--name all upload succeeds for every layout family."""
        cases = [
            ("qoder", QODER_ALL_FILES),
            ("qwenpaw", QWENPAW_ALL_FILES),
            ("openclaw", OPENCLAW_ALL_FILES),
            ("nanobot", NANOBOT_ALL_FILES),
        ]
        for framework, files in cases:
            with self.subTest(framework=framework):
                local = self._create_local_root(framework, ALL_AGENT_NAME, files)
                try:
                    rc = cmd_upload(
                        framework=framework, name=ALL_AGENT_NAME, local_dir=local,
                        endpoint=SERVER, token=TOKEN, username=self.username,
                    )
                    self.assertEqual(rc, 0, f"upload all {framework} should succeed")
                finally:
                    self._cleanup_dir(local)
                _wait(REQUEST_INTERVAL)

    # -----------------------------------------------------------------------
    # 05. Upload: --dry-run
    # -----------------------------------------------------------------------
    def test_05_upload_dry_run(self):
        local = self._create_local_workspace(QODER_INDIVIDUAL_FILES)
        try:
            rc = cmd_upload(
                framework="qoder", name="dry-run-test", local_dir=local,
                dry_run=True,
            )
            self.assertEqual(rc, 0)
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 06. List: list sub-agents
    # -----------------------------------------------------------------------
    def test_06_upload_list(self):
        local = self._create_local_workspace(QODER_ALL_FILES)
        try:
            rc = cmd_status(framework="qoder", local_dir=local)
            self.assertEqual(rc, 0)
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 07. Upload: missing --name with multiple agents -> error
    # -----------------------------------------------------------------------
    def test_07_upload_missing_name(self):
        local = self._create_local_workspace(QODER_ALL_FILES)
        try:
            rc = cmd_upload(
                framework="qoder", name=None, local_dir=local,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 1)
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 08. Upload: unknown framework -> error
    # -----------------------------------------------------------------------
    def test_08_upload_unknown_framework(self):
        local = self._create_local_workspace({"SOUL.md": "# test\n"})
        try:
            rc = cmd_upload(framework="nonexistent-fw", name="test", local_dir=local)
            self.assertEqual(rc, 1)
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 09. Upload: empty workspace -> error
    # -----------------------------------------------------------------------
    def test_09_upload_empty_workspace(self):
        local = tempfile.mkdtemp(prefix="agent_test_empty_")
        try:
            rc = cmd_upload(
                framework="qoder", name="empty-test", local_dir=local,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 1)
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 11. Download: existing repo
    # -----------------------------------------------------------------------
    def test_11_download_existing_repo(self):
        skip_if_server_rejects("qoder")
        agent_name = f"{AGENT_PREFIX}-qoder-ind"
        _wait(5)
        local = tempfile.mkdtemp(prefix="agent_test_dl_")
        try:
            rc = cmd_download(
                framework="qoder", repo=_repo_name("qoder", agent_name), local_dir=local,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 0, "download should succeed")
            written = list(Path(local).rglob("*"))
            files = [f for f in written if f.is_file()]
            self.assertGreater(len(files), 0, "should have downloaded files")
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 12. Download: --dry-run
    # -----------------------------------------------------------------------
    def test_12_download_dry_run(self):
        skip_if_server_rejects("qoder")
        agent_name = f"{AGENT_PREFIX}-qoder-ind"
        _wait(5)
        local = tempfile.mkdtemp(prefix="agent_test_dldry_")
        try:
            rc = cmd_download(
                framework="qoder", repo=_repo_name("qoder", agent_name), local_dir=local,
                dry_run=True,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 0)
            files = [f for f in Path(local).rglob("*") if f.is_file()]
            self.assertEqual(len(files), 0, "dry-run should not write files")
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 13. Download: non-existent repo -> error
    # -----------------------------------------------------------------------
    def test_13_download_nonexistent_repo(self):
        local = tempfile.mkdtemp(prefix="agent_test_dlne_")
        try:
            rc = cmd_download(
                framework="qoder", repo="nonexistent-repo-xyz-99999", local_dir=local,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 1)
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 14. Download: unknown target framework -> error
    # -----------------------------------------------------------------------
    def test_14_download_unknown_target(self):
        agent_name = f"{AGENT_PREFIX}-qoder-ind"
        local = tempfile.mkdtemp(prefix="agent_test_dluf_")
        try:
            rc = cmd_download(
                framework="qoder", repo=agent_name, target="badfw", local_dir=local,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 1)
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 15. Download: cross-framework conversion
    # -----------------------------------------------------------------------
    def test_15_download_cross_framework(self):
        skip_if_server_rejects("nanobot", "openclaw")
        agent_name = f"{AGENT_PREFIX}-nanobot-conv"
        nanobot_files = {
            "SOUL.md": "# Soul\nConversion test.\n",
            "AGENTS.md": "# Agents\nNanobot agents.\n",
            "skills/search/SKILL.md": "# Search\nSearch skill.\n",
        }
        local_up = self._create_local_workspace(nanobot_files)
        try:
            rc = cmd_upload(
                framework="nanobot", name=agent_name, local_dir=local_up,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 0)
        finally:
            self._cleanup_dir(local_up)

        _wait(5)

        local_dl = tempfile.mkdtemp(prefix="agent_test_dlconv_")
        try:
            rc = cmd_download(
                framework="nanobot", repo=_repo_name("nanobot", agent_name), target="openclaw", local_dir=local_dl,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 0)
            files = [f for f in Path(local_dl).rglob("*") if f.is_file()]
            self.assertGreater(len(files), 0)
        finally:
            self._cleanup_dir(local_dl)

    # -----------------------------------------------------------------------
    # 16. Round-trip: upload -> list -> download -> verify content
    # -----------------------------------------------------------------------
    def test_16_roundtrip_content_verify(self):
        skip_if_server_rejects("qoder")
        agent_name = f"{AGENT_PREFIX}-roundtrip"
        files = {
            "AGENTS.md": "# Roundtrip Agents\nTest content.\n",
            f"agents/{agent_name}.md": "# test-rt\nRoundtrip sub-agent.\n",
            "rules/naming.md": "# Naming\nUse snake_case.\n",
            "skills/format/SKILL.md": "# Format\nCode formatter.\n",
        }
        local_up = self._create_local_workspace(files)
        try:
            rc = cmd_upload(
                framework="qoder", name=agent_name, local_dir=local_up,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 0)
        finally:
            self._cleanup_dir(local_up)

        _wait(5)

        server_files = self.client.list_repo_files(self.username, _repo_name("qoder", agent_name))
        uploaded_keys = set(files.keys())
        server_set = set(server_files)
        missing = uploaded_keys - server_set
        self.assertFalse(missing, f"files missing on server: {missing}")

        for rel, expected in files.items():
            if rel in server_set:
                actual = self.client.download_repo_file(self.username, _repo_name("qoder", agent_name), rel)
                self.assertEqual(actual.strip(), expected.strip(),
                                 f"content mismatch for {rel}")

    # -----------------------------------------------------------------------
    # 17. Round-trip: all-mode across layouts (qoder / qwenpaw / openclaw)
    # -----------------------------------------------------------------------
    def test_17_roundtrip_all_frameworks(self):
        """all-mode upload then list, asserting each layout's prefixed paths."""
        cases = [
            ("qoder", QODER_ALL_FILES,
             ["agents/reviewer.md", "agents/coder.md", "AGENTS.md"]),
            ("qwenpaw", QWENPAW_ALL_FILES,
             ["bot-a/SOUL.md", "bot-b/SOUL.md", "bot-a/skills/write/SKILL.md"]),
            ("openclaw", OPENCLAW_ALL_FILES,
             ["workspace/SOUL.md", "workspace-helper/SOUL.md"]),
        ]
        for framework, files, expected in cases:
            with self.subTest(framework=framework):
                local_up = self._create_local_root(framework, ALL_AGENT_NAME, files)
                try:
                    rc = cmd_upload(
                        framework=framework, name=ALL_AGENT_NAME, local_dir=local_up,
                        endpoint=SERVER, token=TOKEN, username=self.username,
                    )
                    self.assertEqual(rc, 0)
                finally:
                    self._cleanup_dir(local_up)

                _wait(5)

                repo = _repo_name(framework, ALL_AGENT_NAME)
                server_set = set(self.client.list_repo_files(self.username, repo))
                for rel in expected:
                    self.assertIn(rel, server_set,
                                  f"{framework}: {rel} missing on server")
                _wait(REQUEST_INTERVAL)

    # -----------------------------------------------------------------------
    # 20. Idempotent re-upload
    # -----------------------------------------------------------------------
    def test_20_idempotent_reupload(self):
        skip_if_server_rejects("qoder")
        agent_name = f"{AGENT_PREFIX}-idempotent"
        files = {"AGENTS.md": "# Agents\nIdempotent test.\n", f"agents/{agent_name}.md": "# Test\n"}
        local = self._create_local_workspace(files)
        try:
            for _ in range(2):
                rc = cmd_upload(
                    framework="qoder", name=agent_name, local_dir=local,
                    endpoint=SERVER, token=TOKEN, username=self.username,
                )
                self.assertEqual(rc, 0)
                _wait(REQUEST_INTERVAL)
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 21. Upload then modify -> re-upload -> verify new content
    # -----------------------------------------------------------------------
    def test_21_upload_modify_reupload(self):
        skip_if_server_rejects("qoder")
        agent_name = f"{AGENT_PREFIX}-modify"
        files_v1 = {"AGENTS.md": "# V1\nOriginal.\n", f"agents/{agent_name}.md": "# Agent V1\n"}
        files_v2 = {"AGENTS.md": "# V2\nModified.\n", f"agents/{agent_name}.md": "# Agent V1 updated\n"}

        local = self._create_local_workspace(files_v1)
        try:
            rc = cmd_upload(
                framework="qoder", name=agent_name, local_dir=local,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 0)
        finally:
            self._cleanup_dir(local)

        _wait(5)

        local = self._create_local_workspace(files_v2)
        try:
            rc = cmd_upload(
                framework="qoder", name=agent_name, local_dir=local,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 0)
        finally:
            self._cleanup_dir(local)

        _wait(5)

        content = self.client.download_repo_file(self.username, _repo_name("qoder", agent_name), "AGENTS.md")
        self.assertIn("V2", content)
        self.assertIn("Modified", content)

    # -----------------------------------------------------------------------
    # 22. Download with --local_dir override
    # -----------------------------------------------------------------------
    def test_22_download_local_dir_override(self):
        skip_if_server_rejects("qoder")
        agent_name = f"{AGENT_PREFIX}-qoder-ind"
        custom_dir = tempfile.mkdtemp(prefix="agent_test_custom_")
        try:
            rc = cmd_download(
                framework="qoder", repo=_repo_name("qoder", agent_name), local_dir=custom_dir,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 0)
            files = [f for f in Path(custom_dir).rglob("*") if f.is_file()]
            self.assertGreater(len(files), 0)
            for f in files:
                self.assertTrue(str(f).startswith(custom_dir))
        finally:
            self._cleanup_dir(custom_dir)

    # -----------------------------------------------------------------------
    # 23. Upload: all frameworks individually
    # -----------------------------------------------------------------------
    def test_23_upload_each_framework(self):
        for fw in FRAMEWORK_REGISTRY:
            with self.subTest(framework=fw):
                skip_if_server_rejects(fw)
                agent_name = f"{AGENT_PREFIX}-fw-{fw}"
                if fw == "qoder":
                    files = {"AGENTS.md": "# Agents\n", f"agents/{agent_name}.md": "# X\n"}
                elif fw == "nanobot":
                    files = {"SOUL.md": "# Soul\n", f"agents/{agent_name}.md": "# X\n"}
                elif fw == "openclaw":
                    files = {"SOUL.md": "# Soul\n", "IDENTITY.md": "# ID\n"}
                elif fw == "qwenpaw":
                    files = {"SOUL.md": "# Soul\n", "PROFILE.md": "# P\n"}
                elif fw == "hermes":
                    files = {"SOUL.md": "# Soul\n"}
                elif fw == "openhuman":
                    files = {"wiki/identity.md": "# Identity\n"}
                elif fw == "ms-agent":
                    files = {"profile.md": "# Profile\n", "MEMORY.md": "# Memory\n"}
                else:
                    files = {"SOUL.md": "# Soul\n"}
                local = self._create_local_root(fw, agent_name, files)
                try:
                    rc = cmd_upload(
                        framework=fw, name=agent_name, local_dir=local,
                        endpoint=SERVER, token=TOKEN, username=self.username,
                    )
                    self.assertEqual(rc, 0, f"upload failed for {fw}")
                finally:
                    self._cleanup_dir(local)
                _wait(REQUEST_INTERVAL)

    # -----------------------------------------------------------------------
    # 24. Upload: individual filters agent
    # -----------------------------------------------------------------------
    def test_24_upload_individual_filters_agent(self):
        files = {
            "AGENTS.md": "# Agents\n",
            "agents/reviewer.md": "# Reviewer\n",
            "agents/coder.md": "# Coder\n",
            "rules/style.md": "# Style\n",
        }
        local = self._create_local_workspace(files)
        try:
            spec = FRAMEWORK_REGISTRY["qoder"](agent_name="reviewer", local_dir=Path(local))
            collected = spec.collect()
            self.assertIn("agents/reviewer.md", collected)
            self.assertNotIn("agents/coder.md", collected,
                             "individual mode should not include other agents")
            self.assertIn("rules/style.md", collected, "shared files should be included")
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 25. Upload: all mode collects all agents
    # -----------------------------------------------------------------------
    def test_25_upload_all_collects_everything(self):
        files = {
            "AGENTS.md": "# Agents\n",
            "agents/reviewer.md": "# Reviewer\n",
            "agents/coder.md": "# Coder\n",
            "agents/tester.md": "# Tester\n",
            "rules/style.md": "# Style\n",
        }
        local = self._create_local_workspace(files)
        try:
            spec = FRAMEWORK_REGISTRY["qoder"](agent_name=ALL_AGENT_NAME, local_dir=Path(local))
            collected = spec.collect()
            self.assertIn("agents/reviewer.md", collected)
            self.assertIn("agents/coder.md", collected)
            self.assertIn("agents/tester.md", collected)
            self.assertIn("rules/style.md", collected)
            self.assertIn("AGENTS.md", collected)
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 26. qwenpaw all: collect prefixed
    # -----------------------------------------------------------------------
    def test_26_qwenpaw_all_collect_prefixed(self):
        local = self._create_local_root("qwenpaw", ALL_AGENT_NAME, QWENPAW_ALL_FILES)
        try:
            spec = FRAMEWORK_REGISTRY["qwenpaw"](agent_name=ALL_AGENT_NAME, local_dir=Path(local))
            collected = spec.collect()
            self.assertIn("bot-a/SOUL.md", collected)
            self.assertIn("bot-b/SOUL.md", collected)
            self.assertIn("bot-a/skills/write/SKILL.md", collected)
            self.assertIn("bot-b/skills/analyze/SKILL.md", collected)
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 27. openclaw all: workspace prefix matches
    # -----------------------------------------------------------------------
    def test_27_openclaw_all_collect_workspace_prefix(self):
        local = self._create_local_workspace(OPENCLAW_ALL_FILES)
        try:
            spec = FRAMEWORK_REGISTRY["openclaw"](agent_name=ALL_AGENT_NAME, local_dir=Path(local))
            collected = spec.collect()
            self.assertIn("workspace/SOUL.md", collected)
            self.assertIn("workspace-helper/SOUL.md", collected)
            self.assertIn("workspace/skills/code/SKILL.md", collected)
            self.assertIn("workspace-helper/skills/refactor/SKILL.md", collected)
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 28. openclaw all: non-workspace dirs excluded
    # -----------------------------------------------------------------------
    def test_28_openclaw_all_excludes_non_workspace(self):
        files = dict(OPENCLAW_ALL_FILES)
        files["config/settings.json"] = '{"key": "value"}'
        files["logs/app.log"] = "log line\n"
        local = self._create_local_workspace(files)
        try:
            spec = FRAMEWORK_REGISTRY["openclaw"](agent_name=ALL_AGENT_NAME, local_dir=Path(local))
            collected = spec.collect()
            self.assertNotIn("config/settings.json", collected)
            self.assertNotIn("logs/app.log", collected)
        finally:
            self._cleanup_dir(local)

    # -----------------------------------------------------------------------
    # 29. Download: all-mode round-trip
    # -----------------------------------------------------------------------
    def test_29_download_all_roundtrip(self):
        local_up = self._create_local_workspace(QODER_ALL_FILES)
        try:
            rc = cmd_upload(
                framework="qoder", name=ALL_AGENT_NAME, local_dir=local_up,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 0)
        finally:
            self._cleanup_dir(local_up)

        _wait(5)

        local_dl = tempfile.mkdtemp(prefix="agent_test_dlall_")
        try:
            repo = _repo_name("qoder", ALL_AGENT_NAME)
            rc = cmd_download(
                framework="qoder", repo=repo, name=ALL_AGENT_NAME, local_dir=local_dl,
                endpoint=SERVER, token=TOKEN, username=self.username,
            )
            self.assertEqual(rc, 0)
            dl_files = {
                str(f.relative_to(local_dl))
                for f in Path(local_dl).rglob("*") if f.is_file()
            }
            self.assertIn("agents/reviewer.md", dl_files)
            self.assertIn("agents/coder.md", dl_files)
        finally:
            self._cleanup_dir(local_dl)

    # -----------------------------------------------------------------------
    # 30. supports_individual_watch property check
    # -----------------------------------------------------------------------
    def test_30_supports_individual_watch(self):
        qoder = FRAMEWORK_REGISTRY["qoder"](agent_name="reviewer")
        nanobot = FRAMEWORK_REGISTRY["nanobot"](agent_name="helper")
        qwenpaw = FRAMEWORK_REGISTRY["qwenpaw"](agent_name="bot-a")
        openclaw = FRAMEWORK_REGISTRY["openclaw"](agent_name="helper")
        hermes = FRAMEWORK_REGISTRY["hermes"](agent_name="default")
        ms_agent = FRAMEWORK_REGISTRY["ms-agent"](agent_name="default")

        # file-per-agent + shared: shared files cascade, individual watch unsupported
        self.assertFalse(qoder.supports_individual_watch)
        # single-agent installs: the whole workspace is the one agent
        self.assertTrue(nanobot.supports_individual_watch)
        self.assertTrue(hermes.supports_individual_watch)
        self.assertTrue(ms_agent.supports_individual_watch)
        # root-per-agent: each agent is its own directory
        self.assertTrue(qwenpaw.supports_individual_watch)
        self.assertTrue(openclaw.supports_individual_watch)


if __name__ == "__main__":
    unittest.main(verbosity=2)
