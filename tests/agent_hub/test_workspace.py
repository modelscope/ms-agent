# Copyright (c) Alibaba, Inc. and its affiliates.
"""Sub-agent-aware workspace spec collection tests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ms_agent.agent_hub import FRAMEWORK_REGISTRY
from ms_agent.agent_hub._commands import build_spec
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
        license / builtin_skill_version / metadata.copaw frontmatter marker) but
        keeps the user's own skills (which have no such markers)."""
        spec = build_spec("hermes", "default", str(self.root))
        base = spec.workspace_root
        (base / "skills" / "docx").mkdir(parents=True, exist_ok=True)
        (base / "skills" / "docx" / "SKILL.md").write_text(
            "---\nname: docx\nlicense: MIT\n---\n# docx\nbuiltin\n", encoding="utf-8")
        (base / "skills" / "write").mkdir(parents=True, exist_ok=True)
        (base / "skills" / "write" / "SKILL.md").write_text(
            "# Write\nUser's own writing skill.\n", encoding="utf-8")
        collected = spec.collect()
        self.assertIn("skills/write/SKILL.md", collected)
        self.assertNotIn("skills/docx/SKILL.md", collected)

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
        (license / metadata.copaw|qwenpaw markers, no .bundled_manifest) are
        dropped with all their assets; user skills are kept."""
        spec = build_spec("qwenpaw", "default", str(self.root))
        base = spec.workspace_root
        docx = base / "skills" / "docx" / "scripts"
        docx.mkdir(parents=True, exist_ok=True)
        (base / "skills" / "docx" / "SKILL.md").write_text(
            "---\nname: docx\nlicense: Proprietary\n---\n# docx\n", encoding="utf-8")
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
    """ms-agent is single-agent: no {name} placeholder; collects persona/
    memory/skills/config under ~/.ms_agent."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_agent_layout_collect(self):
        spec = FRAMEWORK_REGISTRY["ms-agent"](agent_name="default", local_dir=self.root)
        self.assertEqual(spec.product_name, "ms-agent")
        self.assertFalse(any("{name}" in p for p in spec.patterns))
        (self.root / "profile.md").write_text("p")
        (self.root / "MEMORY.md").write_text("m")
        (self.root / "facts.json").write_text("{}")
        (self.root / "settings.json").write_text("{}")
        (self.root / "skill.json").write_text("{}")
        (self.root / "random.txt").write_text("x")
        (self.root / "skills" / "foo").mkdir(parents=True)
        (self.root / "skills" / "foo" / "SKILL.md").write_text("s")
        got = spec.collect()
        for f in ("profile.md", "MEMORY.md", "facts.json", "settings.json",
                  "skill.json", "skills/foo/SKILL.md"):
            self.assertIn(f, got)
        self.assertNotIn("random.txt", got)


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


if __name__ == "__main__":
    unittest.main()
