# Copyright (c) Alibaba, Inc. and its affiliates.
"""Sub-agent-aware workspace spec collection tests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ms_agent.agent_hub import FRAMEWORK_REGISTRY
from ms_agent.agent_hub._commands import build_spec, cmd_convert
from ms_agent.agent_hub.frameworks.nanobot import NanobotWorkspace
from ms_agent.agent_hub.frameworks.qoder import QoderWorkspace
from ms_agent.agent_hub.frameworks.qwenpaw import QwenpawWorkspace


class TestAgentAwareCollect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_qoder_collects_named_agent_plus_shared(self):
        (self.root / "agents").mkdir()
        (self.root / "agents" / "reviewer.md").write_text("reviewer agent")
        (self.root / "agents" / "other.md").write_text("other agent")
        (self.root / "AGENTS.md").write_text("shared instructions")
        (self.root / "skills" / "x").mkdir(parents=True)
        (self.root / "skills" / "x" / "SKILL.md").write_text("skill")

        spec = QoderWorkspace(agent_name="reviewer", local_dir=self.root)
        collected = spec.collect()

        self.assertIn("agents/reviewer.md", collected)
        self.assertIn("AGENTS.md", collected)
        self.assertIn("skills/x/SKILL.md", collected)
        self.assertNotIn("agents/other.md", collected)

    def test_hermes_excludes_framework_skills_keeps_user_skills(self):
        """hermes collect drops bundled/framework skills (identified by a
        builtin_skill_version / metadata.copaw frontmatter marker or a
        .bundled_manifest entry) but keeps the user's own skills -- including
        open-source ones whose frontmatter carries a ``license`` field
        (BUG-021: license alone must NOT mark a skill as bundled)."""
        spec = build_spec("hermes", "default", str(self.root))
        base = spec.workspace_root
        (base / "skills" / "docx").mkdir(parents=True, exist_ok=True)
        (base / "skills" / "docx" / "SKILL.md").write_text(
            "---\nname: docx\nlicense: MIT\nbuiltin_skill_version: '1.0'\n"
            "---\n# docx\nbuiltin\n", encoding="utf-8")
        (base / "skills" / "write").mkdir(parents=True, exist_ok=True)
        (base / "skills" / "write" / "SKILL.md").write_text(
            "# Write\nUser's own writing skill.\n", encoding="utf-8")
        (base / "skills" / "my-open-skill").mkdir(parents=True, exist_ok=True)
        (base / "skills" / "my-open-skill" / "SKILL.md").write_text(
            "---\nname: my-open-skill\ndescription: x\nlicense: Apache-2.0\n"
            "---\n\nBODY\n", encoding="utf-8")
        # BUG-022: a bare metadata.<product> key holding CUSTOM parameters
        # (no install hints) is a user skill, not a bundled one.
        (base / "skills" / "my-meta-skill").mkdir(parents=True, exist_ok=True)
        (base / "skills" / "my-meta-skill" / "SKILL.md").write_text(
            "---\nname: my-meta-skill\nmetadata:\n  openclaw:\n"
            "    my_param: 1\n---\n\nBODY\n", encoding="utf-8")
        # BUG-023: a manifest-declared bundled skill stays bundled even when
        # its frontmatter YAML is corrupt (fail-closed, never uploaded).
        (base / "skills" / ".bundled_manifest").write_text(
            "broken-bundled:deadbeef\n", encoding="utf-8")
        (base / "skills" / "broken-bundled").mkdir(parents=True, exist_ok=True)
        (base / "skills" / "broken-bundled" / "SKILL.md").write_text(
            "---\nname: broken-bundled\n: : bad yaml : :\n---\nBODY\n",
            encoding="utf-8")
        collected = spec.collect()
        self.assertIn("skills/write/SKILL.md", collected)
        self.assertIn("skills/my-open-skill/SKILL.md", collected)
        self.assertIn("skills/my-meta-skill/SKILL.md", collected)
        self.assertNotIn("skills/docx/SKILL.md", collected)
        self.assertNotIn("skills/broken-bundled/SKILL.md", collected)

    def test_hermes_collects_hooks_same_framework(self):
        """hermes collects ``hooks/*`` (lifecycle hooks) for same-framework
        fidelity, both for the default agent and named agents in all-mode."""
        spec = build_spec("hermes", "default", str(self.root))
        base = spec.workspace_root
        (base / "hooks").mkdir(parents=True, exist_ok=True)
        (base / "hooks" / "session_start.sh").write_text(
            "#!/bin/sh\ngit pull\n", encoding="utf-8")
        (base / "SOUL.md").write_text("soul", encoding="utf-8")
        self.assertIn("hooks/session_start.sh", spec.collect())

        # all-mode: a named agent's hooks land under profiles/<name>/hooks/.
        prof = self.root / "profiles" / "qa" / "hooks"
        prof.mkdir(parents=True, exist_ok=True)
        (prof / "pre.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        all_spec = build_spec("hermes", "all", str(self.root))
        self.assertIn("profiles/qa/hooks/pre.sh", all_spec.collect())

    def test_hooks_dropped_when_converting_to_other_frameworks(self):
        """``hooks/*`` is hermes-only and absent from SEMANTIC_GROUPS, so every
        other framework rejects the path (convert drops it via the dst filter;
        it is never folded into the catch-all persona file)."""
        for fw in ("qwenpaw", "openclaw", "nanobot", "openhuman", "qoder", "ms-agent"):
            spec = build_spec(fw, "default", str(self.root))
            self.assertFalse(
                spec.matches("hooks/session_start.sh", spec.resolved_patterns()),
                f"{fw} should not match hooks/* (must be dropped on convert)",
            )

    def test_qwenpaw_excludes_framework_skills_keeps_user_skills(self):
        """qwenpaw (CoPaw) shares BundledSkillFilterMixin: framework skills
        (builtin_skill_version / metadata.copaw|qwenpaw markers, no
        .bundled_manifest) are dropped with all their assets; user skills are
        kept."""
        spec = build_spec("qwenpaw", "default", str(self.root))
        base = spec.workspace_root
        docx = base / "skills" / "docx" / "scripts"
        docx.mkdir(parents=True, exist_ok=True)
        (base / "skills" / "docx" / "SKILL.md").write_text(
            "---\nname: docx\nlicense: Proprietary\n"
            "builtin_skill_version: '1.0'\n---\n# docx\n", encoding="utf-8")
        (docx / "helper.py").write_text("# bundled asset\n", encoding="utf-8")
        cron = base / "skills" / "cron"
        cron.mkdir(parents=True, exist_ok=True)
        (cron / "SKILL.md").write_text(
            '---\nname: cron\nmetadata: {"copaw": {"emoji": "x"}}\n---\n# cron\n',
            encoding="utf-8")
        user = base / "skills" / "my-skill"
        user.mkdir(parents=True, exist_ok=True)
        (user / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: mine\n---\n# mine\n", encoding="utf-8")
        # marketplace/bundled skill keyed by a *different* product name with
        # nested install hints -- must still be detected as framework-provided.
        himalaya = base / "skills" / "himalaya"
        himalaya.mkdir(parents=True, exist_ok=True)
        (himalaya / "SKILL.md").write_text(
            "---\nname: himalaya\nmetadata:\n  openclaw:\n    emoji: mail\n"
            "    install: []\n---\n# himalaya\n", encoding="utf-8")
        collected = spec.collect()
        self.assertIn("skills/my-skill/SKILL.md", collected)
        self.assertNotIn("skills/docx/SKILL.md", collected)
        self.assertNotIn("skills/docx/scripts/helper.py", collected)
        self.assertNotIn("skills/cron/SKILL.md", collected)
        self.assertNotIn("skills/himalaya/SKILL.md", collected)

    def test_name_templating_is_isolated_per_agent(self):
        (self.root / "agents").mkdir()
        (self.root / "agents" / "a.md").write_text("a")
        (self.root / "agents" / "b.md").write_text("b")

        a = QoderWorkspace(agent_name="a", local_dir=self.root).collect()
        b = QoderWorkspace(agent_name="b", local_dir=self.root).collect()
        self.assertEqual(set(a), {"agents/a.md"})
        self.assertEqual(set(b), {"agents/b.md"})

    def test_qoder_list_agents(self):
        (self.root / "agents").mkdir()
        (self.root / "agents" / "a.md").write_text("a")
        (self.root / "agents" / "b.md").write_text("b")
        spec = QoderWorkspace(local_dir=self.root)
        self.assertEqual(spec.list_agents(), ["default", "a", "b"])

    def test_qwenpaw_default_root_uses_agent_name(self):
        spec = QwenpawWorkspace(agent_name="browse-agent")
        self.assertTrue(
            str(spec.workspace_root).endswith("workspaces/browse-agent")
        )

    def test_local_dir_override_wins(self):
        (self.root / "SOUL.md").write_text("soul")
        (self.root / "memory").mkdir()
        (self.root / "memory" / "MEMORY.md").write_text("mem")
        spec = NanobotWorkspace(local_dir=self.root)
        self.assertEqual(spec.workspace_root, self.root)
        collected = spec.collect()
        self.assertIn("SOUL.md", collected)
        self.assertIn("memory/MEMORY.md", collected)

    def test_missing_root_returns_empty(self):
        spec = QoderWorkspace(
            agent_name="x", local_dir=self.root / "does-not-exist"
        )
        self.assertEqual(spec.collect(), {})

    def test_registry_includes_all_frameworks(self):
        for fw in ("qoder", "qwenpaw", "openclaw", "hermes", "nanobot", "openhuman"):
            self.assertIn(fw, FRAMEWORK_REGISTRY)


class TestAllPathPrefix(unittest.TestCase):
    """split_all_path / join_all_path for cross-framework all-mode convert."""

    def test_qwenpaw_split(self):
        spec = build_spec("qwenpaw", "all")
        self.assertTrue(spec.is_root_per_agent)
        self.assertEqual(spec.split_all_path("bot-a/AGENTS.md"), ("bot-a", "AGENTS.md"))
        self.assertEqual(spec.split_all_path("default/SOUL.md"), ("default", "SOUL.md"))
        self.assertEqual(
            spec.split_all_path("bot-a/skills/x/SKILL.md"), ("bot-a", "skills/x/SKILL.md"))
        self.assertEqual(spec.split_all_path("README.md"), (None, "README.md"))

    def test_qwenpaw_join(self):
        spec = build_spec("qwenpaw", "all")
        self.assertEqual(spec.join_all_path("bot-a", "AGENTS.md"), "bot-a/AGENTS.md")
        self.assertEqual(spec.join_all_path("default", "SOUL.md"), "default/SOUL.md")

    def test_openclaw_split(self):
        spec = build_spec("openclaw", "all")
        self.assertTrue(spec.is_root_per_agent)
        self.assertEqual(spec.split_all_path("workspace/AGENTS.md"), ("default", "AGENTS.md"))
        self.assertEqual(
            spec.split_all_path("workspace-bot-a/SOUL.md"), ("bot-a", "SOUL.md"))
        self.assertEqual(spec.split_all_path("README.md"), (None, "README.md"))

    def test_openclaw_join(self):
        spec = build_spec("openclaw", "all")
        self.assertEqual(spec.join_all_path("default", "AGENTS.md"), "workspace/AGENTS.md")
        self.assertEqual(spec.join_all_path("bot-a", "SOUL.md"), "workspace-bot-a/SOUL.md")

    def test_roundtrip_qwenpaw_to_openclaw(self):
        src = build_spec("qwenpaw", "all")
        dst = build_spec("openclaw", "all")
        agent, bare = src.split_all_path("bot-a/AGENTS.md")
        self.assertEqual(dst.join_all_path(agent, bare), "workspace-bot-a/AGENTS.md")

    def test_non_root_per_agent_passthrough(self):
        spec = build_spec("qoder", "all")
        self.assertFalse(spec.is_root_per_agent)
        self.assertEqual(spec.split_all_path("agents/x.md"), (None, "agents/x.md"))
        self.assertEqual(spec.join_all_path("x", "agents/x.md"), "agents/x.md")


class TestMsAgentWorkspace(unittest.TestCase):
    """ms-agent is single-agent: no {name} placeholder; collects the editable
    prompt files (SOUL.md/AGENTS.md/PROFILE.md), config and skills under the
    global home (~/.ms_agent). Runtime-only artifacts -- the builtin sidecars
    (.soul.builtin ...), *.bak backups, and project-level memory -- are not
    part of the portable layout and must be skipped."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_agent_layout_collect(self):
        spec = FRAMEWORK_REGISTRY["ms-agent"](agent_name="default", local_dir=self.root)
        self.assertEqual(spec.product_name, "ms-agent")
        self.assertFalse(any("{name}" in p for p in spec.patterns))
        (self.root / "SOUL.md").write_text("# Who You Are\np")
        (self.root / "AGENTS.md").write_text("a")
        (self.root / "PROFILE.md").write_text("p")
        (self.root / "settings.json").write_text("{}")
        (self.root / "skills.json").write_text("{}")
        # runtime-only artifacts that must NOT be collected.
        (self.root / ".soul.builtin").write_text("x")
        (self.root / "SOUL.md.bak").write_text("x")
        (self.root / "random.txt").write_text("x")
        (self.root / "skills" / "foo").mkdir(parents=True)
        (self.root / "skills" / "foo" / "SKILL.md").write_text("s")
        got = spec.collect()
        for f in ("SOUL.md", "AGENTS.md", "PROFILE.md", "settings.json",
                  "skills.json", "skills/foo/SKILL.md"):
            self.assertIn(f, got)
        for f in ("random.txt", ".soul.builtin", "SOUL.md.bak"):
            self.assertNotIn(f, got)


class TestQwenpawConfigRoot(unittest.TestCase):
    """qwenpaw probes ~/.qwenpaw (preferred) then legacy ~/.copaw, and falls
    back to ~/.qwenpaw when neither exists (brand rename CoPaw -> QwenPaw)."""

    def _root_name(self, present):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            for name in present:
                (home / name).mkdir()
            with mock.patch("pathlib.Path.home", return_value=home):
                return QwenpawWorkspace(agent_name="x").default_root.name

    def test_prefers_qwenpaw_when_both_exist(self):
        self.assertEqual(self._root_name([".qwenpaw", ".copaw"]), ".copaw")

    def test_uses_legacy_copaw_when_only_copaw(self):
        self.assertEqual(self._root_name([".copaw"]), ".copaw")

    def test_uses_qwenpaw_when_only_qwenpaw(self):
        self.assertEqual(self._root_name([".qwenpaw"]), ".qwenpaw")

    def test_defaults_to_qwenpaw_when_neither_exists(self):
        self.assertEqual(self._root_name([]), ".copaw")


class TestOpenhumanUserWorkspace(unittest.TestCase):
    """Regression (BUG-033): openhuman keeps its files in a per-device user
    workspace ``~/.openhuman/users/<user-id>/workspace``, not directly under
    ``~/.openhuman``, so the old fixed root collected ZERO files on real
    installs. Profiles under ``personalities/`` are sub-agents.
    """

    USER_ID = "local-u-mwj2l941-2317-local"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / ".openhuman"
        self.ws = self.root / "users" / self.USER_ID / "workspace"
        (self.ws / "personalities" / "Alice").mkdir(parents=True)
        (self.ws / "personalities" / "Bob").mkdir(parents=True)
        (self.ws / "wiki").mkdir()
        (self.ws / "SOUL.md").write_text("# global soul\n")
        (self.ws / "IDENTITY.md").write_text("# id\n")
        (self.ws / "config.toml").write_text('name = "bot"\n')
        (self.ws / "wiki" / "note.md").write_text("note\n")
        (self.ws / "personalities" / "Alice" / "SOUL.md").write_text("# A\n")
        (self.ws / "personalities" / "Bob" / "SOUL.md").write_text("# B\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolves_per_device_user_workspace(self):
        spec = build_spec("openhuman", "default", str(self.root))
        self.assertEqual(spec.workspace_root, self.ws)
        self.assertEqual(
            sorted(spec.collect_bytes()),
            ["IDENTITY.md", "SOUL.md", "config.toml", "wiki/note.md"])

    def test_default_root_probes_users_dir(self):
        from ms_agent.agent_hub.frameworks.openhuman import OpenhumanWorkspace
        with mock.patch("pathlib.Path.home", return_value=self.root.parent):
            self.assertEqual(
                OpenhumanWorkspace(agent_name="default").default_root, self.ws)

    def test_profiles_are_sub_agents(self):
        spec = build_spec("openhuman", "default", str(self.root))
        self.assertEqual(spec.list_agents(), ["default", "Alice", "Bob"])
        alice = build_spec("openhuman", "Alice", str(self.root))
        self.assertEqual(alice.workspace_root,
                         self.ws / "personalities" / "Alice")
        # Alice lacks IDENTITY.md, so the workspace-level copy falls back in
        # (app lookup order: Profile file > workspace-level default).
        self.assertEqual(sorted(alice.collect_bytes()),
                         ["IDENTITY.md", "SOUL.md"])

    def test_all_mode_prefixes_profile_dirs(self):
        spec = build_spec("openhuman", "all", str(self.root))
        self.assertEqual(sorted(spec.collect_bytes()),
                         ["Alice/SOUL.md", "Bob/SOUL.md"])
        self.assertTrue(spec.is_root_per_agent)
        self.assertEqual(spec.split_all_path("Alice/SOUL.md"),
                         ("Alice", "SOUL.md"))
        self.assertEqual(spec.join_all_path("Bob", "SOUL.md"), "Bob/SOUL.md")

    def test_local_dir_may_point_at_workspace_itself(self):
        spec = build_spec("openhuman", "default", str(self.ws))
        self.assertEqual(spec.workspace_root, self.ws)
        self.assertIn("SOUL.md", spec.collect_bytes())

    def test_fresh_install_without_users_dir_is_not_an_error(self):
        fresh = Path(self.tmp.name) / "fresh"
        fresh.mkdir()
        spec = build_spec("openhuman", "default", str(fresh))
        self.assertEqual(spec.collect_bytes(), {})


class TestOpenhumanActiveProfile(unittest.TestCase):
    """an omitted --from-name must convert the ACTIVE profile
    (``agent_profiles.json`` ``activeProfileId``), not the workspace-level
    fallback persona, and a Profile without its own MEMORY.md must fall back
    to the workspace-level one -- otherwise converting an openhuman install
    loses the active persona's memory.
    """

    USER_ID = "local-u-x"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / ".openhuman"
        self.ws = self.root / "users" / self.USER_ID / "workspace"
        librarian = self.ws / "personalities" / "to-ms-librarian"
        librarian.mkdir(parents=True)
        (self.ws / "personalities" / "idle").mkdir()
        # Workspace-level fallback persona + curated memory.
        (self.ws / "SOUL.md").write_text("# fallback soul\n")
        (self.ws / "IDENTITY.md").write_text("# id\n")
        (self.ws / "MEMORY.md").write_text("# workspace memory\n")
        # Active profile carries its own SOUL but NOT its own MEMORY.
        (librarian / "SOUL.md").write_text("# librarian soul\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_profiles(self, content):
        (self.ws / "agent_profiles.json").write_text(content)

    def test_omitted_name_selects_active_profile(self):
        self._write_profiles(json.dumps({"activeProfileId": "to-ms-librarian"}))
        spec = build_spec("openhuman", "default", str(self.root))
        self.assertEqual(spec.resolve_default_agent_name(), "to-ms-librarian")

    def test_no_profiles_json_falls_back_to_default(self):
        spec = build_spec("openhuman", "default", str(self.root))
        self.assertEqual(spec.resolve_default_agent_name(), "default")

    def test_malformed_profiles_json_falls_back_to_default(self):
        self._write_profiles("{not json")
        spec = build_spec("openhuman", "default", str(self.root))
        self.assertEqual(spec.resolve_default_agent_name(), "default")

    def test_unknown_profile_id_falls_back_to_default(self):
        self._write_profiles(json.dumps({"activeProfileId": "ghost"}))
        spec = build_spec("openhuman", "default", str(self.root))
        self.assertEqual(spec.resolve_default_agent_name(), "default")

    def test_empty_profile_id_falls_back_to_default(self):
        self._write_profiles(json.dumps({"activeProfileId": "  "}))
        spec = build_spec("openhuman", "default", str(self.root))
        self.assertEqual(spec.resolve_default_agent_name(), "default")

    def test_profile_memory_falls_back_to_workspace_level(self):
        spec = build_spec("openhuman", "to-ms-librarian", str(self.root))
        files = spec.collect()
        # Profile's own SOUL wins over the workspace-level one ...
        self.assertEqual(files["SOUL.md"], "# librarian soul\n")
        # ... while the missing persona files fall back to workspace copies.
        self.assertEqual(files["MEMORY.md"], "# workspace memory\n")
        self.assertEqual(files["IDENTITY.md"], "# id\n")
        self.assertNotIn("config.toml", files)
        self.assertNotIn("wiki/note.md", files)

    def test_profile_file_always_wins_over_workspace_fallback(self):
        (self.ws / "personalities" / "to-ms-librarian" /
         "MEMORY.md").write_text("# profile memory\n")
        spec = build_spec("openhuman", "to-ms-librarian", str(self.root))
        self.assertEqual(spec.collect()["MEMORY.md"], "# profile memory\n")

    def test_missing_memory_everywhere_is_silent(self):
        (self.ws / "MEMORY.md").unlink()
        spec = build_spec("openhuman", "to-ms-librarian", str(self.root))
        self.assertNotIn("MEMORY.md", spec.collect())

    def test_all_mode_stays_bare_per_profile(self):
        spec = build_spec("openhuman", "all", str(self.root))
        # No workspace-level duplication leaks into the per-profile repos.
        self.assertEqual(sorted(spec.collect()),
                         ["to-ms-librarian/SOUL.md"])

    def test_convert_without_name_uses_active_profile(self):
        """cmd_convert auto-selects the active profile end to end."""
        self._write_profiles(json.dumps({"activeProfileId": "to-ms-librarian"}))
        out_dir = Path(self.tmp.name) / "out"
        rc = cmd_convert(
            "openhuman", "nanobot", None, None, str(self.root), str(out_dir))
        self.assertEqual(rc, 0)
        # The ACTIVE profile's own SOUL (not the workspace-level fallback
        # persona) must be the converted persona ...
        self.assertIn("# librarian soul",
                      (out_dir / "SOUL.md").read_text(encoding="utf-8"))
        # ... and the workspace-level MEMORY falls back into the target's
        # memory slot instead of being lost (BUG-0825).
        memory = (out_dir / "memory" / "MEMORY.md").read_text(
            encoding="utf-8")
        self.assertIn("# workspace memory", memory)


class TestQwenpawAgentJsonSecrets(unittest.TestCase):
    """agent.json sanitize must blank secrets ANYWHERE in the JSON tree.

    Regression for the leak where only ``channels.*`` and
    ``mcp.clients.*.env`` were walked, so the top-level ``model.api_key``
    (the primary LLM credential) went to the public repo in plaintext.
    """

    SRC = json.dumps({
        "model": {"api_key": "sk-SECRET-1", "model": "qwen-max"},
        "channels": {
            "dingtalk": {
                "client_secret": "SECRET-2",
                "client_id": "keep-me",
                "db_path": "/local/db.sqlite",
            }
        },
        "mcp": {"clients": {"c1": {"env": {"ANY_NAME": "SECRET-3"}}}},
        "plugins": [{"token": "SECRET-4", "name": "p1"}],
    })

    def setUp(self):
        self.spec = QwenpawWorkspace(agent_name="paw_qa_01")

    def _assert_scrubbed(self, out: dict):
        # secrets blanked at every depth:
        self.assertEqual(out["model"]["api_key"], "")
        self.assertEqual(out["channels"]["dingtalk"]["client_secret"], "")
        self.assertEqual(out["mcp"]["clients"]["c1"]["env"], {"ANY_NAME": ""})
        self.assertEqual(out["plugins"][0]["token"], "")
        # machine-local channel key blanked:
        self.assertEqual(out["channels"]["dingtalk"]["db_path"], "")
        # non-secret fields preserved for post-migration debugging:
        self.assertEqual(out["model"]["model"], "qwen-max")
        self.assertEqual(out["channels"]["dingtalk"]["client_id"], "keep-me")
        self.assertEqual(out["plugins"][0]["name"], "p1")

    def test_outbound_upload_scrubs_whole_tree(self):
        out = json.loads(self.spec._strip_outbound_agent_json(self.SRC))
        self._assert_scrubbed(out)
        self.assertNotIn("SECRET", json.dumps(out))

    def test_inbound_download_scrubs_whole_tree(self):
        out = json.loads(self.spec._sanitize_agent_json("paw_qa_01", self.SRC))
        self._assert_scrubbed(out)
        self.assertNotIn("SECRET", json.dumps(out))

    def test_env_cleared_for_every_mcp_schema_spelling(self):
        """Regression (BUG-011): the wholesale env-clear rule was anchored on
        the ``mcp.clients`` path only; ``mcp_clients`` / ``mcpClients``
        spellings leaked non-vocabulary env values in plaintext."""
        sentinel = "SENTINEL-BUG011-CUSTOM"
        for name, payload in {
                "mcp.clients": {"mcp": {"clients": {"fetch": {"env": {"CUSTOM_VALUE": sentinel}}}}},
                "mcp_clients": {"mcp_clients": {"fetch": {"env": {"CUSTOM_VALUE": sentinel}}}},
                "mcpClients": {"mcpClients": {"fetch": {"env": {"CUSTOM_VALUE": sentinel}}}},
        }.items():
            body = json.dumps({"id": "bot-a", **payload})
            out = self.spec._strip_outbound_agent_json(body)
            self.assertNotIn(sentinel, out, f"MCP schema '{name}' leaked env value")
            # env keys preserved (values blanked), structure intact.
            self.assertIn("CUSTOM_VALUE", out)


class TestScrubYamlTomlSpellings(unittest.TestCase):
    """YAML/TOML scrubbers must catch every legal spelling of a secret.

    Regression (BUG-010): the line-based scrubbers only handled simple
    ``key: <scalar>`` / ``key = <scalar>`` lines; flow mappings, block/folded
    scalars, TOML inline tables, arrays and multi-line strings all went to
    the remote repo in plaintext with exit code 0.
    """

    S = "SENTINEL-BUG010-PLAINTEXT-SECRET"

    def _yaml(self, text):
        from ms_agent.agent_hub._workspace import scrub_yaml_secrets
        return scrub_yaml_secrets(text, mcp_block_keys=("mcp_servers", ))

    def _toml(self, text):
        from ms_agent.agent_hub.frameworks.openhuman import OpenhumanWorkspace
        return OpenhumanWorkspace(agent_name="default")._scrub_toml_secrets(
            text)

    def test_yaml_spellings_all_scrubbed(self):
        cases = {
            "flow_env":
            "mcp_servers:\n  fetch:\n    env: {TAVILY_API_KEY: %s}\n" % self.S,
            "flow_top": "llm: {api_key: %s, model: qwen3-max}\n" % self.S,
            "block_scalar": "api_key: |\n  %s\n" % self.S,
            "folded_scalar": "api_key: >\n  %s\n" % self.S,
            "baseline": "api_key: %s\n" % self.S,
        }
        leaked = [n for n, t in cases.items() if self.S in self._yaml(t)]
        self.assertEqual(leaked, [], f"YAML spellings leaked: {leaked}")

    def test_toml_spellings_all_scrubbed(self):
        cases = {
            "inline_table": 'provider = { api_key = "%s" }\n' % self.S,
            "array": 'tokens = ["%s"]\n' % self.S,
            "multiline": "secret = '''\n%s\n'''\n" % self.S,
            "nested_inline": 'model = { auth = { token = "%s" } }\n' % self.S,
            "baseline": 'api_key = "%s"\n' % self.S,
        }
        leaked = [n for n, t in cases.items() if self.S in self._toml(t)]
        self.assertEqual(leaked, [], f"TOML spellings leaked: {leaked}")

    def test_non_secret_content_preserved(self):
        """Comments, key order and non-secret pairs stay byte-identical."""
        yaml_in = ("# comment\nmodel: qwen3-max\n"
                   "llm: {model: qwen3-max, temperature: 0.7}\n")
        self.assertEqual(self._yaml(yaml_in), yaml_in)
        toml_in = ('# comment\nname = "bot"\n'
                   'provider = { model = "qwen3-max", timeout = 30 }\n')
        self.assertEqual(self._toml(toml_in), toml_in)

    def test_http_credential_key_names_recognized(self):
        """Regression (BUG-016): plain ``key: value`` lines with common HTTP
        credential key names (authorization / bearer / cookie / session_id)
        leaked because the vocabulary only knew key/token/secret suffixes."""
        from ms_agent.agent_hub._workspace import is_secret_key
        for key in ("authorization", "Authorization", "bearer", "cookie",
                    "cookies", "set-cookie", "session_id", "sessionid",
                    "x-api-key"):
            self.assertTrue(is_secret_key(key), f"{key} not recognized")
            leaked = self._yaml(f"{key}: SENTINEL-BUG016-TOKEN\n")
            self.assertNotIn("SENTINEL-BUG016-TOKEN", leaked, key)
        # No over-reach on ordinary keys.
        for key in ("model", "session_timeout", "author", "bookkeeper"):
            self.assertFalse(is_secret_key(key), f"{key} wrongly flagged")


class TestFailClosedUploadSanitize(unittest.TestCase):
    """Malformed config files must be REFUSED on upload, not pushed verbatim.

    Regression (BUG-012): a syntactically broken ``agent.json`` /
    ``settings.json`` skipped sanitizing and went to the remote repo with
    plaintext keys and exit code 0.  Upload now fails closed; the inbound
    (download) direction keeps its best-effort pass-through.
    """

    S = "SENTINEL-BUG012-PLAINTEXT-KEY"
    BROKEN = '{"id": "bot", "api_key": "%s",,,'

    def test_qwenpaw_broken_agent_json_refused_on_upload(self):
        spec = QwenpawWorkspace(agent_name="default")
        with self.assertRaises(ValueError):
            spec.sanitize_outbound_file("agent.json",
                                        (self.BROKEN % self.S).encode())

    def test_msagent_broken_settings_json_refused_on_upload(self):
        from ms_agent.agent_hub.frameworks.ms_agent import MsAgentWorkspace
        spec = MsAgentWorkspace(agent_name="default")
        with self.assertRaises(ValueError):
            spec.sanitize_outbound_file("settings.json",
                                        (self.BROKEN % self.S).encode())

    def test_inbound_direction_still_best_effort(self):
        """Download keeps pass-through: a broken remote file must not abort
        the whole download (it adds no new exposure when written locally)."""
        spec = QwenpawWorkspace(agent_name="default")
        raw = (self.BROKEN % self.S).encode()
        self.assertEqual(spec.sanitize_inbound_file("agent.json", raw), raw)

    @mock.patch("pathlib.Path.home")
    def test_cmd_upload_fails_with_clear_message(self, mock_home):
        """End-to-end: upload aborts with exit code 1 BEFORE any network or
        credential use, and the message names the broken file."""
        from ms_agent.agent_hub._commands import cmd_upload
        with tempfile.TemporaryDirectory() as td:
            mock_home.return_value = Path(td)
            ws = Path(td) / "ws"
            ws.mkdir()
            (ws / "agent.json").write_text(self.BROKEN % self.S)
            rc = cmd_upload("qwenpaw", name="default", local_dir=str(ws),
                            repo="owner/broken-demo")
            self.assertEqual(rc, 1)


class TestMsAgentSkillsGovernance(unittest.TestCase):
    """skills.json ``disabled`` is a machine-local safety switch, not content.

    Sync must move only the ``sources`` inventory: a download must never flip
    the local enable/disable state, and an upload must never publish it.
    """

    def _spec(self, root):
        from ms_agent.agent_hub.frameworks.ms_agent import MsAgentWorkspace
        return MsAgentWorkspace(agent_name="default", local_dir=root)

    def test_inbound_preserves_local_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "skills.json").write_text(
                json.dumps({"sources": ["old"], "disabled": ["danger-skill"]}))
            incoming = json.dumps(
                {"sources": ["new"], "disabled": []}).encode()
            out = json.loads(self._spec(root).sanitize_inbound_file(
                "skills.json", incoming))
            # sources sync in, but the local safety switch is preserved.
            self.assertEqual(out["sources"], ["new"])
            self.assertEqual(out["disabled"], ["danger-skill"])

    def test_inbound_no_local_file_drops_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)  # no local skills.json
            incoming = json.dumps(
                {"sources": ["x"], "disabled": ["remote-switch"]}).encode()
            out = json.loads(self._spec(root).sanitize_inbound_file(
                "skills.json", incoming))
            # nothing local to preserve -> the remote switch is not honored.
            self.assertNotIn("disabled", out)
            self.assertEqual(out["sources"], ["x"])

    def test_outbound_strips_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = json.dumps(
                {"sources": ["x"], "disabled": ["secret-off"]}).encode()
            out = json.loads(self._spec(root).sanitize_outbound_file(
                "skills.json", payload))
            self.assertEqual(out["sources"], ["x"])
            self.assertNotIn("disabled", out)

    def test_malformed_skills_json_passes_through(self):
        with tempfile.TemporaryDirectory() as td:
            spec = self._spec(Path(td))
            raw = b'{"sources": [,,,'
            self.assertEqual(
                spec.sanitize_inbound_file("skills.json", raw), raw)
            self.assertEqual(
                spec.sanitize_outbound_file("skills.json", raw), raw)


class TestInstallRootProbing(unittest.TestCase):
    """``--local_dir`` may point at the install root, not just the data root.

    Nanobot keeps its files in ``.nanobot/workspace/``, so passing the natural
    ``.nanobot`` used to abort with "no nanobot files found" (users had to
    guess the extra level). ``_ROOT_SUBDIRS`` now normalizes it. The probe is
    deliberately conservative -- it descends only into a declared sub-path
    that already exists, and never when the given dir holds files itself --
    because this same path is the WRITE target for download/convert.
    """

    def _make_install(self, td, name=".nanobot"):
        root = Path(td) / name
        ws = root / "workspace"
        ws.mkdir(parents=True)
        (ws / "AGENTS.md").write_text("# Agents\n")
        (ws / "SOUL.md").write_text("# Soul\nGOLD-SOUL\n")
        return root, ws

    def test_install_root_resolves_to_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root, ws = self._make_install(td)
            spec = build_spec("nanobot", "default", str(root))
            self.assertEqual(spec.root, ws)
            self.assertEqual(len(spec.collect_bytes()), 2)

    def test_data_root_still_works_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            _root, ws = self._make_install(td)
            spec = build_spec("nanobot", "default", str(ws))
            self.assertEqual(spec.root, ws)
            self.assertEqual(len(spec.collect_bytes()), 2)

    def test_own_files_win_over_a_nested_subdir(self):
        """A dir holding files IS the data root, even with a ``workspace/``."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "both"
            (base / "workspace").mkdir(parents=True)
            (base / "SOUL.md").write_text("# top\n")
            spec = build_spec("nanobot", "default", str(base))
            self.assertEqual(spec.root, base)

    def test_empty_dir_is_not_redirected(self):
        """A fresh out-dir must not be silently relocated into ``workspace/``."""
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "fresh-out"
            empty.mkdir()
            spec = build_spec("nanobot", "default", str(empty))
            self.assertEqual(spec.root, empty)

    def test_convert_accepts_install_root(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ws = self._make_install(td)
            out = Path(td) / "out"
            rc = cmd_convert(
                "nanobot", "ms-agent",
                from_name="default", target_name="default",
                local_dir=str(root), out_dir=str(out))
            self.assertEqual(rc, 0)
            hits = [
                p for p in out.rglob("*")
                if p.is_file() and "GOLD-SOUL" in p.read_text()
            ]
            self.assertEqual(len(hits), 1, f"persona lost: {hits}")

    def test_frameworks_without_subdirs_are_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            for fw in ("qoder", "hermes", "ms-agent", "openclaw", "qwenpaw"):
                given = Path(td) / fw
                given.mkdir()
                spec = build_spec(fw, "default", str(given))
                self.assertEqual(spec.root, given, f"{fw} root changed")


if __name__ == "__main__":
    unittest.main()
