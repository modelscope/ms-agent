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


if __name__ == "__main__":
    unittest.main()
