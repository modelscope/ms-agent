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

    def test_hermes_metadata_hermes_tags_marks_app_native_skill(self):
        """BUG-0828: Hermes app-native skills (desktop plugins, themes, the
        ``apple/`` / ``media/`` category libraries) are seeded OUTSIDE the
        ``.bundled_manifest`` sync and carry a ``metadata.hermes`` catalog
        block -- ``tags`` is the shape marker. A ``metadata.hermes.config``
        settings block or a bare ``hermes`` key is a legitimate user skill
        (BUG-022 precedent) and must stay.
        """
        spec = build_spec("hermes", "default", str(self.root))
        base = spec.workspace_root
        # App-native top-level skill: metadata.hermes.tags -> dropped.
        (base / "skills" / "hermes-themes").mkdir(parents=True)
        (base / "skills" / "hermes-themes" / "SKILL.md").write_text(
            "---\nname: hermes-themes\nmetadata:\n  hermes:\n"
            "    tags: [theme, skin]\n    related_skills: []\n---\n# themes\n",
            encoding="utf-8")
        # App-native skill nested in a category dir, with an asset -> the
        # whole tree is dropped.
        cat = base / "skills" / "media" / "heartmula"
        cat.mkdir(parents=True)
        (cat / "SKILL.md").write_text(
            "---\nname: heartmula\nmetadata:\n  hermes:\n"
            "    tags: [music]\n---\n# heartmula\n", encoding="utf-8")
        (cat / "references").mkdir()
        (cat / "references" / "models.md").write_text("bundled asset\n")
        # User skill with metadata.hermes.config SETTINGS (no tags) -> kept.
        (base / "skills" / "my-configured").mkdir()
        (base / "skills" / "my-configured" / "SKILL.md").write_text(
            "---\nname: my-configured\nmetadata:\n  hermes:\n"
            "    config:\n      api_url: https://example.com\n---\nBODY\n",
            encoding="utf-8")
        # User skill with a bare hermes key (no catalog shape) -> kept.
        (base / "skills" / "my-bare-meta").mkdir()
        (base / "skills" / "my-bare-meta" / "SKILL.md").write_text(
            "---\nname: my-bare-meta\nmetadata:\n  hermes: {}\n---\nBODY\n",
            encoding="utf-8")
        collected = spec.collect()
        self.assertNotIn("skills/hermes-themes/SKILL.md", collected)
        self.assertNotIn("skills/media/heartmula/SKILL.md", collected)
        self.assertNotIn("skills/media/heartmula/references/models.md",
                         collected)
        self.assertIn("skills/my-configured/SKILL.md", collected)
        self.assertIn("skills/my-bare-meta/SKILL.md", collected)

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


class TestOpenhumanWorkspaceLiveness(unittest.TestCase):
    """BUG-0828: reinstalls / user-id migrations leave SEVERAL ``users/<id>``
    dirs behind. The resolver must pick the LIVE workspace by liveness score
    (``agent_profiles.json`` / ``personalities/`` / ``SOUL.md``), not the
    alphabetically-first one -- a stale ``users/local`` shell used to shadow
    the active ``users/local-u-...`` workspace and every convert silently
    read the wrong persona.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / ".openhuman"
        # Stale shell: sorts FIRST, keeps only a persona file.
        self.stale = self.root / "users" / "local" / "workspace"
        self.stale.mkdir(parents=True)
        (self.stale / "SOUL.md").write_text("# stale soul\n")
        # Live workspace: machine-generated id sorts AFTER the shell.
        self.live = (self.root / "users" / "local-u-x1" / "workspace")
        self.live.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_live_workspace_beats_stale_sorted_first(self):
        (self.live / "agent_profiles.json").write_text(
            json.dumps({"activeProfileId": "p"}))
        (self.live / "personalities" / "p").mkdir(parents=True)
        (self.live / "SOUL.md").write_text("# live soul\n")
        spec = build_spec("openhuman", "default", str(self.root))
        self.assertEqual(spec.root, self.live)
        self.assertEqual(spec.collect()["SOUL.md"], "# live soul\n")

    def test_personalities_alone_outscores_soul_only_shell(self):
        # No agent_profiles.json anywhere: personalities/ (2) + SOUL.md (1)
        # still beats the shell's SOUL.md (1).
        (self.live / "personalities" / "p").mkdir(parents=True)
        (self.live / "SOUL.md").write_text("# live soul\n")
        spec = build_spec("openhuman", "default", str(self.root))
        self.assertEqual(spec.root, self.live)

    def test_no_markers_falls_back_to_sorted_first(self):
        spec = build_spec("openhuman", "default", str(self.root))
        self.assertEqual(spec.root, self.stale)

    def test_tie_falls_back_to_sorted_first(self):
        for ws in (self.stale, self.live):
            (ws / "agent_profiles.json").write_text("{}")
        spec = build_spec("openhuman", "default", str(self.root))
        self.assertEqual(spec.root, self.stale)

    def test_local_dir_one_level_above_data_root_is_probed(self):
        # A backup dir that merely CONTAINS ``.openhuman/`` resolves through.
        (self.live / "agent_profiles.json").write_text("{}")
        spec = build_spec("openhuman", "default", str(self.root.parent))
        self.assertEqual(spec.root, self.live)

    def test_user_dir_without_workspace_keeps_legacy_path(self):
        # users/<id> exists but has no workspace/ yet: report the canonical
        # path anyway (status must not fail on a fresh install). Uses its own
        # tree -- setUp's dirs all have workspace/ already.
        root = Path(self.tmp.name) / "fresh-oh" / ".openhuman"
        no_ws = root / "users" / "aaa"
        no_ws.mkdir(parents=True)
        spec = build_spec("openhuman", "default", str(root))
        self.assertEqual(spec.root, no_ws / "workspace")

    def test_convert_end_to_end_picks_live_user_active_profile(self):
        """Full BUG-0828 shape: stale user sorts first; the LIVE user's
        ACTIVE profile carries skills (+openhuman provenance sidecars) but no
        SOUL.md of its own. A name-less convert must resolve the live
        workspace, pick the active profile, migrate the skills without the
        ``_meta.json`` sidecar, and fold the workspace-level SOUL fallback
        into the target persona.
        """
        profile = self.live / "personalities" / "personalized-agent"
        (profile / "skills" / "weather").mkdir(parents=True)
        (self.live / "agent_profiles.json").write_text(
            json.dumps({"activeProfileId": "personalized-agent"}))
        (self.live / "SOUL.md").write_text("# live soul\nGOLD-PERSONA\n")
        (profile / "MEMORY.md").write_text("GOLD-MEMORY\n")
        (profile / "skills" / "weather" / "SKILL.md").write_text(
            "GOLD-WEATHER\n")
        (profile / "skills" / "weather" / "_meta.json").write_text('{"k": 1}')
        out = Path(self.tmp.name) / "out"
        rc = cmd_convert("openhuman", "ms-agent", None, None,
                         str(self.root), str(out))
        self.assertEqual(rc, 0)
        rels = {
            str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()
        }
        self.assertIn("skills/weather/SKILL.md", rels)
        self.assertNotIn("skills/weather/_meta.json", rels)
        all_text = "".join(
            p.read_text(encoding="utf-8") for p in out.rglob("*")
            if p.is_file())
        self.assertIn("GOLD-PERSONA", all_text)
        self.assertIn("GOLD-MEMORY", all_text)
        self.assertIn("GOLD-WEATHER", all_text)
        # the stale shell's persona must NOT leak into the output
        self.assertNotIn("stale soul", all_text)


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
        return scrub_yaml_secrets(text)

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


class TestUrlAndArgSecretHelpers(unittest.TestCase):
    """Shared carrier helpers: URL credentials and stdio flag values.

    Secrets travel in places no key-name vocabulary can reach: inside URLs
    (query parameters, userinfo passwords) and as positional values after a
    secret-named CLI flag (``--api-key VALUE``). These helpers strip them
    while leaving clean input byte-identical.
    """

    def test_url_secret_param_values_blanked_name_kept(self):
        # Names stay, values go -- consistent with headers / env / args, and
        # the remote still sees the parameter structure.
        from ms_agent.agent_hub._workspace import scrub_url_secrets
        out = scrub_url_secrets(
            "https://api.example.com/v1?api_key=S1&token=S2&model=y")
        self.assertEqual(out, "https://api.example.com/v1?api_key=&token="
                            "&model=y")

    def test_url_only_secret_params_keep_query_mark(self):
        from ms_agent.agent_hub._workspace import scrub_url_secrets
        out = scrub_url_secrets("https://api.example.com/sse?api_key=S1")
        self.assertEqual(out, "https://api.example.com/sse?api_key=")

    def test_url_extra_query_vocabulary(self):
        # OAuth codes / signatures / passwords are credentials in a URL even
        # though a bare config key named ``code`` is not.
        from ms_agent.agent_hub._workspace import scrub_url_secrets
        out = scrub_url_secrets(
            "https://cb.example.com/x?code=oa1&sig=S&signature=S&pwd=S&v=1")
        self.assertEqual(out, "https://cb.example.com/x?code=&sig="
                              "&signature=&pwd=&v=1")

    def test_url_userinfo_password_stripped(self):
        from ms_agent.agent_hub._workspace import scrub_url_secrets
        out = scrub_url_secrets("https://user:pa55@host.example.com/p?x=1")
        self.assertEqual(out, "https://user@host.example.com/p?x=1")

    def test_url_bare_token_userinfo_dropped(self):
        # No colon -> cannot be told from a PAT (https://ghp_xxx@host);
        # fail-closed: the whole userinfo goes.
        from ms_agent.agent_hub._workspace import scrub_url_secrets
        self.assertEqual(
            scrub_url_secrets("https://ghp_LEAKTOKEN@host.example.com/x"),
            "https://host.example.com/x")

    def test_url_whitespace_guard_no_truncation(self):
        # A string containing whitespace is prose that merely CONTAINS a url,
        # not a bare URL: it must survive byte-identical, never truncated.
        from ms_agent.agent_hub._workspace import scrub_url_secrets
        text = "https://docs.example.com/g?tokens=abc rest of sentence"
        self.assertEqual(scrub_url_secrets(text), text)

    def test_url_fragment_and_port_preserved(self):
        from ms_agent.agent_hub._workspace import scrub_url_secrets
        url = "https://host.example.com:8443/p?a=1#frag"
        self.assertEqual(scrub_url_secrets(url), url)

    def test_url_no_scheme_is_not_a_url(self):
        from ms_agent.agent_hub._workspace import scrub_url_secrets
        for val in ("not a url ?token=x", "example.com?token=x", "", 42):
            self.assertEqual(scrub_url_secrets(val), val)

    def test_clean_url_round_trips_byte_identical(self):
        from ms_agent.agent_hub._workspace import scrub_url_secrets
        for url in ("https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "https://host/x?model=qwen&temp=0.7",
                    "https://host",
                    "http://[::1]:8080/path"):
            self.assertEqual(scrub_url_secrets(url), url)

    def test_args_flag_value_blanked(self):
        from ms_agent.agent_hub._workspace import scrub_args_secrets
        out = scrub_args_secrets(
            ["-y", "srv", "--api-key", "SECRET", "--model", "qwen"])
        self.assertEqual(out, ["-y", "srv", "--api-key", "",
                               "--model", "qwen"])

    def test_args_flag_equals_form_blanked(self):
        from ms_agent.agent_hub._workspace import scrub_args_secrets
        out = scrub_args_secrets(["run", "--token=SECRET", "--port", "8080"])
        self.assertEqual(out, ["run", "--token=", "--port", "8080"])

    def test_args_single_dash_equals_form_blanked(self):
        from ms_agent.agent_hub._workspace import scrub_args_secrets
        out = scrub_args_secrets(["srv", "-token=SECRET"])
        self.assertEqual(out, ["srv", "-token="])

    def test_args_docker_env_assignment_blanked(self):
        # Official docker-MCP spelling: the flag is ``-e`` (not in the
        # vocabulary); the NEXT element is a NAME=VALUE pair whose NAME is.
        from ms_agent.agent_hub._workspace import scrub_args_secrets
        out = scrub_args_secrets(
            ["run", "-i", "--rm", "-e", "GITHUB_TOKEN=ghp_LEAK", "img"])
        self.assertEqual(out, ["run", "-i", "--rm", "-e", "GITHUB_TOKEN=",
                               "img"])

    def test_args_benign_env_assignment_preserved(self):
        from ms_agent.agent_hub._workspace import scrub_args_secrets
        args = ["run", "-e", "RUST_LOG=debug", "-e", "IMAGE=nginx", "img"]
        self.assertEqual(scrub_args_secrets(args), args)

    def test_args_url_element_not_a_pair(self):
        # ``://`` marks a URL, never a NAME=VALUE assignment.
        from ms_agent.agent_hub._workspace import scrub_args_secrets
        args = ["--url", "https://h.example.com/p?a=1"]
        self.assertEqual(scrub_args_secrets(args), args)

    def test_args_flag_value_followed_by_flag_not_eaten(self):
        from ms_agent.agent_hub._workspace import scrub_args_secrets
        out = scrub_args_secrets(["--api-key", "--verbose", "x"])
        self.assertEqual(out, ["--api-key", "--verbose", "x"])

    def test_args_clean_list_byte_identical(self):
        from ms_agent.agent_hub._workspace import scrub_args_secrets
        args = ["-y", "mcp-server", "--port", "8080", "--model", "qwen"]
        self.assertEqual(scrub_args_secrets(args), args)

    def test_args_trailing_secret_flag_without_value(self):
        from ms_agent.agent_hub._workspace import scrub_args_secrets
        self.assertEqual(scrub_args_secrets(["srv", "--token"]),
                         ["srv", "--token"])


class TestMsAgentOutboundLeakCarriers(unittest.TestCase):
    """ms-agent upload must not leak url / headers / args carriers.

    ``settings.json`` and ``mcp.json`` carry provider and MCP server
    definitions; credentials hide in URL query strings / userinfo, in
    arbitrary-named HTTP headers and in stdio command lines -- none of which
    a key-name vocabulary can catch.
    """

    def setUp(self):
        from ms_agent.agent_hub.frameworks.ms_agent import MsAgentWorkspace
        self.spec = MsAgentWorkspace(agent_name="default")

    SETTINGS = {
        "providers": {
            "dashscope": {
                "name": "dashscope", "protocol": "openai",
                "api_key": "sk-LEAK-provider",
                "base_url": "https://dashscope.aliyuncs.com/compatible/v1",
                "models": ["qwen3-max"],
            },
            "my-gateway": {
                "name": "gateway", "protocol": "openai",
                "api_key": "sk-LEAK-gateway",
                "base_url": "https://gw.example.com/v1?token=LEAK-url-token",
                "models": [],
            },
        },
        "default_model": "dashscope/qwen3-max",
    }

    MCP = {
        "mcpServers": {
            "remote-http": {
                "url": "https://api.example.com/msse?api_key=LEAK-url-key",
                "transport": "sse",
                "headers": {
                    "Authorization": "Bearer LEAK-bearer",
                    "x-api-key": "LEAK-header-key",
                    "X-Auth-Code": "LEAK-custom-header",
                },
                "enabled": True,
            },
            "userinfo": {
                "url": "https://user:LEAK-pass@host.example.com/sse",
                "transport": "sse",
            },
            "local-stdio": {
                "command": "npx",
                "args": ["-y", "mcp-server", "--api-key", "LEAK-arg-key",
                         "--model", "qwen"],
                "env": {"OPENAI_API_KEY": "LEAK-env-key"},
                "enabled": True,
            },
        },
    }

    def _out(self, rel, data):
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return json.loads(self.spec.sanitize_outbound_file(rel, raw))

    def test_no_leak_tokens_survive_upload(self):
        for rel, data in (("settings.json", self.SETTINGS),
                          ("mcp.json", self.MCP)):
            out = json.dumps(self._out(rel, data))
            self.assertNotIn("LEAK", out, f"{rel} leaked secrets")

    def test_structure_and_non_secrets_preserved(self):
        s = self._out("settings.json", self.SETTINGS)
        self.assertEqual(s["default_model"], "dashscope/qwen3-max")
        self.assertEqual(s["providers"]["dashscope"]["models"], ["qwen3-max"])
        # clean URL untouched; secret query param blanked (name kept):
        self.assertEqual(
            s["providers"]["dashscope"]["base_url"],
            "https://dashscope.aliyuncs.com/compatible/v1")
        self.assertEqual(
            s["providers"]["my-gateway"]["base_url"],
            "https://gw.example.com/v1?token=")
        m = self._out("mcp.json", self.MCP)
        remote = m["mcpServers"]["remote-http"]
        self.assertEqual(remote["url"],
                         "https://api.example.com/msse?api_key=")
        self.assertEqual(remote["transport"], "sse")
        self.assertEqual(remote["enabled"], True)
        # header names kept (structure visible), values wiped:
        self.assertEqual(set(remote["headers"]),
                         {"Authorization", "x-api-key", "X-Auth-Code"})
        self.assertEqual(set(remote["headers"].values()), {""})
        self.assertEqual(m["mcpServers"]["userinfo"]["url"],
                         "https://user@host.example.com/sse")
        stdio = m["mcpServers"]["local-stdio"]
        self.assertEqual(stdio["command"], "npx")
        self.assertEqual(stdio["args"],
                         ["-y", "mcp-server", "--api-key", "",
                          "--model", "qwen"])
        self.assertEqual(stdio["env"], {"OPENAI_API_KEY": ""})

    def test_free_text_with_url_not_truncated(self):
        # Review must-fix: a prompt/description string that merely CONTAINS
        # a URL (whitespace present) must not be treated as a URL -- the old
        # behavior cut everything after the query string away.
        data = {"description": "see https://docs.example.com/g?tokens=abc "
                               "for the rest of this sentence"}
        out = self._out("settings.json", data)
        self.assertEqual(out["description"], data["description"])

    def test_docker_env_args_and_bare_userinfo(self):
        # Review must-fix: docker-style ``-e NAME=VALUE`` and colon-less
        # ``https://<token>@host`` userinfo both leaked before.
        data = {"mcpServers": {
            "docker": {
                "command": "docker",
                "args": ["run", "-i", "--rm", "-e",
                         "GITHUB_TOKEN=ghp_LEAK", "img"],
            },
            "pat": {"url": "https://ghp_LEAKTOKEN@host.example.com/sse"},
        }}
        out = self._out("mcp.json", data)
        dumped = json.dumps(out)
        self.assertNotIn("LEAK", dumped)
        self.assertEqual(out["mcpServers"]["docker"]["args"],
                         ["run", "-i", "--rm", "-e", "GITHUB_TOKEN=", "img"])
        self.assertEqual(out["mcpServers"]["pat"]["url"],
                         "https://host.example.com/sse")

    def test_argv_alias_scrubbed_like_args(self):
        data = {"mcpServers": {"s": {
            "command": "srv", "argv": ["--token", "LEAK-v"]}}}
        out = self._out("mcp.json", data)
        self.assertEqual(out["mcpServers"]["s"]["argv"], ["--token", ""])

    def test_inbound_direction_scrubs_too(self):
        raw = json.dumps(self.MCP, ensure_ascii=False).encode("utf-8")
        out = self.spec.sanitize_inbound_file("mcp.json", raw).decode()
        self.assertNotIn("LEAK", out)


class TestQwenpawOutboundLeakCarriers(unittest.TestCase):
    """qwenpaw agent.json upload must close the same three carriers."""

    def setUp(self):
        self.spec = QwenpawWorkspace(agent_name="paw_qa_01")

    SRC = json.dumps({
        "id": "bot",
        "model": {"api_key": "sk-SECRET-1", "model": "qwen-max"},
        "mcp": {
            "clients": {
                "remote": {
                    "url": "https://mcp.example.com/sse?api_key=SECRET-URL",
                    "headers": {"X-Auth-Code": "SECRET-HEADER"},
                },
                "stdio": {
                    "command": "npx",
                    "args": ["-y", "srv", "--token=SECRET-ARG"],
                },
            },
        },
    })

    def test_outbound_scrubs_url_headers_args(self):
        out = self.spec._strip_outbound_agent_json(self.SRC)
        self.assertNotIn("SECRET", out)
        data = json.loads(out)
        remote = data["mcp"]["clients"]["remote"]
        self.assertEqual(remote["url"], "https://mcp.example.com/sse?api_key=")
        self.assertEqual(remote["headers"], {"X-Auth-Code": ""})
        self.assertEqual(data["mcp"]["clients"]["stdio"]["args"],
                         ["-y", "srv", "--token="])
        self.assertEqual(data["model"]["model"], "qwen-max")


class TestYamlOutboundLeakCarriers(unittest.TestCase):
    """hermes config.yaml must close the url / headers / args carriers in
    every legal YAML spelling, without touching clean lines."""

    def _scrub(self, text):
        from ms_agent.agent_hub._workspace import scrub_yaml_secrets
        return scrub_yaml_secrets(text)

    CONFIG = (
        "# hermes config\n"
        "model: qwen3-max\n"
        "llm:\n"
        "  base_url: https://gw.example.com/v1?token=LEAK-url-token\n"
        "  api_key: LEAK-key\n"
        "mcp_servers:\n"
        "  remote:\n"
        "    url: https://api.example.com/msse?api_key=LEAK-url-key&v=2\n"
        "    transport: sse\n"
        "    headers:\n"
        "      Authorization: Bearer LEAK-bearer\n"
        "      X-Auth-Code: LEAK-custom-header\n"
        "    enabled: true\n"
        "  gateway:\n"
        "    url: https://user:LEAK-pass@host.example.com/path\n"
        "  stdio:\n"
        "    command: npx\n"
        "    args:\n"
        "      - -y\n"
        "      - mcp-server\n"
        "      - --api-key\n"
        "      - LEAK-arg-key\n"
        "      - --model\n"
        "      - qwen\n"
        "    env:\n"
        "      OPENAI_API_KEY: LEAK-env-key\n"
        "  flow:\n"
        "    command: uvx\n"
        "    args: [run, --token, LEAK-flow-arg, --port, \"8080\"]\n"
        "    headers: {X-Custom: LEAK-flow-header}\n"
        "plain: value\n"
    )

    def test_no_leak_tokens_survive(self):
        out = self._scrub(self.CONFIG)
        self.assertNotIn("LEAK", out)

    def test_structure_preserved(self):
        out = self._scrub(self.CONFIG)
        self.assertIn("model: qwen3-max", out)
        self.assertIn("plain: value", out)
        self.assertIn("url: https://api.example.com/msse?api_key=&v=2", out)
        self.assertIn("url: https://user@host.example.com/path", out)
        self.assertIn("base_url: https://gw.example.com/v1?token=", out)
        self.assertIn("Authorization: ''", out)
        self.assertIn("X-Auth-Code: ''", out)
        self.assertIn("- -y", out)
        self.assertIn("- mcp-server", out)
        self.assertIn("- --api-key", out)
        self.assertIn("- --model", out)
        self.assertIn("- qwen", out)
        self.assertIn("- ''", out)
        self.assertIn("args: [run, --token, '', --port, \"8080\"]", out)
        self.assertIn("headers: {X-Custom: ''}", out)

    def test_clean_config_byte_identical(self):
        clean = (
            "# comment\n"
            "model: qwen3-max\n"
            "mcp_servers:\n"
            "  remote:\n"
            "    url: https://api.example.com/msse?v=2\n"
            "    transport: sse\n"
            "  stdio:\n"
            "    args:\n"
            "      - -y\n"
            "      - --port\n"
            "      - \"8080\"\n"
        )
        self.assertEqual(self._scrub(clean), clean)

    def test_innocuous_headers_cleared_too(self):
        """headers is a wholesale secret bag: header names cannot be
        enumerated (a gateway may demand ``X-Auth-Code``), so even innocuous
        values like ``Accept`` are deliberately cleared -- fail-closed."""
        text = ("mcp_servers:\n"
                "  remote:\n"
                "    headers:\n"
                "      Accept: application/json\n")
        self.assertIn("Accept: ''", self._scrub(text))

    def test_top_level_bags_and_args_scrubbed_anywhere(self):
        # Review fix: bags/args used to be scoped to the mcp_servers block,
        # so top-level ones leaked. Policy is now global (JSON/TOML parity).
        text = ("headers:\n"
                "  X-Auth-Code: LEAK-header\n"
                "env:\n"
                "  RANDOM_NAME: LEAK-env\n"
                "args:\n"
                "  - --token\n"
                "  - LEAK-arg\n")
        out = self._scrub(text)
        self.assertNotIn("LEAK", out)
        self.assertIn("X-Auth-Code: ''", out)
        self.assertIn("RANDOM_NAME: ''", out)
        self.assertIn("- ''", out)

    def test_block_opener_with_inline_comment_recognized(self):
        # ``mcp_servers:  # remote`` must still open the block.
        text = ("mcp_servers:  # remote tools\n"
                "  fs:\n"
                "    headers:\n"
                "      X-Auth-Code: LEAK\n")
        out = self._scrub(text)
        self.assertNotIn("LEAK", out)
        self.assertIn("mcp_servers:  # remote tools", out)

    def test_url_scalar_trailing_comment_kept_separate(self):
        # Review fix: the comment used to be glued into the scrubbed value.
        out = self._scrub("url: https://h.example.com/p?token=X # note\n")
        self.assertEqual(out, "url: https://h.example.com/p?token= # note\n")

    def test_block_args_env_assignment_blanked(self):
        text = ("mcp_servers:\n"
                "  d:\n"
                "    args:\n"
                "      - run\n"
                "      - -e\n"
                "      - GITHUB_TOKEN=ghp_LEAK\n")
        out = self._scrub(text)
        self.assertNotIn("LEAK", out)
        self.assertIn("- GITHUB_TOKEN=", out)


class TestTomlOutboundLeakCarriers(unittest.TestCase):
    """openhuman config.toml must close the url / headers / args carriers."""

    def _scrub(self, text):
        from ms_agent.agent_hub.frameworks.openhuman import \
            OpenhumanWorkspace
        return OpenhumanWorkspace(
            agent_name="default")._scrub_toml_secrets(text)

    CONFIG = (
        "# openhuman config\n"
        "[model]\n"
        'provider = "openai"\n'
        'api_key = "LEAK-key"\n'
        "[providers.gateway]\n"
        'base_url = "https://gw.example.com/v1?token=LEAK-url&mode=fast"\n'
        'endpoint = "https://user:LEAK-pass@ep.example.com/x"\n'
        "[mcp.remote]\n"
        "headers = { Authorization = \"Bearer LEAK-b\", X-Custom = "
        "\"LEAK-c\" }\n"
        'args = ["-y", "srv", "--api-key", "LEAK-arg", "--port", "8080"]\n'
        'url = "https://mcp.example.com/sse?api_key=LEAK-u&v=2"\n'
        # Block table-section spellings (NOT inline tables): a headers / env
        # section whose inner key names are arbitrary (incl. a quoted key that
        # the bare-key pattern cannot match).
        "[mcp.block.headers]\n"
        'X-Auth-Code = "LEAK-block-header"\n'
        '"X-Quoted-Key" = "LEAK-quoted-header"\n'
        "[mcp.block.env]\n"
        'SOME_RANDOM_NAME = "LEAK-block-env"\n'
        # Multi-line args array with the secret on a continuation line.
        "[mcp.spawner]\n"
        "args = [\n"
        '  "-y",\n'
        '  "--token",\n'
        '  "LEAK-ml-arg",\n'
        '  "--model",\n'
        '  "qwen",\n'
        "]\n"
    )

    def test_no_leak_tokens_survive(self):
        self.assertNotIn("LEAK", self._scrub(self.CONFIG))

    def test_structure_preserved(self):
        out = self._scrub(self.CONFIG)
        self.assertIn('provider = "openai"', out)
        self.assertIn('base_url = "https://gw.example.com/v1?token=&mode=fast"',
                      out)
        self.assertIn('endpoint = "https://user@ep.example.com/x"', out)
        self.assertIn("headers = { Authorization = \"\", X-Custom = \"\" }",
                      out)
        self.assertIn(
            'args = ["-y", "srv", "--api-key", "", "--port", "8080"]', out)
        self.assertIn('url = "https://mcp.example.com/sse?api_key=&v=2"', out)
        # Block sections: the section headers survive, the inner values don't.
        self.assertIn("[mcp.block.headers]", out)
        self.assertIn('X-Auth-Code = ""', out)
        self.assertIn('"X-Quoted-Key" = ""', out)
        self.assertIn("[mcp.block.env]", out)
        self.assertIn('SOME_RANDOM_NAME = ""', out)
        # Multi-line args collapsed to one line with the secret value blanked.
        self.assertIn('args = ["-y", "--token", "", "--model", "qwen"]', out)

    def test_clean_config_byte_identical(self):
        # No bag section here: [...headers] / [...env] are fail-closed and
        # blank every value even when innocuous (same as the YAML scrubber).
        clean = (
            "# comment\n"
            'name = "bot"\n'
            'base_url = "https://gw.example.com/v1?mode=fast"\n'
            'args = ["-y", "srv", "--port", "8080"]\n'
            "[mcp.spawner]\n"
            'command = "srv"\n'
            "args = [\n"
            '  "-y",\n'
            '  "--port",\n'
            '  "8080",\n'
            "]\n"
        )
        self.assertEqual(self._scrub(clean), clean)

    def test_toml_dotted_key_through_bag(self):
        # ``mcp.fs.headers.X = v`` is the same as living under
        # ``[mcp.fs.headers]`` -- the dotted path must trigger the bag rule.
        out = self._scrub('mcp.fs.headers.X-Auth-Code = "LEAK"\n')
        self.assertEqual(out, 'mcp.fs.headers.X-Auth-Code = ""\n')

    def test_toml_quoted_url_trailing_comment(self):
        # Review fix: 'URL' # note used to pass through untouched.
        out = self._scrub('url = "https://h.example.com/p?token=LEAK" # x\n')
        self.assertEqual(out,
                         'url = "https://h.example.com/p?token=" # x\n')

    def test_toml_argv_alias_scrubbed(self):
        out = self._scrub('argv = ["--token", "LEAK"]\n')
        self.assertEqual(out, 'argv = ["--token", ""]\n')


class TestLeakCarrierEdgeCases(unittest.TestCase):
    """Tricky-but-legal shapes beyond the canonical test configs.

    Generated from an edge-case probe: every assertion locks behavior that was
    manually verified correct, so a future refactor cannot silently regress a
    corner nobody looked at (fragment handling, quoting, scoping, word
    boundaries...).
    """

    # ---- shared URL / args helpers -----------------------------------

    def test_url_userinfo_and_query_combined(self):
        from ms_agent.agent_hub._workspace import scrub_url_secrets
        self.assertEqual(
            scrub_url_secrets(
                "https://user:pa55@h.example.com/p?api_key=X&v=1"),
            "https://user@h.example.com/p?api_key=&v=1")

    def test_url_no_path_query_only(self):
        from ms_agent.agent_hub._workspace import scrub_url_secrets
        self.assertEqual(
            scrub_url_secrets("https://host.example.com?token=X"),
            "https://host.example.com?token=")

    def test_url_ws_scheme(self):
        from ms_agent.agent_hub._workspace import scrub_url_secrets
        self.assertEqual(
            scrub_url_secrets("ws://mcp.local/sse?api_key=X"),
            "ws://mcp.local/sse?api_key=")

    def test_url_fragment_preserved_when_query_stripped(self):
        from ms_agent.agent_hub._workspace import scrub_url_secrets
        self.assertEqual(
            scrub_url_secrets("https://h.example.com/p?token=X#frag=1"),
            "https://h.example.com/p?token=#frag=1")

    def test_args_chained_secret_flags(self):
        from ms_agent.agent_hub._workspace import scrub_args_secrets
        self.assertEqual(
            scrub_args_secrets(["--api-key", "A", "--token", "B"]),
            ["--api-key", "", "--token", ""])

    def test_args_word_boundary_no_false_positive(self):
        # ``tokenizer`` / ``keymap`` end in secret-ish substrings but are NOT
        # secret flags -- the vocabulary anchors on [_-] boundaries + end.
        from ms_agent.agent_hub._workspace import scrub_args_secrets
        args = ["--tokenizer", "cl100k", "--keymap", "vim"]
        self.assertEqual(scrub_args_secrets(args), args)

    def test_args_non_string_values_pass_through(self):
        from ms_agent.agent_hub._workspace import scrub_args_secrets
        self.assertEqual(
            scrub_args_secrets(["--api-key", 123, "-y"]),
            ["--api-key", 123, "-y"])

    # ---- JSON (ms-agent) ---------------------------------------------

    def test_json_headers_inside_list_item(self):
        from ms_agent.agent_hub._workspace import scrub_json_secrets
        data = {"servers": [{"headers": {"X-Auth-Code": "LEAK"}}]}
        scrub_json_secrets(data)
        self.assertEqual(data, {"servers": [{"headers": {"X-Auth-Code": ""}}]})

    def test_json_dict_nested_in_args_list(self):
        from ms_agent.agent_hub._workspace import scrub_json_secrets
        data = {"args": [{"env": {"K": "LEAK"}}]}
        scrub_json_secrets(data)
        self.assertEqual(data, {"args": [{"env": {"K": ""}}]})

    def test_json_uppercase_scheme_and_params(self):
        from ms_agent.agent_hub._workspace import scrub_json_secrets
        data = {"u": "HTTPS://HOST.example.com/p?TOKEN=LEAK&v=1"}
        scrub_json_secrets(data)
        self.assertEqual(data, {"u": "HTTPS://HOST.example.com/p?TOKEN=&v=1"})

    def test_json_empty_value_param_before_fragment(self):
        from ms_agent.agent_hub._workspace import scrub_json_secrets
        data = {"u": "https://h.example.com/p?api_key=#frag"}
        scrub_json_secrets(data)
        self.assertEqual(data, {"u": "https://h.example.com/p?api_key=#frag"})

    # ---- YAML (hermes) -----------------------------------------------

    def _yscrub(self, text):
        from ms_agent.agent_hub._workspace import scrub_yaml_secrets
        return scrub_yaml_secrets(text)

    def test_yaml_quoted_url_scalar(self):
        out = self._yscrub(
            'url: "https://host.example.com/sse?api_key=LEAK"\n')
        self.assertEqual(out, 'url: "https://host.example.com/sse?api_key="\n')

    def test_yaml_url_fragment_preserved(self):
        out = self._yscrub(
            "mcp_servers:\n"
            "  fs:\n"
            "    url: https://h.example.com/p?token=LEAK#frag=1\n")
        self.assertIn("url: https://h.example.com/p?token=#frag=1", out)

    def test_yaml_args_outside_mcp_block_scrubbed_globally(self):
        # Bags and args lists are scrubbed at ANY depth now (JSON/TOML
        # parity) -- a top-level args list gets the same positional scrub.
        text = "args:\n  - --api-key\n  - VALUE\n"
        self.assertEqual(self._yscrub(text), "args:\n  - --api-key\n  - ''\n")

    # ---- TOML (openhuman) --------------------------------------------

    def _tscrub(self, text):
        from ms_agent.agent_hub.frameworks.openhuman import \
            OpenhumanWorkspace
        return OpenhumanWorkspace(
            agent_name="default")._scrub_toml_secrets(text)

    def test_toml_array_of_tables_bag(self):
        out = self._tscrub("[[mcp.fs.headers]]\n"
                           'X-Auth-Code = "LEAK"\n')
        self.assertIn("[[mcp.fs.headers]]", out)
        self.assertIn('X-Auth-Code = ""', out)
        self.assertNotIn("LEAK", out)

    def test_toml_section_trailing_comment(self):
        out = self._tscrub("[mcp.fs.headers]  # auth bag\n"
                           'X-Auth-Code = "LEAK"\n')
        self.assertNotIn("LEAK", out)
        self.assertIn('X-Auth-Code = ""', out)

    def test_toml_multiline_array_in_bag_section(self):
        out = self._tscrub("[mcp.fs.env]\n"
                           "vals = [\n"
                           '  "LEAK",\n'
                           "]\n")
        self.assertNotIn("LEAK", out)
        self.assertIn("vals = []", out)

    def test_toml_single_quoted_url(self):
        out = self._tscrub(
            "base_url = 'https://h.example.com/v1?token=LEAK'\n")
        self.assertEqual(out, "base_url = 'https://h.example.com/v1?token='\n")


if __name__ == "__main__":
    unittest.main()
