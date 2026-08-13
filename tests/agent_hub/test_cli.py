# Copyright (c) ModelScope Contributors. All rights reserved.
"""CLI command tests: helper functions, upload/download/convert flows (stubbed client)."""
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from ms_agent.agent_hub._commands import (
    available_frameworks,
    build_spec,
    check_framework,
    cmd_convert,
    cmd_download,
    cmd_list,
    cmd_recover,
    cmd_status,
    cmd_stop,
    cmd_upload,
    cmd_watch,
    repo_name,
    resolve_local_name,
    resolve_remote,
)
from modelscope_hub.agent._api import RemoteFileInfo
from ms_agent.agent_hub._sync import sha256_content


class _RepoStub:
    """Base offline repo stub. Subclasses define ``STORE`` ({path: content});
    this provides the read APIs the download/sync flows call, including
    ``list_repo_files_detail`` (sha256 computed from STORE content).
    """

    STORE: dict = {}

    def repo_info(self, path, name):
        return {"Path": path, "Name": name,
                "Framework": self.FRAMEWORK, "Revision": 1}

    def list_repo_files(self, path, name, revision="master"):
        return list(self.STORE)

    def list_repo_files_detail(self, path, name, revision="master"):
        return [
            RemoteFileInfo(path=p, sha256=sha256_content(c), is_lfs=False)
            for p, c in self.STORE.items()
        ]

    def download_repo_file(self, path, name, file_path, revision="master",
                           *, binary=False):
        # Mirrors the real SDK: binary=True returns raw bytes, the default
        # text mode decodes (and would corrupt non-UTF-8 binary content).
        content = self.STORE[file_path]
        raw = content if isinstance(content, bytes) else content.encode("utf-8")
        return raw if binary else raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestExperimentalFrameworkGate(unittest.TestCase):
    """Only ms-agent / qwenpaw are exposed unless TRY_EXP_FRAMEWORKS is set.

    conftest turns the gate ON for the rest of the suite (the gated frameworks
    still need their regressions), so each test here pins the env var itself
    rather than relying on the ambient value.
    """

    def _clear(self):
        return mock.patch.dict(os.environ, {"TRY_EXP_FRAMEWORKS": ""})

    def _enable(self, value="True"):
        return mock.patch.dict(os.environ, {"TRY_EXP_FRAMEWORKS": value})

    def test_stable_frameworks_always_allowed(self):
        with self._clear():
            for fw in ("ms-agent", "qwenpaw"):
                self.assertIsNone(check_framework(fw))

    def test_gated_frameworks_rejected_by_default(self):
        with self._clear():
            for fw in ("qoder", "hermes", "nanobot", "openclaw", "openhuman"):
                err = check_framework(fw)
                self.assertIsNotNone(err, f"{fw} should be gated by default")
                # points at the opt-in, and does not pretend the name is bogus
                self.assertIn("TRY_EXP_FRAMEWORKS", err)
                self.assertNotIn("unknown", err)

    def test_gated_frameworks_allowed_when_enabled(self):
        for value in ("True", "true", "1", "yes", "on"):
            with self._enable(value):
                self.assertIsNone(
                    check_framework("qoder"), f"{value!r} should enable")

    def test_falsy_values_keep_gate_closed(self):
        for value in ("", "false", "0", "no"):
            with self._enable(value):
                self.assertIsNotNone(
                    check_framework("qoder"), f"{value!r} must not enable")

    def test_unknown_framework_is_reported_as_unknown(self):
        for ctx in (self._clear(), self._enable()):
            with ctx:
                err = check_framework("bogus")
                self.assertIn("unknown", err)
                self.assertNotIn("TRY_EXP_FRAMEWORKS", err)

    def test_available_frameworks_reflects_the_gate(self):
        with self._clear():
            self.assertEqual(available_frameworks(), "ms-agent, qwenpaw")
        with self._enable():
            listed = available_frameworks()
            for fw in ("qoder", "hermes", "ms-agent", "qwenpaw"):
                self.assertIn(fw, listed)

    def test_commands_exit_nonzero_for_gated_framework(self):
        with self._clear():
            with mock.patch("sys.stderr", new=io.StringIO()) as err:
                self.assertEqual(cmd_status("qoder"), 1)
            self.assertIn("TRY_EXP_FRAMEWORKS", err.getvalue())


class TestRepoName(unittest.TestCase):
    def test_both_fw_and_name(self):
        self.assertEqual(repo_name("qoder", "reviewer"), "qoder-reviewer")

    def test_name_all(self):
        self.assertEqual(repo_name("qoder", "all"), "qoder")

    def test_fw_only(self):
        self.assertEqual(repo_name("qoder", ""), "qoder")

    def test_name_only(self):
        self.assertEqual(repo_name("", "mybot"), "mybot")

    def test_neither(self):
        self.assertEqual(repo_name("", ""), "default")


class TestResolveRemote(unittest.TestCase):
    def test_repo_with_slash(self):
        group, name = resolve_remote(repo="org/myrepo", username="u")
        self.assertEqual(group, "org")
        self.assertEqual(name, "myrepo")

    def test_repo_without_slash(self):
        group, name = resolve_remote(repo="myrepo", username="u")
        self.assertEqual(group, "u")
        self.assertEqual(name, "myrepo")

    def test_no_repo_derives(self):
        group, name = resolve_remote(name="bot", framework="qoder", username="u")
        self.assertEqual(group, "u")
        self.assertEqual(name, "qoder-bot")


class TestResolveLocalName(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_name_passes_through(self):
        name, err = resolve_local_name("reviewer", "qoder", self.root)
        self.assertEqual(name, "reviewer")
        self.assertIsNone(err)

    def test_single_agent_auto_select(self):
        (self.root / "agents").mkdir()
        (self.root / "agents" / "mybot.md").write_text("x")
        name, err = resolve_local_name(None, "qoder", self.root)
        self.assertEqual(name, "mybot")
        self.assertIsNone(err)

    def test_multiple_agents_error(self):
        (self.root / "agents").mkdir()
        (self.root / "agents" / "a.md").write_text("x")
        (self.root / "agents" / "b.md").write_text("y")
        name, err = resolve_local_name(None, "qoder", self.root)
        self.assertIsNone(name)
        self.assertIn("multiple", err)

    def test_root_per_agent_omitted_name_is_default(self):
        # qwenpaw is root-per-agent (no {name} placeholder): an omitted --name
        # ALWAYS resolves to 'default', never auto-selecting or erroring on
        # sibling sub-agents (bot-a/bot-b).  Regression for the upload bug.
        name, err = resolve_local_name(None, "qwenpaw", self.root)
        self.assertEqual(name, "default")
        self.assertIsNone(err)

    def test_single_agent_layout_omitted_name_is_default(self):
        # single-agent frameworks (hermes) resolve omitted --name to default too.
        name, err = resolve_local_name(None, "hermes", self.root)
        self.assertEqual(name, "default")
        self.assertIsNone(err)

    def test_all_name_passes_through(self):
        name, err = resolve_local_name("all", "qwenpaw", self.root)
        self.assertEqual(name, "all")
        self.assertIsNone(err)

    def test_explicit_bot_name_passes_through(self):
        name, err = resolve_local_name("bot-a", "qwenpaw", self.root)
        self.assertEqual(name, "bot-a")
        self.assertIsNone(err)


# ---------------------------------------------------------------------------
# Status command tests
# ---------------------------------------------------------------------------


class TestStatusCmd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "agents").mkdir()
        (self.root / "agents" / "reviewer.md").write_text("reviewer")
        (self.root / "agents" / "coder.md").write_text("coder")
        (self.root / "AGENTS.md").write_text("shared")

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_shows_agents(self):
        rc = cmd_status(framework="qoder", local_dir=str(self.root))
        self.assertEqual(rc, 0)

    def test_status_unknown_framework_fails(self):
        rc = cmd_status(framework="nope", local_dir=str(self.root))
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# Upload command tests (stubbed client)
# ---------------------------------------------------------------------------


class _StubClient:
    """Records calls so the test can assert the upload flow."""

    instances = []

    # Subclasses/tests may set this to simulate pre-existing remote files.
    preset_remote = []

    # Metadata returned by ``repo_info`` for the post-create visibility
    # read-back. Default ``{}`` (unknown) makes verification proceed, matching
    # every existing upload test; a test can set ``{"private": False}`` to
    # simulate the server ignoring a private request.
    preset_repo_info = {}

    def __init__(self, *args, **kwargs):
        self.created = []
        self.created_visibility = []
        self.committed_actions = []
        self.uploaded_resources = None
        self.lfs_uploads = []
        self.deleted = []
        _StubClient.instances.append(self)

    def check_repo(self, path, name):
        return False

    def repo_info(self, path, name):
        return type(self).preset_repo_info

    def list_repo_files(self, path, name, revision="master"):
        return list(type(self).preset_remote)

    def delete_file(self, path, name, file_path, **kwargs):
        self.deleted.append(file_path)
        return {"success": True}

    def create_repo(self, path, name, framework=None, visibility="public"):
        self.created.append((path, name, framework))
        self.created_visibility.append(visibility)
        return {"success": True}

    def commit_files(self, path, name, actions, **kwargs):
        self.committed_actions.extend(actions)
        # Track resources from the actions for assertions.
        if self.uploaded_resources is None:
            self.uploaded_resources = {}
        import base64
        for a in actions:
            if a.get("encoding") == "base64" and a.get("content"):
                self.uploaded_resources[a["path"]] = base64.b64decode(a["content"])
        return {"success": True}

    def upload_lfs_file(self, path, name, file_path, content, **kwargs):
        self.lfs_uploads.append((file_path, content))
        if self.uploaded_resources is None:
            self.uploaded_resources = {}
        self.uploaded_resources[file_path] = content
        return {"success": True}


class TestUploadCmd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "agents").mkdir()
        (self.root / "agents" / "reviewer.md").write_text("reviewer")
        (self.root / "AGENTS.md").write_text("shared")
        (self.root / "skills" / "test-skill").mkdir(parents=True)
        (self.root / "skills" / "test-skill" / "SKILL.md").write_text("skill")
        _StubClient.instances = []

    def tearDown(self):
        self.tmp.cleanup()

    def test_unknown_framework_fails(self):
        rc = cmd_upload(framework="nope", name="x", local_dir=str(self.root))
        self.assertEqual(rc, 1)

    def test_dry_run_does_not_upload(self):
        rc = cmd_upload(
            framework="qoder", name="reviewer",
            local_dir=str(self.root), dry_run=True,
        )
        self.assertEqual(rc, 0)
        self.assertEqual(_StubClient.instances, [])

    def test_no_files_fails(self):
        rc = cmd_upload(
            framework="qoder", name="ghost",
            local_dir=str(self.root / "empty"),
        )
        self.assertEqual(rc, 1)

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_full_upload_creates_then_uploads_zip(self):
        rc = cmd_upload(
            framework="qoder", name="reviewer",
            local_dir=str(self.root),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(len(_StubClient.instances), 1)
        client = _StubClient.instances[0]
        # create_repo called with (group, repo_name)
        self.assertEqual(len(client.created), 1)
        self.assertEqual(client.created[0], ("u", "qoder-reviewer", "qoder"))
        # Verify uploaded resources are bytes-valued dict
        self.assertIsNotNone(client.uploaded_resources)
        self.assertIsInstance(client.uploaded_resources, dict)
        self.assertIn("agents/reviewer.md", client.uploaded_resources)
        self.assertIn("AGENTS.md", client.uploaded_resources)
        for v in client.uploaded_resources.values():
            self.assertIsInstance(v, bytes)

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_private_request_honored_proceeds(self):
        """Server confirms private -> upload proceeds normally."""
        _StubClient.preset_repo_info = {"private": True}
        try:
            rc = cmd_upload(
                framework="qoder", name="reviewer",
                local_dir=str(self.root),
                endpoint="http://s", token="tok", username="u",
                visibility="private",
            )
        finally:
            _StubClient.preset_repo_info = {}
        self.assertEqual(rc, 0)
        client = _StubClient.instances[0]
        self.assertEqual(client.created_visibility, ["private"])
        self.assertIsNotNone(client.uploaded_resources)

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_private_request_created_public_aborts_before_upload(self):
        """Server ignored private (repo is public) -> abort, nothing uploaded.

        Regression: this used to log a cheerful "private" success while the
        repo was public -- a silent leak with exit code 0.
        """
        _StubClient.preset_repo_info = {"private": False}
        try:
            rc = cmd_upload(
                framework="qoder", name="reviewer",
                local_dir=str(self.root),
                endpoint="http://s", token="tok", username="u",
                visibility="private",
            )
        finally:
            _StubClient.preset_repo_info = {}
        self.assertEqual(rc, 1)  # non-zero: the failure is observable on CLI
        client = _StubClient.instances[0]
        # Repo was created, but NO content was pushed after the mismatch.
        self.assertEqual(client.created_visibility, ["private"])
        self.assertIsNone(client.uploaded_resources)

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_unverifiable_visibility_proceeds(self):
        """Metadata unreadable -> proceed rather than block a real upload."""
        _StubClient.preset_repo_info = {}  # unknown
        rc = cmd_upload(
            framework="qoder", name="reviewer",
            local_dir=str(self.root),
            endpoint="http://s", token="tok", username="u",
            visibility="private",
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(_StubClient.instances[0].uploaded_resources)

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_full_upload_prunes_stale_remote_in_scope(self):
        """Mirror semantics: remote files in scope but not local are deleted."""
        # Remote has a stale skill (in scope, no local match) plus a file
        # belonging to a DIFFERENT sub-agent (agents/other.md, out of scope).
        _StubClient.preset_remote = [
            "AGENTS.md",                       # will be re-uploaded (kept)
            "agents/reviewer.md",              # re-uploaded (kept)
            "skills/stale-skill/SKILL.md",     # stale, in scope -> DELETE
            "agents/other.md",                 # other sub-agent -> KEEP
        ]
        try:
            rc = cmd_upload(
                framework="qoder", name="reviewer",
                local_dir=str(self.root),
                endpoint="http://s", token="tok", username="u",
            )
        finally:
            _StubClient.preset_remote = []
        self.assertEqual(rc, 0)
        client = _StubClient.instances[0]
        # The stale in-scope skill is pruned.
        self.assertIn("skills/stale-skill/SKILL.md", client.deleted)
        # The other sub-agent's file is out of scope and preserved.
        self.assertNotIn("agents/other.md", client.deleted)
        # Files re-uploaded this run are never deleted.
        self.assertNotIn("AGENTS.md", client.deleted)
        self.assertNotIn("agents/reviewer.md", client.deleted)

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_full_upload_no_prune_when_remote_clean(self):
        """No deletes when remote has nothing beyond the uploaded set."""
        _StubClient.preset_remote = ["AGENTS.md", "agents/reviewer.md"]
        try:
            rc = cmd_upload(
                framework="qoder", name="reviewer",
                local_dir=str(self.root),
                endpoint="http://s", token="tok", username="u",
            )
        finally:
            _StubClient.preset_remote = []
        self.assertEqual(rc, 0)
        client = _StubClient.instances[0]
        self.assertEqual(client.deleted, [])

    def test_upload_without_login_fails(self):
        rc = cmd_upload(
            framework="qoder", name="reviewer",
            local_dir=str(self.root),
            endpoint=None, token=None,
        )
        self.assertEqual(rc, 1)

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_upload_multiple_agents_no_name_fails(self):
        """When --name is not specified and multiple agents exist, should fail."""
        (self.root / "agents" / "coder.md").write_text("coder")
        rc = cmd_upload(
            framework="qoder", name=None,
            local_dir=str(self.root),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 1)

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_upload_auto_select_single_agent(self):
        """When only one sub-agent exists, auto-select it without --name."""
        rc = cmd_upload(
            framework="qoder", name=None,
            local_dir=str(self.root),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        client = _StubClient.instances[0]
        self.assertEqual(client.created[0][1], "qoder-reviewer")

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_upload_with_repo_slash(self):
        """--repo with '/' should use the group from repo, not username."""
        rc = cmd_upload(
            framework="qoder", name="reviewer",
            repo="mygroup/myrepo",
            local_dir=str(self.root),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        client = _StubClient.instances[0]
        self.assertEqual(client.created[0][0], "mygroup")
        self.assertEqual(client.created[0][1], "myrepo")

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_upload_repo_defaults_to_name(self):
        """When --repo is omitted, remote repo name derives from --name."""
        rc = cmd_upload(
            framework="qoder", name="reviewer",
            local_dir=str(self.root),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        client = _StubClient.instances[0]
        self.assertEqual(client.created[0][0], "u")
        self.assertEqual(client.created[0][1], "qoder-reviewer")

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_upload_default_visibility_public(self):
        """create_repo defaults to public visibility when not specified."""
        rc = cmd_upload(
            framework="qoder", name="reviewer",
            local_dir=str(self.root),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        client = _StubClient.instances[0]
        self.assertEqual(client.created_visibility, ["public"])

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_upload_visibility_private_forwarded(self):
        """visibility='private' is threaded through to create_repo."""
        rc = cmd_upload(
            framework="qoder", name="reviewer",
            local_dir=str(self.root), visibility="private",
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        client = _StubClient.instances[0]
        self.assertEqual(client.created_visibility, ["private"])

    def test_create_repo_sends_boolean_private_not_visibility(self):
        """The agent API takes a boolean ``private`` (inverted), not the old
        ``visibility`` string: a string is rejected 400 by the server, and a
        missing field silently defaults to public. The caller-facing label
        stays ``public``/``private`` on purpose."""
        from modelscope_hub.agent import AgentApi

        sent = {}

        class _FakeOpenApi:

            def request(self, method, path=None, **kw):
                sent.clear()
                sent.update(kw.get("json_body") or {})
                return {}

        api = AgentApi.__new__(AgentApi)
        api._openapi = _FakeOpenApi()

        AgentApi.create_repo(api, "grp", "a", visibility="private")
        self.assertEqual(sent["private"], True)
        self.assertNotIn("visibility", sent)

        AgentApi.create_repo(api, "grp", "b")  # default public
        self.assertEqual(sent["private"], False)
        self.assertIsInstance(sent["private"], bool)
        self.assertNotIn("visibility", sent)

        with self.assertRaises(ValueError):
            AgentApi.create_repo(api, "grp", "c", visibility="Public")

    def test_agent_field_readers_handle_renamed_and_legacy_keys(self):
        """``private`` is an INVERTED boolean, so ``private=False`` (public)
        must not be swallowed by a falsy ``or``-chain; the renamed time field
        and the legacy spellings are both accepted."""
        from modelscope_hub.agent import (agent_last_modified,
                                          agent_visibility_label)
        self.assertEqual(agent_visibility_label({"private": False}), "public")
        self.assertEqual(agent_visibility_label({"Private": False}), "public")
        self.assertEqual(agent_visibility_label({"private": True}), "private")
        self.assertEqual(agent_visibility_label({"Private": True}), "private")
        # legacy servers still send the string form, in any casing / with
        # padding / as the int enum or its numeric string
        self.assertEqual(
            agent_visibility_label({"Visibility": "private"}), "private")
        self.assertEqual(
            agent_visibility_label({"Visibility": "Public"}), "public")
        self.assertEqual(
            agent_visibility_label({"visibility": "PRIVATE"}), "private")
        self.assertEqual(
            agent_visibility_label({"Visibility": "  public  "}), "public")
        self.assertEqual(agent_visibility_label({"Visibility": 5}), "public")
        self.assertEqual(agent_visibility_label({"Visibility": 1}), "private")
        self.assertEqual(agent_visibility_label({"Visibility": "5"}), "public")
        # new field wins over a stale legacy one
        self.assertEqual(
            agent_visibility_label({"private": False, "Visibility": "private"}),
            "public")
        # unknown / empty values are never guessed into "private"
        self.assertEqual(agent_visibility_label({"Visibility": "weird"}),
                         "weird")
        self.assertEqual(agent_visibility_label({"Visibility": ""}), "-")
        self.assertEqual(agent_visibility_label({}), "-")

        self.assertEqual(
            agent_last_modified({"LastModified": "2026-07-16T10:30:00Z"}),
            "2026-07-16T10:30:00Z")
        self.assertEqual(
            agent_last_modified({"GmtModified": "2026-07-16T18:30:00+08:00"}),
            "2026-07-16T18:30:00+08:00")
        self.assertEqual(agent_last_modified({}), "-")

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_upload_global_only_no_agents_dir(self):
        """When no agents/ directory exists, upload only shared (global) files."""
        import shutil
        shutil.rmtree(self.root / "agents")
        rc = cmd_upload(
            framework="qoder", name=None,
            local_dir=str(self.root),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        client = _StubClient.instances[0]
        # Repo should be "qoder" (no name specified, global mode).
        self.assertEqual(client.created[0][1], "qoder")
        # Verify that no agents/*.md files are uploaded.
        self.assertIsNotNone(client.uploaded_resources)
        for p in client.uploaded_resources.keys():
            self.assertFalse(p.startswith("agents/"))


# ---------------------------------------------------------------------------
# Backup/restore tests
# ---------------------------------------------------------------------------


class TestBackupsFilterCmd(unittest.TestCase):
    """Test backup list/restore framework and name filtering."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Create fake backup zips in a temp cache dir.
        self.cache_dir = Path(self.tmp.name)
        for name in [
            "qoder_default_20260624_120000.zip",
            "qoder_reviewer_20260624_130000.zip",
            "qwenpaw_default_20260702_170208.zip",
            "nanobot_mybot_20260703_100000.zip",
        ]:
            zpath = self.cache_dir / name
            with zipfile.ZipFile(zpath, 'w') as zf:
                zf.writestr("dummy.txt", "placeholder")

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("ms_agent.agent_hub._cache.cache_dir")
    def test_backups_list_all(self, mock_cache):
        """Without --framework, list all backups."""
        mock_cache.return_value = self.cache_dir
        rc = cmd_recover(list_backups=True)
        self.assertEqual(rc, 0)

    @mock.patch("ms_agent.agent_hub._cache.cache_dir")
    def test_backups_list_filter_by_framework(self, mock_cache):
        """With --framework qoder, only qoder backups appear."""
        mock_cache.return_value = self.cache_dir
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_recover(list_backups=True, framework="qoder")
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("qoder_default_20260624_120000.zip", output)
        self.assertIn("qoder_reviewer_20260624_130000.zip", output)
        self.assertNotIn("qwenpaw", output)
        self.assertNotIn("nanobot", output)

    @mock.patch("ms_agent.agent_hub._cache.cache_dir")
    def test_backups_list_filter_by_name(self, mock_cache):
        """With --name reviewer, only matching backups appear."""
        mock_cache.return_value = self.cache_dir
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_recover(list_backups=True, name="reviewer")
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("qoder_reviewer_20260624_130000.zip", output)
        self.assertNotIn("qoder_default", output)
        self.assertNotIn("qwenpaw", output)

    @mock.patch("ms_agent.agent_hub._cache.cache_dir")
    def test_backups_list_no_match(self, mock_cache):
        """Filter with nonexistent framework returns 'No backups found'."""
        mock_cache.return_value = self.cache_dir
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_recover(list_backups=True, framework="hermes")
        self.assertEqual(rc, 0)
        self.assertIn("No backups found", buf.getvalue())

    @mock.patch("ms_agent.agent_hub._cache.cache_dir")
    def test_restore_last_filters_by_framework(self, mock_cache):
        """'restore last -f qoder' picks the latest qoder backup."""
        mock_cache.return_value = self.cache_dir
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_recover(target="last", framework="qoder")
        # rc=1 because the fake zip doesn't have valid data to restore,
        # but it should attempt the qoder_reviewer (latest qoder) not qwenpaw.
        self.assertNotIn("no backups found", buf.getvalue().lower())

    @mock.patch("ms_agent.agent_hub._cache.cache_dir")
    def test_restore_last_no_match_fails(self, mock_cache):
        """'restore last -f hermes' with no hermes backups should fail."""
        mock_cache.return_value = self.cache_dir
        rc = cmd_recover(target="last", framework="hermes")
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# Restore *behaviour* tests: actual delete + extract, scoped per backup.
# These cover cmd_recover's core restore path (previously untested) and lock
# the P0 regression where a single-agent restore wiped sibling agents because
# the scope was hardcoded to "all".
# ---------------------------------------------------------------------------


class TestRestoreBehaviour(unittest.TestCase):
    """Exercise cmd_recover's delete-extra + extract logic against a real
    on-disk workspace, asserting the restore is scoped to the backup's agent.

    NOTE: these deliberately do NOT pass ``local_dir`` -- an explicit override
    makes ``workspace_root`` ignore ``agent_name`` entirely, which would bypass
    the exact scoping logic under test.  Instead we redirect ``Path.home()`` to
    a temp dir so qwenpaw resolves to ``{home}/.qwenpaw/workspaces[/<agent>]``
    just like in production.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.cache_dir = Path(self.tmp.name) / "cache"
        self.cache_dir.mkdir()
        # qwenpaw all-root workspace with three sibling agents on disk.
        self.ws = self.home / ".qwenpaw" / "workspaces"
        for agent in ("default", "bot-a", "bot-b"):
            d = self.ws / agent
            d.mkdir(parents=True)
            (d / "SOUL.md").write_text(f"# Soul\n{agent} original.\n")
            (d / "PROFILE.md").write_text(f"# Profile\n{agent} profile.\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _make_backup(self, stem: str, files: dict) -> Path:
        """Write a backup zip {rel: content} into the cache dir."""
        zpath = self.cache_dir / f"{stem}.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            for rel, content in files.items():
                zf.writestr(rel, content)
        return zpath

    def _read(self, agent: str, fname: str):
        f = self.ws / agent / fname
        return f.read_text() if f.exists() else None

    @mock.patch("pathlib.Path.home")
    @mock.patch("ms_agent.agent_hub._sync.cache_dir")
    @mock.patch("ms_agent.agent_hub._cache.cache_dir")
    def test_restore_single_agent_does_not_wipe_siblings(self, mock_cache, mock_sync_cache, mock_home):
        """P0 regression: restoring a single-agent (default) backup must NOT
        delete or touch sibling agents bot-a / bot-b."""
        mock_cache.return_value = self.cache_dir
        mock_sync_cache.return_value = self.cache_dir
        mock_home.return_value = self.home
        # A watch-style single-agent backup: bare (unprefixed) paths for default.
        self._make_backup(
            "qwenpaw_default_20260702_170208",
            {"SOUL.md": "# Soul\ndefault restored.\n"},
        )
        rc = cmd_recover(target="qwenpaw_default_20260702_170208")
        self.assertEqual(rc, 0)
        # default restored from the zip.
        self.assertEqual(self._read("default", "SOUL.md"), "# Soul\ndefault restored.\n")
        # siblings untouched -- the whole point of the fix.
        self.assertEqual(self._read("bot-a", "SOUL.md"), "# Soul\nbot-a original.\n")
        self.assertEqual(self._read("bot-a", "PROFILE.md"), "# Profile\nbot-a profile.\n")
        self.assertEqual(self._read("bot-b", "SOUL.md"), "# Soul\nbot-b original.\n")

    @mock.patch("pathlib.Path.home")
    @mock.patch("ms_agent.agent_hub._sync.cache_dir")
    @mock.patch("ms_agent.agent_hub._cache.cache_dir")
    def test_restore_removes_extra_files_within_same_agent(self, mock_cache, mock_sync_cache, mock_home):
        """Files present locally but absent from the (same-agent) backup are
        removed -- but only within the restored agent's own directory."""
        mock_cache.return_value = self.cache_dir
        mock_sync_cache.return_value = self.cache_dir
        mock_home.return_value = self.home
        # backup has only SOUL.md -> local default/PROFILE.md is 'extra'.
        self._make_backup(
            "qwenpaw_default_20260702_170208",
            {"SOUL.md": "# Soul\ndefault restored.\n"},
        )
        rc = cmd_recover(target="qwenpaw_default_20260702_170208")
        self.assertEqual(rc, 0)
        # extra file within default is removed.
        self.assertIsNone(self._read("default", "PROFILE.md"))
        # but sibling PROFILE.md files survive.
        self.assertEqual(self._read("bot-a", "PROFILE.md"), "# Profile\nbot-a profile.\n")

    @mock.patch("pathlib.Path.home")
    @mock.patch("ms_agent.agent_hub._sync.cache_dir")
    @mock.patch("ms_agent.agent_hub._cache.cache_dir")
    def test_restore_all_scope_backup_uses_prefixed_paths(self, mock_cache, mock_sync_cache, mock_home):
        """An all-scope backup (name-less filename, agent-prefixed entries)
        restores across every agent directory."""
        mock_cache.return_value = self.cache_dir
        mock_sync_cache.return_value = self.cache_dir
        mock_home.return_value = self.home
        # all-scope backup: filename has no name segment; entries are prefixed.
        self._make_backup(
            "qwenpaw_20260702_170208",
            {
                "default/SOUL.md": "# Soul\ndefault all-restored.\n",
                "bot-a/SOUL.md": "# Soul\nbot-a all-restored.\n",
                "bot-b/SOUL.md": "# Soul\nbot-b all-restored.\n",
            },
        )
        rc = cmd_recover(target="qwenpaw_20260702_170208")
        self.assertEqual(rc, 0)
        # every agent restored from its prefixed entry.
        self.assertEqual(self._read("default", "SOUL.md"), "# Soul\ndefault all-restored.\n")
        self.assertEqual(self._read("bot-a", "SOUL.md"), "# Soul\nbot-a all-restored.\n")
        self.assertEqual(self._read("bot-b", "SOUL.md"), "# Soul\nbot-b all-restored.\n")

    @mock.patch("pathlib.Path.home")
    @mock.patch("ms_agent.agent_hub._sync.cache_dir")
    @mock.patch("ms_agent.agent_hub._cache.cache_dir")
    def test_pre_restore_backup_has_framework_prefix(self, mock_cache, mock_sync_cache, mock_home):
        """The automatic pre-restore backup must follow the shared naming
        convention ``{fw}_{name}_{date}_{time}.zip`` so ``backups -f <fw>``
        can find it (bug: it was named ``{name}_...`` and got parsed as
        framework='paw' for name='paw_qa_01')."""
        mock_cache.return_value = self.cache_dir
        mock_sync_cache.return_value = self.cache_dir
        mock_home.return_value = self.home
        # agent whose name contains '_' -- the original mis-parse trigger.
        agent_dir = self.ws / "paw_qa_01"
        agent_dir.mkdir()
        (agent_dir / "SOUL.md").write_text("# Soul\ncurrent state.\n")
        self._make_backup(
            "qwenpaw_paw_qa_01_20260702_170208",
            {"SOUL.md": "# Soul\nfrom backup.\n"},
        )
        rc = cmd_recover(target="last", framework="qwenpaw", name="paw_qa_01")
        self.assertEqual(rc, 0)
        pre = [
            f for f in self.cache_dir.glob("*.zip")
            if f.stem != "qwenpaw_paw_qa_01_20260702_170208"
        ]
        self.assertEqual(len(pre), 1, "exactly one pre-restore backup expected")
        # named like every other backup: framework prefix + agent name.
        self.assertTrue(
            pre[0].name.startswith("qwenpaw_paw_qa_01_"),
            f"pre-restore backup misnamed: {pre[0].name}")
        # and the backups -f filter parses the right framework out of it.
        from ms_agent.agent_hub._commands import _parse_backup_meta
        fw, nm = _parse_backup_meta(pre[0].stem)
        self.assertEqual(fw, "qwenpaw")

    @mock.patch("pathlib.Path.home")
    @mock.patch("ms_agent.agent_hub._sync.cache_dir")
    @mock.patch("ms_agent.agent_hub._cache.cache_dir")
    def test_pre_restore_backup_all_scope_uses_framework_only(self, mock_cache, mock_sync_cache, mock_home):
        """Restoring an all-scope backup names its pre-restore backup
        ``{fw}_{date}_{time}.zip`` (no name segment), matching the all-scope
        convention."""
        mock_cache.return_value = self.cache_dir
        mock_sync_cache.return_value = self.cache_dir
        mock_home.return_value = self.home
        self._make_backup(
            "qwenpaw_20260702_170208",
            {"default/SOUL.md": "# Soul\nall restored.\n"},
        )
        rc = cmd_recover(target="qwenpaw_20260702_170208")
        self.assertEqual(rc, 0)
        pre = [
            f for f in self.cache_dir.glob("*.zip")
            if f.stem != "qwenpaw_20260702_170208"
        ]
        self.assertEqual(len(pre), 1)
        from ms_agent.agent_hub._commands import _parse_backup_meta
        fw, nm = _parse_backup_meta(pre[0].stem)
        self.assertEqual(fw, "qwenpaw")
        self.assertEqual(nm, "")

    @mock.patch("pathlib.Path.home")
    @mock.patch("ms_agent.agent_hub._sync.cache_dir")
    @mock.patch("ms_agent.agent_hub._cache.cache_dir")
    def test_restore_untrusted_zip_filtered_and_sanitized(self, mock_cache, mock_sync_cache, mock_home):
        """Regression (BUG-013): restore must apply the same inbound rules as
        download -- spec filtering (no foreign scripts / hidden credential
        files written) plus inbound sanitize (no plaintext keys on disk)."""
        mock_cache.return_value = self.cache_dir
        mock_sync_cache.return_value = self.cache_dir
        mock_home.return_value = self.home
        agent_dir = self.ws / "bot-x"
        agent_dir.mkdir()
        self._make_backup(
            "qwenpaw_bot-x_20260726_090000",
            {
                "SOUL.md": "# soul\nrestored.\n",
                "agent.json": '{"id": "bot-x", "model": '
                              '{"api_key": "SENTINEL-BUG013-KEY"}}',
                "run_me.sh": "#!/bin/sh\necho pwned\n",
                ".hidden_token": "SENTINEL-BUG013-SECRET\n",
                "../escape.md": "outside\n",
            },
        )
        rc = cmd_recover(target="qwenpaw_bot-x_20260726_090000",
                         framework="qwenpaw", name="bot-x")
        self.assertEqual(rc, 0)
        written = {p.name for p in agent_dir.rglob("*") if p.is_file()}
        # spec-listed files restored; foreign files rejected.
        self.assertIn("SOUL.md", written)
        self.assertNotIn("run_me.sh", written)
        self.assertNotIn(".hidden_token", written)
        self.assertNotIn("escape.md", written)
        # inbound sanitize ran: the plaintext key never reached disk.
        self.assertNotIn("SENTINEL-BUG013-KEY",
                         (agent_dir / "agent.json").read_text())

    def test_backup_meta_anchors_on_registered_framework_names(self):
        """Regression (BUG-032): 'ms-agent' contains the '-' delimiter, so
        parsing must anchor on registered framework names (longest first)
        instead of splitting on the first delimiter."""
        from ms_agent.agent_hub._commands import _parse_backup_meta
        cases = {
            "ms-agent-default_20260726_101010": ("ms-agent", "default"),
            "ms-agent_20260726_101010": ("ms-agent", ""),
            "ms-agent_default_20260726_101010": ("ms-agent", "default"),
            "nanobot_default_20260726_101010": ("nanobot", "default"),
            "qwenpaw_paw_qa_01_20260726_101010": ("qwenpaw", "paw_qa_01"),
            "nanobot_default_20260731_133225-2": ("nanobot", "default"),
            "unknownfw_myname_20260726_101010": ("unknownfw", "myname"),
        }
        for stem, expected in cases.items():
            self.assertEqual(_parse_backup_meta(stem), expected, stem)

    @mock.patch("ms_agent.agent_hub._sync.cache_dir")
    def test_same_second_backups_do_not_overwrite(self, mock_sync_cache):
        """Regression (BUG-031): two backups within the same second must get
        distinct filenames (``-N`` inside the time segment), keeping every
        restore point, and the suffix must not break filename parsing."""
        import io
        import zipfile as zf

        from ms_agent.agent_hub._commands import _parse_backup_meta
        from ms_agent.agent_hub._sync import backup_local
        cache = Path(self.tmp.name) / "bk_cache"
        cache.mkdir(exist_ok=True)
        mock_sync_cache.return_value = cache
        root = Path(self.tmp.name) / "bk_ws"
        root.mkdir()
        (root / "SOUL.md").write_text("V1\n")
        spec = build_spec("nanobot", "default", str(root))
        p1 = backup_local(spec, "nanobot_default")
        (root / "SOUL.md").write_text("V2\n")
        p2 = backup_local(spec, "nanobot_default")
        self.assertNotEqual(p1, p2)
        v1 = zf.ZipFile(io.BytesIO(p1.read_bytes())).read("SOUL.md").decode()
        self.assertEqual(v1.strip(), "V1")  # first restore point intact
        self.assertEqual(_parse_backup_meta(p2.stem), ("nanobot", "default"))

    @mock.patch("pathlib.Path.home")
    @mock.patch("ms_agent.agent_hub._sync.cache_dir")
    @mock.patch("ms_agent.agent_hub._cache.cache_dir")
    def test_restore_corrupt_zip_fails_cleanly(self, mock_cache, mock_sync_cache, mock_home):
        """Regression (BUG-019): a corrupt / non-zip backup crashed with a
        raw BadZipFile traceback. It must _fail with a readable message and
        must not touch the workspace (no pre-restore backup, no deletes)."""
        mock_cache.return_value = self.cache_dir
        mock_sync_cache.return_value = self.cache_dir
        mock_home.return_value = self.home
        agent_dir = self.ws / "bot-x"
        agent_dir.mkdir()
        (agent_dir / "SOUL.md").write_text("# existing")
        bad = self.cache_dir / "qwenpaw_bot-x_20260726_090000.zip"
        bad.write_text("NOT-A-ZIP")
        rc = cmd_recover(target=bad.name, framework="qwenpaw", name="bot-x")
        self.assertEqual(rc, 1)
        self.assertEqual((agent_dir / "SOUL.md").read_text(), "# existing")
        # No pre-restore backup was produced before the rejection.
        self.assertEqual(list(self.cache_dir.glob("*.zip")), [bad])


# ---------------------------------------------------------------------------
# Download command tests (stubbed client)
# ---------------------------------------------------------------------------


class _DownloadStub(_RepoStub):
    """Serves a fixed nanobot repo so download flows can be exercised offline."""

    FRAMEWORK = "nanobot"
    instances = []
    STORE = {"SOUL.md": "soul", "USER.md": "user", "memory/MEMORY.md": "mem"}

    def __init__(self, *args, **kwargs):
        _DownloadStub.instances.append(self)


class _QwenpawAllStub(_RepoStub):
    """Serves a qwenpaw all-mode repo (agent-prefixed paths) for convert tests."""

    FRAMEWORK = "qwenpaw"
    instances = []
    STORE = {
        ".gitattributes": "x",
        "README.md": "readme",
        "default/AGENTS.md": "# default agents",
        "default/SOUL.md": "# default soul",
        "bot-a/AGENTS.md": "# bot-a agents",
        "bot-a/SOUL.md": "# bot-a soul",
        "bot-a/PROFILE.md": "# bot-a profile",
    }

    def __init__(self, *args, **kwargs):
        _QwenpawAllStub.instances.append(self)


class _HermesAllStub(_RepoStub):
    """Serves a hermes repo uploaded with ``-n all``: default agent at bare
    paths + named agent under ``profiles/coder/`` (bug: download -n coder
    used to write default's files into coder and drop coder's own)."""

    FRAMEWORK = "hermes"
    instances = []
    STORE = {
        "SOUL.md": "# default soul",
        "config.yaml": "model: default-model",
        "memories/2026-07-20.md": "default mem",
        "skills/daily-ai-news/SKILL.md": "default skill",
        "hooks/session_start.sh": "echo hook",
        "optional-skills/git-helper/SKILL.md": "default opt skill",
        "profiles/coder/SOUL.md": "# coder soul",
        "profiles/coder/memories/2026-07-26.md": "coder mem",
        "profiles/coder/skills/code-review/SKILL.md": "coder skill",
    }

    def __init__(self, *args, **kwargs):
        _HermesAllStub.instances.append(self)


class TestDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "ws"
        _DownloadStub.instances = []
        _QwenpawAllStub.instances = []

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _DownloadStub)
    def test_download_writes_files(self):
        rc = cmd_download(
            framework="nanobot", repo="nano",
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        self.assertEqual((self.out / "SOUL.md").read_text(), "soul")
        self.assertEqual((self.out / "memory" / "MEMORY.md").read_text(), "mem")

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _DownloadStub)
    def test_download_with_conversion(self):
        # nanobot -> hermes: USER.md must land at hermes' memories/USER.md.
        rc = cmd_download(
            framework="nanobot", repo="nano",
            target="hermes", local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        self.assertTrue((self.out / "memories" / "USER.md").is_file())
        self.assertFalse((self.out / "USER.md").is_file())

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _DownloadStub)
    def test_download_binary_asset_byte_faithful(self):
        """Regression (BUG-015): downloads went through text mode, so a
        binary asset's non-UTF-8 bytes (PNG magic ``\\x89``) got mangled by
        decode/re-encode. Downloads must be byte-faithful."""
        png = b"\x89PNG\r\n\x1a\nopenhuman"
        orig_store = _DownloadStub.STORE.copy()
        _DownloadStub.STORE = {
            "SOUL.md": "soul",
            "skills/draw/assets/pic.png": png,
        }
        try:
            rc = cmd_download(
                framework="nanobot", repo="nano",
                local_dir=str(self.out),
                endpoint="http://s", token="tok", username="u",
            )
            self.assertEqual(rc, 0)
            written = (self.out / "skills" / "draw" / "assets"
                       / "pic.png").read_bytes()
            self.assertEqual(written, png)
            # Text files still round-trip as text.
            self.assertEqual((self.out / "SOUL.md").read_text(), "soul")
        finally:
            _DownloadStub.STORE = orig_store

    @mock.patch("ms_agent.agent_hub._sync.cache_dir")
    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _DownloadStub)
    def test_existing_skill_not_overwritten(self, mock_sync_cache):
        """Regression (BUG-024): cross-framework convert/download must skip a
        skill the target already has instead of silently overwriting it."""
        from ms_agent.agent_hub._commands import cmd_convert
        cache = Path(self.tmp.name) / "cache"
        cache.mkdir(exist_ok=True)
        mock_sync_cache.return_value = cache
        # convert path: target dst already has skills/demo with own content.
        src = Path(self.tmp.name) / "cv_src"
        (src / "skills" / "demo").mkdir(parents=True)
        (src / "SOUL.md").write_text("# soul")
        (src / "skills" / "demo" / "SKILL.md").write_text("SRC VERSION")
        dst = Path(self.tmp.name) / "cv_dst"
        (dst / "skills" / "demo").mkdir(parents=True)
        (dst / "skills" / "demo" / "SKILL.md").write_text("TARGET VERSION")
        rc = cmd_convert("hermes", "nanobot", from_name="default",
                         local_dir=str(src), out_dir=str(dst))
        self.assertEqual(rc, 0)
        self.assertEqual(
            (dst / "skills" / "demo" / "SKILL.md").read_text(),
            "TARGET VERSION")
        # download path: local workspace already has skills/demo.
        dl = Path(self.tmp.name) / "dl_ws"
        (dl / "skills" / "demo").mkdir(parents=True)
        (dl / "skills" / "demo" / "SKILL.md").write_text("LOCAL VERSION")
        orig_store = _DownloadStub.STORE.copy()
        _DownloadStub.STORE = {
            "SOUL.md": "soul",
            "skills/demo/SKILL.md": "REMOTE VERSION",
        }
        try:
            rc = cmd_download(
                framework="hermes", repo="h", target="nanobot",
                local_dir=str(dl),
                endpoint="http://s", token="tok", username="u")
        finally:
            _DownloadStub.STORE = orig_store
        self.assertEqual(rc, 0)
        self.assertEqual(
            (dl / "skills" / "demo" / "SKILL.md").read_text(),
            "LOCAL VERSION")

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _DownloadStub)
    def test_download_convert_parity_with_local_convert(self):
        """Regression (BUG-020): ``download --target-framework`` must produce
        the SAME file set as a local ``convert`` -- same persona routing for
        file-per-agent targets (agents/<name>.md, no shared AGENTS.md
        pollution) and no invented target default templates."""
        from ms_agent.agent_hub._commands import cmd_convert
        src = Path(self.tmp.name) / "src"
        src.mkdir()
        for rel, content in _DownloadStub.STORE.items():
            p = src / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        for target, kwargs in (("qoder", {"name": "myagent"}),
                               ("hermes", {})):
            dl = Path(self.tmp.name) / f"dl_{target}"
            cv = Path(self.tmp.name) / f"cv_{target}"
            rc = cmd_download(
                framework="nanobot", repo="nano", target=target,
                local_dir=str(dl),
                endpoint="http://s", token="tok", username="u", **kwargs)
            self.assertEqual(rc, 0)
            rc = cmd_convert(
                "nanobot", target, from_name="default",
                target_name=kwargs.get("name"),
                local_dir=str(src), out_dir=str(cv))
            self.assertEqual(rc, 0)
            dl_files = sorted(
                str(p.relative_to(dl)) for p in dl.rglob("*") if p.is_file())
            cv_files = sorted(
                str(p.relative_to(cv)) for p in cv.rglob("*") if p.is_file())
            self.assertEqual(dl_files, cv_files, f"target={target}")
        # file-per-agent target: persona landed in its private file.
        self.assertTrue((Path(self.tmp.name) / "dl_qoder" / "agents"
                         / "myagent.md").is_file())

    def test_download_without_login_fails(self):
        rc = cmd_download(
            framework="nanobot", repo="nano",
            local_dir=str(self.out),
            endpoint=None, token=None,
        )
        self.assertEqual(rc, 1)

    def test_download_repo_required(self):
        """Download without --repo should fail."""
        rc = cmd_download(
            framework="nanobot", repo="",
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 1)

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _DownloadStub)
    def test_download_with_name_creates_agent(self):
        """Download with --name should write files for that local agent."""
        rc = cmd_download(
            framework="nanobot", repo="nano",
            name="myagent", local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        self.assertTrue((self.out / "SOUL.md").is_file())

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _DownloadStub)
    def test_download_filters_by_allowlist(self):
        """Files not matching the allowlist patterns should be skipped."""
        orig_store = _DownloadStub.STORE.copy()
        _DownloadStub.STORE = {
            "SOUL.md": "soul",
            "random/junk.txt": "junk",
            "memory/MEMORY.md": "mem",
        }
        try:
            rc = cmd_download(
                framework="nanobot", repo="nano",
                local_dir=str(self.out),
                endpoint="http://s", token="tok", username="u",
            )
            self.assertEqual(rc, 0)
            # random/junk.txt should NOT be written.
            self.assertFalse((self.out / "random" / "junk.txt").exists())
            # Valid files should be written.
            self.assertTrue((self.out / "SOUL.md").is_file())
        finally:
            _DownloadStub.STORE = orig_store

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _DownloadStub)
    def test_download_repo_with_slash(self):
        """--repo with '/' uses the specified group instead of username."""
        rc = cmd_download(
            framework="nanobot", repo="othergroup/nano",
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        self.assertTrue((self.out / "SOUL.md").is_file())

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _QwenpawAllStub)
    def test_download_convert_all_root_to_root(self):
        """qwenpaw -> openclaw with --name all: per-agent convert + re-prefix."""
        rc = cmd_download(
            framework="qwenpaw", repo="qw", name="all", target="openclaw",
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        # default -> workspace/, bot-a -> workspace-bot-a/ (openclaw convention)
        self.assertTrue((self.out / "workspace" / "AGENTS.md").is_file())
        self.assertTrue((self.out / "workspace-bot-a" / "AGENTS.md").is_file())
        self.assertTrue((self.out / "workspace-bot-a" / "SOUL.md").is_file())
        # qwenpaw-only PROFILE.md has no openclaw equivalent: must NOT land as-is.
        self.assertFalse((self.out / "workspace-bot-a" / "PROFILE.md").exists())
        # top-level non-agent files (README) are dropped, never mis-prefixed.
        self.assertFalse((self.out / "README.md").exists())
        self.assertFalse((self.out / "workspace" / "README.md").exists())

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _QwenpawAllStub)
    def test_download_convert_all_cross_layout_rejected(self):
        """qwenpaw -> qoder with --name all is cross-layout: must be rejected."""
        rc = cmd_download(
            framework="qwenpaw", repo="qw", name="all", target="qoder",
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 1)

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _QwenpawAllStub)
    def test_download_all_same_framework_keeps_prefixed_paths(self):
        """qwenpaw -> qwenpaw with --name all: no convert, agent prefixes kept."""
        rc = cmd_download(
            framework="qwenpaw", repo="qw", name="all",
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        self.assertTrue((self.out / "workspaces" / "default" / "AGENTS.md").is_file())
        self.assertTrue((self.out / "workspaces" / "bot-a" / "AGENTS.md").is_file())
        self.assertTrue((self.out / "workspaces" / "bot-a" / "PROFILE.md").is_file())
        # non-spec top-level files are skipped.
        self.assertFalse((self.out / "README.md").exists())

    # ---- named-agent download from an all-layout repo (bug regression) ----

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _HermesAllStub)
    def test_download_named_agent_from_all_repo_takes_only_its_files(self):
        """-n coder must take ONLY profiles/coder/** (prefix stripped) --
        never default's bare files."""
        rc = cmd_download(
            framework="hermes", repo="hm", name="coder",
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        coder = self.out / "profiles" / "coder"
        # coder's own files, prefix stripped:
        self.assertEqual((coder / "SOUL.md").read_text(), "# coder soul")
        self.assertEqual(
            (coder / "memories" / "2026-07-26.md").read_text(), "coder mem")
        self.assertEqual(
            (coder / "skills" / "code-review" / "SKILL.md").read_text(),
            "coder skill")
        # default's files must NOT leak into coder's directory:
        self.assertFalse((coder / "config.yaml").exists())
        self.assertFalse((coder / "hooks").exists())
        self.assertFalse((coder / "memories" / "2026-07-20.md").exists())
        self.assertFalse((coder / "skills" / "daily-ai-news").exists())
        self.assertFalse((coder / "optional-skills").exists())

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _HermesAllStub)
    def test_download_default_from_all_repo_excludes_named_agents(self):
        """Default download from an all repo: bare files only, no profiles/."""
        rc = cmd_download(
            framework="hermes", repo="hm",
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        self.assertEqual((self.out / "SOUL.md").read_text(), "# default soul")
        self.assertTrue((self.out / "memories" / "2026-07-20.md").is_file())
        self.assertFalse((self.out / "profiles").exists())

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _HermesAllStub)
    def test_download_missing_agent_from_all_repo_fails(self):
        """An all repo without the requested agent must error, not silently
        fill the agent with default's content."""
        rc = cmd_download(
            framework="hermes", repo="hm", name="writer",
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 1)
        self.assertFalse((self.out / "profiles" / "writer").exists())

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _QwenpawAllStub)
    def test_download_named_agent_from_qwenpaw_all_repo(self):
        """Same family bug on qwenpaw: -n bot-a takes only bot-a/**."""
        rc = cmd_download(
            framework="qwenpaw", repo="qw", name="bot-a",
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        ws = self.out / "workspaces" / "bot-a"
        self.assertEqual((ws / "SOUL.md").read_text(), "# bot-a soul")
        self.assertEqual((ws / "AGENTS.md").read_text(), "# bot-a agents")
        # default's files must not leak into bot-a's workspace:
        self.assertFalse(
            (ws / "workspaces").exists(),
            "no nested workspaces dir expected")
        self.assertNotEqual((ws / "AGENTS.md").read_text(), "# default agents")

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _DownloadStub)
    def test_download_single_agent_repo_with_name_keeps_legacy_behavior(self):
        """A legacy bare (single-agent) repo downloaded with -n <name> still
        writes the bare files into that agent's directory."""
        rc = cmd_download(
            framework="nanobot", repo="nano", name="myagent",
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        self.assertEqual((self.out / "SOUL.md").read_text(), "soul")


# ---------------------------------------------------------------------------
# Convert command tests
# ---------------------------------------------------------------------------


class TestConvert(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name) / "nb"
        self.out = Path(self.tmp.name) / "hm"
        (self.src / "memory").mkdir(parents=True)
        (self.src / "SOUL.md").write_text("nano soul")
        (self.src / "USER.md").write_text("about user")
        (self.src / "memory" / "MEMORY.md").write_text("fact")

    def tearDown(self):
        self.tmp.cleanup()

    # NOTE: basic nanobot->hermes convert (presence-only) is covered more
    # strongly by test_convert_targetname.py::test_convert_to_hermes_output_is_clean
    # (identity survival + landing path + corruption-free), so it is not
    # duplicated here.  This class keeps only the failure/edge paths below.

    def test_convert_dry_run_writes_nothing(self):
        rc = cmd_convert(
            source_fw="nanobot", target_fw="hermes",
            local_dir=str(self.src), out_dir=str(self.out),
            dry_run=True,
        )
        self.assertEqual(rc, 0)
        self.assertFalse(self.out.exists())

    def test_convert_unknown_framework_fails(self):
        rc = cmd_convert(
            source_fw="nope", target_fw="hermes",
            local_dir=str(self.src),
        )
        self.assertEqual(rc, 1)

    def test_convert_no_source_files_fails(self):
        rc = cmd_convert(
            source_fw="nanobot", target_fw="hermes",
            local_dir=str(self.src / "missing"),
        )
        self.assertEqual(rc, 1)

    @mock.patch("ms_agent.agent_hub._sync.cache_dir")
    def test_convert_twice_is_idempotent(self, mock_sync_cache):
        """Regression (BUG-027): re-running convert into the same out-dir
        must neither duplicate the '## Imported from' overflow block nor
        wipe the previously migrated user content down to zero."""
        from ms_agent.agent_hub._defaults import get_defaults
        cache = Path(self.tmp.name) / "cache"
        cache.mkdir(exist_ok=True)
        mock_sync_cache.return_value = cache
        root = Path(self.tmp.name) / "qp"
        ws = root / "workspaces" / "default"
        ws.mkdir(parents=True)
        (ws / "PROFILE.md").write_text(
            get_defaults("qwenpaw")["PROFILE.md"]
            + "\n\n## My Marker\n\nMRGMARKER\n")
        (ws / "SOUL.md").write_text("# soul\nCUSTOM SOUL\n")
        out = Path(self.tmp.name) / "oc"
        for _ in range(2):
            rc = cmd_convert(
                source_fw="qwenpaw", target_fw="openclaw",
                from_name="default",
                local_dir=str(root), out_dir=str(out))
            self.assertEqual(rc, 0)
        agents = (out / "workspace" / "AGENTS.md").read_text()
        self.assertEqual(agents.count("## Imported from"), 1)
        self.assertEqual(agents.count("MRGMARKER"), 1)


class TestFrameworkUploadCoverage(unittest.TestCase):
    """Offline upload coverage for openclaw / hermes / ms-agent / qwenpaw,
    each using its own native file layout.  Complements TestUploadCmd (qoder)."""

    LAYOUTS = {
        "openclaw": {"SOUL.md": "# Soul\noc\n", "USER.md": "# User\noc\n"},
        "hermes": {"SOUL.md": "# Soul\nhm\n", "memories/USER.md": "# User\nhm\n"},
        "ms-agent": {"SOUL.md": "# Soul\nms\n", "PROFILE.md": "# Profile\nms\n"},
        "qwenpaw": {"SOUL.md": "# Soul\nqp\n", "PROFILE.md": "# Profile\nqp\n"},
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _StubClient.instances = []

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def _upload(self, framework, files):
        root = Path(self.tmp.name) / framework
        ws = build_spec(framework, "default", str(root)).workspace_root
        for rel, content in files.items():
            fp = ws / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
        _StubClient.instances = []
        rc = cmd_upload(
            framework=framework, name=None, local_dir=str(root),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0, f"{framework} upload failed")
        return _StubClient.instances[0]

    def test_upload_openclaw(self):
        client = self._upload("openclaw", self.LAYOUTS["openclaw"])
        self.assertEqual(client.created[0], ("u", "openclaw-default", "openclaw"))
        self.assertIn("SOUL.md", client.uploaded_resources)
        self.assertIn("USER.md", client.uploaded_resources)

    def test_upload_hermes(self):
        client = self._upload("hermes", self.LAYOUTS["hermes"])
        self.assertEqual(client.created[0], ("u", "hermes-default", "hermes"))
        self.assertIn("memories/USER.md", client.uploaded_resources)

    def test_upload_ms_agent(self):
        client = self._upload("ms-agent", self.LAYOUTS["ms-agent"])
        self.assertEqual(client.created[0], ("u", "ms-agent-default", "ms-agent"))
        self.assertIn("SOUL.md", client.uploaded_resources)
        self.assertIn("PROFILE.md", client.uploaded_resources)

    def test_upload_qwenpaw(self):
        client = self._upload("qwenpaw", self.LAYOUTS["qwenpaw"])
        self.assertEqual(client.created[0], ("u", "qwenpaw-default", "qwenpaw"))
        self.assertIn("PROFILE.md", client.uploaded_resources)


class TestUploadSanitization(unittest.TestCase):
    """Outbound (local -> remote) secret scrubbing MUST happen *at upload time*.

    These assert against ``client.uploaded_resources`` -- the exact bytes the
    stubbed commit interface received -- so a secret left in a local config file
    (hermes ``config.yaml``, qwenpaw ``agent.json``) is proven to never leave the
    machine.  Upload wires the scrub via ``sanitize_outbound`` in ``cmd_upload``
    *before* anything is handed to the client.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _StubClient.instances = []

    def tearDown(self):
        self.tmp.cleanup()

    def _write_ws(self, framework, files):
        root = Path(self.tmp.name) / framework
        ws = build_spec(framework, "default", str(root)).workspace_root
        for rel, content in files.items():
            fp = ws / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
        return root

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_upload_scrubs_hermes_config_secrets(self):
        """config.yaml api_key + mcp_servers.*.env values are blanked on push;
        structure / non-secret content survives."""
        config = (
            "# my custom hermes config\n"
            "model:\n"
            "  name: qwen-max\n"
            "  api_key: sk-SUPERSECRET123\n"
            "mcp_servers:\n"
            "  fetch:\n"
            "    command: fetch-server\n"
            "    env:\n"
            "      FETCH_TOKEN: tok-LEAKME456\n"
        )
        root = self._write_ws(
            "hermes", {"SOUL.md": "# Soul\ncustom\n", "config.yaml": config})
        rc = cmd_upload(
            framework="hermes", name=None, local_dir=str(root),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        client = _StubClient.instances[0]
        self.assertIn("config.yaml", client.uploaded_resources)
        pushed = client.uploaded_resources["config.yaml"].decode("utf-8")
        # Secrets are gone from what actually left the machine.
        self.assertNotIn("sk-SUPERSECRET123", pushed)
        self.assertNotIn("tok-LEAKME456", pushed)
        # Non-secret structure / values are preserved.
        self.assertIn("name: qwen-max", pushed)
        self.assertIn("mcp_servers:", pushed)
        self.assertIn("api_key:", pushed)

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_upload_scrubs_qwenpaw_agent_json_secrets(self):
        """agent.json channel secrets + MCP env are blanked on push, while local
        identity (id / workspace_dir) is kept (rebound only on download)."""
        import json
        agent_json = json.dumps({
            "id": "default",
            "workspace_dir": "/Users/me/.copaw/workspaces/default",
            "channels": {
                "telegram": {
                    "token": "tg-LEAKME789",
                    "db_path": "/Users/me/telegram.sqlite",
                },
            },
            "mcp": {
                "clients": {
                    "srv": {"env": {"API_KEY": "mcp-LEAKME000"}},
                },
            },
        })
        root = self._write_ws(
            "qwenpaw", {"SOUL.md": "# Soul\ncustom\n", "agent.json": agent_json})
        rc = cmd_upload(
            framework="qwenpaw", name=None, local_dir=str(root),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        client = _StubClient.instances[0]
        self.assertIn("agent.json", client.uploaded_resources)
        pushed = json.loads(client.uploaded_resources["agent.json"].decode("utf-8"))
        # Channel + MCP secrets blanked in the pushed payload.
        self.assertEqual(pushed["channels"]["telegram"]["token"], "")
        self.assertEqual(pushed["channels"]["telegram"]["db_path"], "")
        self.assertEqual(pushed["mcp"]["clients"]["srv"]["env"]["API_KEY"], "")
        # Raw secret strings never appear anywhere in the bytes.
        raw = client.uploaded_resources["agent.json"].decode("utf-8")
        self.assertNotIn("tg-LEAKME789", raw)
        self.assertNotIn("mcp-LEAKME000", raw)
        self.assertNotIn("/Users/me/telegram.sqlite", raw)
        # Local identity is NOT rebound/stripped on upload (kept as-is).
        self.assertEqual(pushed["id"], "default")

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_upload_scrubs_ms_agent_yaml_secrets(self):
        """ms-agent agent.yaml/config.yaml llm.*_api_key + mcpServers env are
        blanked on push; non-secret structure survives."""
        agent_yaml = (
            "llm:\n"
            "  service: modelscope\n"
            "  model: Qwen/Qwen3-235B-A22B-Instruct-2507\n"
            "  modelscope_api_key: ms-LEAKME111\n"
            "mcpServers:\n"
            "  fetch:\n"
            "    command: fetch-server\n"
            "    env:\n"
            "      FETCH_TOKEN: env-LEAKME222\n"
        )
        root = self._write_ws(
            "ms-agent",
            {"profile.md": "# Profile\ncustom\n", "agent.yaml": agent_yaml})
        rc = cmd_upload(
            framework="ms-agent", name=None, local_dir=str(root),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        client = _StubClient.instances[0]
        self.assertIn("agent.yaml", client.uploaded_resources)
        pushed = client.uploaded_resources["agent.yaml"].decode("utf-8")
        # Both the llm api_key and the mcpServers env secret are gone.
        self.assertNotIn("ms-LEAKME111", pushed)
        self.assertNotIn("env-LEAKME222", pushed)
        # Non-secret structure / values preserved.
        self.assertIn("service: modelscope", pushed)
        self.assertIn("modelscope_api_key:", pushed)
        self.assertIn("mcpServers:", pushed)

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _StubClient)
    def test_upload_scrubs_ms_agent_settings_json_secrets(self):
        """ms-agent settings.json secret keys + mcpServers env are blanked on
        push; non-secret values survive."""
        import json
        settings = json.dumps({
            "openai_api_key": "sk-LEAKME333",
            "model": "gpt-4o",
            "mcpServers": {
                "srv": {
                    "command": "run",
                    "env": {"API_KEY": "env-LEAKME444"},
                },
            },
        })
        root = self._write_ws(
            "ms-agent",
            {"profile.md": "# Profile\ncustom\n", "settings.json": settings})
        rc = cmd_upload(
            framework="ms-agent", name=None, local_dir=str(root),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        client = _StubClient.instances[0]
        self.assertIn("settings.json", client.uploaded_resources)
        raw = client.uploaded_resources["settings.json"].decode("utf-8")
        pushed = json.loads(raw)
        # Secret key + mcpServers env blanked; non-secret value preserved.
        self.assertEqual(pushed["openai_api_key"], "")
        self.assertEqual(pushed["mcpServers"]["srv"]["env"]["API_KEY"], "")
        self.assertEqual(pushed["model"], "gpt-4o")
        self.assertNotIn("sk-LEAKME333", raw)
        self.assertNotIn("env-LEAKME444", raw)


class _OpenclawStub(_RepoStub):
    """Serves an openclaw single sub-agent repo (bare paths)."""

    FRAMEWORK = "openclaw"
    STORE = {"SOUL.md": "# Soul\noc identity\n", "USER.md": "# User\noc user\n"}

    def __init__(self, *args, **kwargs):
        pass


class _HermesStub(_RepoStub):
    """Serves a hermes single-agent repo."""

    FRAMEWORK = "hermes"
    STORE = {"SOUL.md": "# Soul\nhermes identity\n",
             "memories/USER.md": "# User\nhermes user\n"}

    def __init__(self, *args, **kwargs):
        pass


class _MsAgentStub(_RepoStub):
    """Serves an ms-agent single-agent repo (SOUL.md / PROFILE.md prompt files)."""

    FRAMEWORK = "ms-agent"
    STORE = {"SOUL.md": "# Soul\nms persona\n",
             "PROFILE.md": "# Profile\nms profile\n"}

    def __init__(self, *args, **kwargs):
        pass


class TestFrameworkDownloadCoverage(unittest.TestCase):
    """Direct (non-convert) download coverage for openclaw / hermes / ms-agent,
    complementing the qwenpaw download tests already in TestDownload."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "ws"

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _OpenclawStub)
    def test_download_openclaw_writes_content(self):
        rc = cmd_download(
            framework="openclaw", repo="oc", local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        self.assertEqual((self.out / "workspace" / "SOUL.md").read_text(), "# Soul\noc identity\n")
        self.assertEqual((self.out / "workspace" / "USER.md").read_text(), "# User\noc user\n")

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _HermesStub)
    def test_download_hermes_writes_content(self):
        rc = cmd_download(
            framework="hermes", repo="hm", local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        self.assertEqual((self.out / "SOUL.md").read_text(), "# Soul\nhermes identity\n")
        self.assertEqual(
            (self.out / "memories" / "USER.md").read_text(), "# User\nhermes user\n")

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _MsAgentStub)
    def test_download_ms_agent_writes_content(self):
        rc = cmd_download(
            framework="ms-agent", repo="msa", local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        self.assertEqual((self.out / "SOUL.md").read_text(), "# Soul\nms persona\n")
        self.assertEqual((self.out / "PROFILE.md").read_text(), "# Profile\nms profile\n")


# ---------------------------------------------------------------------------
# List command tests (--owner / --page / --page-size, stubbed client)
# ---------------------------------------------------------------------------


class _ListStub:
    """Records the pagination/owner args and serves a fixed agent listing."""

    calls = []
    RESULT = {
        "items": [
            {"Path": "alice", "Name": "bot-a", "Framework": "qwenpaw",
             "Visibility": "public", "LastUpdatedDate": "2026-07-01T10:00:00"},
        ],
        "total_count": 1,
    }

    def __init__(self, *args, **kwargs):
        pass

    def list_agents(self, owner=None, page_number=1, page_size=10):
        _ListStub.calls.append(
            {"owner": owner, "page_number": page_number, "page_size": page_size})
        return _ListStub.RESULT


class TestListCmd(unittest.TestCase):
    def setUp(self):
        _ListStub.calls = []

    def test_list_requires_login(self):
        # No endpoint -> command fails without touching the client.
        rc = cmd_list(endpoint=None, token=None)
        self.assertEqual(rc, 1)

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _ListStub)
    def test_list_passes_owner_and_pagination(self):
        rc = cmd_list(
            owner="alice", page_number=3, page_size=25,
            endpoint="http://s", token="tok",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(len(_ListStub.calls), 1)
        self.assertEqual(
            _ListStub.calls[0],
            {"owner": "alice", "page_number": 3, "page_size": 25},
        )

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _ListStub)
    def test_list_defaults_pagination(self):
        rc = cmd_list(endpoint="http://s", token="tok")
        self.assertEqual(rc, 0)
        self.assertEqual(
            _ListStub.calls[0],
            {"owner": None, "page_number": 1, "page_size": 10},
        )

    @mock.patch("ms_agent.agent_hub._commands.AgentApi")
    def test_list_empty_result(self, mock_api):
        inst = mock_api.return_value
        inst.list_agents.return_value = {"items": [], "total_count": 0}
        rc = cmd_list(endpoint="http://s", token="tok")
        self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# Stop command tests (stubbed daemon)
# ---------------------------------------------------------------------------


class TestStopCmd(unittest.TestCase):
    @mock.patch("ms_agent.agent_hub._watcher.stop_daemon")
    def test_stop_reports_stopped(self, mock_stop):
        mock_stop.return_value = True
        rc = cmd_stop()
        self.assertEqual(rc, 0)
        mock_stop.assert_called_once()

    @mock.patch("ms_agent.agent_hub._watcher.stop_daemon")
    def test_stop_reports_none_running(self, mock_stop):
        mock_stop.return_value = False
        rc = cmd_stop()
        self.assertEqual(rc, 0)
        mock_stop.assert_called_once()


# ---------------------------------------------------------------------------
# Watch command entry tests (--pull / -n guards, no daemon spawned)
# ---------------------------------------------------------------------------


class TestWatchCmdEntry(unittest.TestCase):
    """Exercises cmd_watch validation branches that return before daemonizing."""

    def test_watch_unknown_framework_fails(self):
        rc = cmd_watch(framework="nope", repo="r",
                       endpoint="http://s", token="tok", username="u")
        self.assertEqual(rc, 1)

    def test_watch_requires_login(self):
        rc = cmd_watch(framework="nanobot", repo="r",
                       endpoint=None, token=None, username="u")
        self.assertEqual(rc, 1)

    def test_watch_requires_username(self):
        rc = cmd_watch(framework="nanobot", repo="r",
                       endpoint="http://s", token="tok", username=None)
        self.assertEqual(rc, 1)

    @mock.patch("ms_agent.agent_hub._watcher.stop_daemon")
    def test_watch_individual_on_shared_framework_rejected(self, mock_stop):
        # qoder shares files across sub-agents; a named individual watch is
        # rejected (--pull / -n path) before any daemon is launched.
        rc = cmd_watch(
            framework="qoder", name="bot-a", repo="r", pull=True,
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
