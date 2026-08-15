# Copyright (c) Alibaba, Inc. and its affiliates.
"""Cross-framework convert & download coverage for --target-name, content
correctness, all-mode round-trip byte-equality, default-agent boundaries, and
single-agent download.

These tests close gaps left by ``test_cli.py`` / ``test_upload_download.py``:
they were only asserting *presence* (``assertIn`` / ``is_file()``) and never
*correctness* (landing path per target layout, identity not polluted into shared
files, converted content free of template corruption such as the ``§`` bug).

All tests run fully offline via stub clients; no remote server is contacted.

Usage:
    python -m pytest tests/agent/test_convert_targetname.py -v
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ms_agent.agent_hub._commands import (
    build_spec,
    cmd_convert,
    cmd_download,
    convert_resources,
    repo_name,
)
from ms_agent.agent_hub._defaults import get_defaults
from ms_agent.agent_hub._workspace import (
    ALL_AGENT_NAME,
    DEFAULT_AGENT_NAME,
    FRAMEWORK_REGISTRY,
)
from modelscope_hub.agent._api import RemoteFileInfo
from ms_agent.agent_hub._sync import sha256_content


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _write(root: Path, files: dict) -> None:
    """Write {rel_path: content} under root."""
    for rel, content in files.items():
        fp = root / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")


def _read_all(root: Path) -> dict:
    """Return {rel_path: content} for every file under root."""
    out = {}
    for f in root.rglob("*"):
        if f.is_file():
            out[str(f.relative_to(root))] = f.read_text(encoding="utf-8")
    return out


# ===========================================================================
# P0-A: --target-name single-agent cross-framework convert landing behaviour
# ===========================================================================

class TestConvertTargetNameLanding(unittest.TestCase):
    """Assert where --target-name identity lands per target layout.

    root-per-agent (openclaw/qwenpaw): target-name lands via directory prefix.
    single-agent   (hermes):           target-name has no path effect (by design).
    file-per-agent (qoder):            target-name lands in agents/{name}.md,
                                       keeping the shared AGENTS.md clean.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        # A qwenpaw single sub-agent workspace (root-per-agent source).
        self.src = self.base / "src"
        # source is a qwenpaw bot-a sub-agent: write into its real workspace.
        _write(build_spec("qwenpaw", "bot-a", str(self.src)).workspace_root, {
            "SOUL.md": "# Soul\nBot A creative AI.\n",
            "PROFILE.md": "# Profile A\nBot A profile.\n",
            "skills/write/SKILL.md": "# Write\nWriting skill.\n",
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_qwenpaw_to_openclaw_targetname_lands_in_workspace_dir(self):
        """root-per-agent target: bot-a identity lands in workspace-bot-a/."""
        out = self.base / "openclaw_home"
        rc = cmd_convert(
            source_fw="qwenpaw", target_fw="openclaw",
            from_name="bot-a", target_name="bot-a",
            local_dir=str(self.src), out_dir=str(out),
        )
        self.assertEqual(rc, 0)
        files = _read_all(out / "workspace-bot-a")
        # SOUL identity preserved in target workspace dir.
        self.assertIn("SOUL.md", files)
        self.assertIn("Bot A creative AI.", files["SOUL.md"])
        # skill carried over.
        self.assertIn("skills/write/SKILL.md", files)

    def test_unchanged_source_defaults_dropped_and_no_target_scaffold(self):
        """convert carries only user-modified files: a source file byte-identical
        to the source default is dropped, and the target's own default templates
        are NOT scaffolded for files the user never customized."""
        qp_defaults = get_defaults("qwenpaw")
        src = self.base / "src_defaults"
        _write(build_spec("qwenpaw", "bot-a", str(src)).workspace_root, {
            "SOUL.md": "# Soul\nBot A creative AI.\n",     # modified -> carried
            "PROFILE.md": qp_defaults["PROFILE.md"],         # == default -> dropped
            "skills/write/SKILL.md": "# Write\nWriting skill.\n",
        })
        out = self.base / "openclaw_scaffold"
        rc = cmd_convert(
            source_fw="qwenpaw", target_fw="openclaw",
            from_name="bot-a", target_name="bot-a",
            local_dir=str(src), out_dir=str(out),
        )
        self.assertEqual(rc, 0)
        files = _read_all(out / "workspace-bot-a")
        # Real user content crossed over.
        self.assertIn("SOUL.md", files)
        self.assertIn("Bot A creative AI.", files["SOUL.md"])
        self.assertIn("skills/write/SKILL.md", files)
        # No target-default scaffolding for never-customized files.
        for scaffold in ("BOOTSTRAP.md", "HEARTBEAT.md", "TOOLS.md",
                         "IDENTITY.md", "USER.md", "AGENTS.md"):
            self.assertNotIn(scaffold, files,
                             f"{scaffold} is a target default and must not be scaffolded")

    def test_all_mode_dropped_default_not_resurrected_as_binary(self):
        """Regression: an unchanged-default sub-agent file dropped by
        drop_unchanged_defaults must NOT reappear via the binary passthrough.
        The passthrough subtracts the full PRE-drop text set, so only genuine
        binaries pass; dropped default text stays dropped."""
        qp = get_defaults("qwenpaw")
        src = self.base / "qp_all_src"
        _write(build_spec("qwenpaw", "default", str(src)).workspace_root, {
            "SOUL.md": "# Soul\nRoot real.\n",
        })
        _write(build_spec("qwenpaw", "bot-a", str(src)).workspace_root, {
            "SOUL.md": "# Soul\nBot A real.\n",
            "HEARTBEAT.md": qp["HEARTBEAT.md"],   # byte-identical default -> dropped
        })
        out = self.base / "oc_all_out"
        rc = cmd_convert(
            source_fw="qwenpaw", target_fw="openclaw",
            from_name="all", target_name="all",
            local_dir=str(src), out_dir=str(out),
        )
        self.assertEqual(rc, 0)
        files = _read_all(out)
        self.assertIn("workspace-bot-a/SOUL.md", files)
        self.assertNotIn(
            "workspace-bot-a/HEARTBEAT.md", files,
            "dropped unchanged default must not resurface via binary passthrough")

    def test_qwenpaw_to_hermes_targetname_lands_in_profiles(self):
        """root-per-agent target: bot-a identity lands in profiles/bot-a/."""
        out = self.base / "hermes_home"
        rc = cmd_convert(
            source_fw="qwenpaw", target_fw="hermes",
            from_name="bot-a", target_name="bot-a",
            local_dir=str(self.src), out_dir=str(out),
        )
        self.assertEqual(rc, 0)
        # hermes is root-per-agent: a named agent lands under profiles/bot-a/.
        files = _read_all(out / "profiles" / "bot-a")
        self.assertIn("SOUL.md", files)
        self.assertIn("Bot A creative AI.", files["SOUL.md"])

    def test_qwenpaw_to_qoder_targetname_lands_in_agents_file(self):
        """file-per-agent target: --target-name lands in agents/{name}.md.

        The converted persona (SOUL/PROFILE) is routed to the per-agent file
        agents/bot-a.md, while the shared AGENTS.md must NOT be polluted with
        that identity content.
        """
        out = self.base / "qoder_home"
        rc = cmd_convert(
            source_fw="qwenpaw", target_fw="qoder",
            from_name="bot-a", target_name="bot-a",
            local_dir=str(self.src), out_dir=str(out),
        )
        self.assertEqual(rc, 0)
        files = _read_all(out)
        # Persona now lands in the dedicated per-agent file.
        self.assertIn("agents/bot-a.md", files,
                      "file-per-agent target must route persona to agents/{name}.md")
        self.assertIn("Bot A creative AI.", files["agents/bot-a.md"])
        self.assertIn("Bot A profile.", files["agents/bot-a.md"])
        # Shared AGENTS.md, if present, must not carry the imported persona.
        if "AGENTS.md" in files:
            self.assertNotIn("Bot A creative AI.", files["AGENTS.md"],
                             "shared AGENTS.md must stay free of per-agent identity")

    def test_qwenpaw_to_qoder_default_name_lands_in_agents_default(self):
        """file-per-agent target without --target-name: persona -> agents/default.md."""
        out = self.base / "qoder_default_home"
        # from_name=default -> source lives in the default sub-agent workspace.
        src_default = self.base / "src_default"
        _write(build_spec("qwenpaw", "default", str(src_default)).workspace_root, {
            "SOUL.md": "# Soul\nBot A creative AI.\n",
            "PROFILE.md": "# Profile A\nBot A profile.\n",
        })
        rc = cmd_convert(
            source_fw="qwenpaw", target_fw="qoder",
            from_name="default", target_name=None,
            local_dir=str(src_default), out_dir=str(out),
        )
        self.assertEqual(rc, 0)
        files = _read_all(out)
        self.assertIn("agents/default.md", files,
                      "default persona must land in agents/default.md")
        self.assertIn("Bot A creative AI.", files["agents/default.md"])


# ===========================================================================
# P0-B: converted content correctness (no template corruption, e.g. the § bug)
# ===========================================================================

class TestConvertContentCorrectness(unittest.TestCase):
    """Converted output must be clean: no stray control/section chars, and the
    persona identity must survive the merge."""

    CORRUPTION_MARKERS = ("\u00a7", "\ufffd")  # § (section sign), replacement char

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.src = self.base / "src"
        _write(build_spec("qwenpaw", "bot-a", str(self.src)).workspace_root, {
            "SOUL.md": "# Soul\nMy custom identity line.\n",
            "PROFILE.md": "# Profile\nMy profile.\n",
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_hermes_default_user_template_is_clean(self):
        """Regression for the § corruption in hermes memories/USER.md template."""
        defaults = get_defaults("hermes")
        self.assertIn("memories/USER.md", defaults)
        user_md = defaults["memories/USER.md"]
        for marker in self.CORRUPTION_MARKERS:
            self.assertNotIn(marker, user_md,
                             f"hermes USER.md template contains corruption {marker!r}")

    def test_all_default_templates_are_clean(self):
        """No framework default template may carry corruption markers."""
        for fw in FRAMEWORK_REGISTRY:
            for rel, content in get_defaults(fw).items():
                for marker in self.CORRUPTION_MARKERS:
                    self.assertNotIn(
                        marker, content,
                        f"{fw}/{rel} default template contains corruption {marker!r}",
                    )

    def test_convert_to_hermes_output_is_clean(self):
        """qwenpaw -> hermes convert output (incl. filled defaults) has no §."""
        out = self.base / "hermes_out"
        rc = cmd_convert(
            source_fw="qwenpaw", target_fw="hermes",
            from_name="bot-a", local_dir=str(self.src), out_dir=str(out),
        )
        self.assertEqual(rc, 0)
        files = _read_all(out / "profiles" / "bot-a")
        # identity survives.
        self.assertIn("SOUL.md", files)
        self.assertIn("My custom identity line.", files["SOUL.md"])
        # every written file is corruption-free.
        for rel, content in files.items():
            for marker in self.CORRUPTION_MARKERS:
                self.assertNotIn(marker, content, f"{rel} contains corruption {marker!r}")


# ===========================================================================
# Download stubs for offline round-trip / boundary tests
# ===========================================================================

class _StoreStub:
    """Serves a fixed remote repo from an in-memory STORE dict.

    Subclasses set STORE and FRAMEWORK.  Content is returned verbatim so tests
    can assert byte-for-byte equality after download.
    """

    STORE: dict = {}
    FRAMEWORK = "qwenpaw"

    def __init__(self, *args, **kwargs):
        pass

    def repo_info(self, path, name):
        return {"Path": path, "Name": name, "Framework": self.FRAMEWORK, "Revision": 1}

    def list_repo_files(self, path, name, revision="master"):
        return list(self.STORE)

    def list_repo_files_detail(self, path, name, revision="master"):
        return [
            RemoteFileInfo(path=p, sha256=sha256_content(c), is_lfs=False)
            for p, c in self.STORE.items()
        ]

    def download_repo_file(self, path, name, file_path, revision="master",
                           *, binary=False):
        content = self.STORE[file_path]
        raw = (content if isinstance(content, bytes) else
               content.encode("utf-8"))
        return raw if binary else raw.decode("utf-8", errors="replace")


class _QwenpawAllStore(_StoreStub):
    FRAMEWORK = "qwenpaw"
    STORE = {
        "default/SOUL.md": "# Soul\nDefault agent soul.\n",
        "default/PROFILE.md": "# Profile\nDefault profile.\n",
        "bot-a/SOUL.md": "# Soul\nBot A creative AI.\n",
        "bot-a/PROFILE.md": "# Profile A\nBot A profile.\n",
        "bot-a/skills/write/SKILL.md": "# Write\nWriting skill.\n",
        "bot-b/SOUL.md": "# Soul\nBot B analysis AI.\n",
    }


class _QwenpawDefaultStore(_StoreStub):
    FRAMEWORK = "qwenpaw"
    STORE = {
        "SOUL.md": "# Soul\nThe one default agent.\n",
        "PROFILE.md": "# Profile\nDefault profile.\n",
    }


# ===========================================================================
# P1-A: all-mode / root-per-agent download round-trip byte-equality
# ===========================================================================

class TestAllModeRoundTripContent(unittest.TestCase):
    """Download qwenpaw --name all (no convert): every agent-prefixed file must
    land byte-for-byte identical, not merely exist."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "ws"

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _QwenpawAllStore)
    def test_qwenpaw_all_download_content_matches(self):
        rc = cmd_download(
            framework="qwenpaw", repo="qw", name=ALL_AGENT_NAME,
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        written = _read_all(self.out / "workspaces")
        # every stored spec file present with identical content.
        for rel, expected in _QwenpawAllStore.STORE.items():
            self.assertIn(rel, written, f"{rel} missing after all-mode download")
            self.assertEqual(written[rel], expected, f"content mismatch for {rel}")
        # agent prefixes preserved (root-per-agent, same framework).
        self.assertIn("bot-a/SOUL.md", written)
        self.assertIn("bot-b/SOUL.md", written)


# ===========================================================================
# P1-B: default-agent upload/download boundary semantics
# ===========================================================================

class TestDefaultAgentBoundary(unittest.TestCase):
    """'default' is a special name: repo_name(fw, 'default') keeps the name,
    while empty/all collapse to the framework alone.  Root-per-agent default
    resolves to the base workspace dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "ws"

    def tearDown(self):
        self.tmp.cleanup()

    def test_repo_name_default_vs_all_vs_empty(self):
        # explicit 'default' is a normal name -> fw-default
        self.assertEqual(repo_name("qwenpaw", DEFAULT_AGENT_NAME), "qwenpaw-default")
        # 'all' and '' both collapse to the framework alone.
        self.assertEqual(repo_name("qwenpaw", ALL_AGENT_NAME), "qwenpaw")
        self.assertEqual(repo_name("qwenpaw", ""), "qwenpaw")

    def test_qwenpaw_default_workspace_root(self):
        # root-per-agent default (no local_dir override) -> workspaces/default.
        spec = build_spec("qwenpaw", DEFAULT_AGENT_NAME)
        self.assertTrue(
            str(spec.workspace_root).endswith(str(Path("workspaces") / "default")),
            f"unexpected default root: {spec.workspace_root}",
        )
        # all-mode lifts to the workspaces/ parent (no agent suffix).
        all_spec = build_spec("qwenpaw", ALL_AGENT_NAME)
        self.assertTrue(str(all_spec.workspace_root).endswith("workspaces"))
        # an explicit local_dir override is used verbatim as the root.
        override = build_spec("qwenpaw", DEFAULT_AGENT_NAME, str(self.out))
        self.assertEqual(str(override.workspace_root),
                         str(self.out / "workspaces" / "default"))

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _QwenpawDefaultStore)
    def test_download_default_agent_writes_bare_paths(self):
        rc = cmd_download(
            framework="qwenpaw", repo="qwenpaw-default", name=DEFAULT_AGENT_NAME,
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        written = _read_all(self.out / "workspaces" / "default")
        self.assertIn("SOUL.md", written)
        self.assertEqual(written["SOUL.md"], _QwenpawDefaultStore.STORE["SOUL.md"])
        # no agent-prefixed dirs for a single default download.
        self.assertFalse(any("bot-" in p for p in written))


# ===========================================================================
# P2: root-per-agent single sub-agent download
# ===========================================================================

class TestSingleSubAgentDownload(unittest.TestCase):
    """Downloading a single root-per-agent sub-agent (bot-a) writes bare paths
    into the target agent's own workspace, with content intact."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "ws"

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("ms_agent.agent_hub._commands.AgentApi", _QwenpawDefaultStore)
    def test_download_single_bot_agent_content(self):
        # A single sub-agent repo stores bare (unprefixed) paths.
        rc = cmd_download(
            framework="qwenpaw", repo="qwenpaw-bot-a", name="bot-a",
            local_dir=str(self.out),
            endpoint="http://s", token="tok", username="u",
        )
        self.assertEqual(rc, 0)
        written = _read_all(self.out / "workspaces" / "bot-a")
        self.assertIn("SOUL.md", written)
        self.assertIn("PROFILE.md", written)
        self.assertEqual(written["SOUL.md"], _QwenpawDefaultStore.STORE["SOUL.md"])


# ===========================================================================
# P3: four-framework cross-convert matrix (openclaw / hermes / qwenpaw / ms-agent)
# ===========================================================================

class TestFourFrameworkConvertMatrix(unittest.TestCase):
    """End-to-end ``cmd_convert`` coverage for the four required frameworks.

    Each source persona carries a unique marker so we can assert the identity
    actually survives the cross-framework merge (persona files are merged into
    the target template via an ``Imported from ...`` section, so we check with
    ``assertIn`` rather than byte-equality).  Plain files (MEMORY.md, USER.md)
    are carried over verbatim.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _convert(self, src_files, source_fw, target_fw):
        src = self.base / f"{source_fw}_src"
        out = self.base / f"{source_fw}_to_{target_fw}"
        _write(build_spec(source_fw, "bot-a", str(src)).workspace_root, src_files)
        rc = cmd_convert(
            source_fw=source_fw, target_fw=target_fw,
            from_name="bot-a", local_dir=str(src), out_dir=str(out),
        )
        self.assertEqual(rc, 0, f"{source_fw}->{target_fw} convert failed")
        return _read_all(build_spec(target_fw, "bot-a", str(out)).workspace_root)

    def test_ms_agent_to_qwenpaw_persona_maps_to_profile(self):
        """ms-agent (single-agent) -> qwenpaw (root-per-agent): PROFILE.md
        identity lands in qwenpaw PROFILE.md (persona semantic group)."""
        files = self._convert(
            {
                "PROFILE.md": "---\nversion: 1\n---\n\n# About Me\n- Call me: MS_PERSONA_MARKER\n",
                "skills/write/SKILL.md": "# Write\nWriting skill.\n",
            },
            "ms-agent", "qwenpaw",
        )
        self.assertIn("PROFILE.md", files)
        self.assertIn("MS_PERSONA_MARKER", files["PROFILE.md"])
        # skill carried over.
        self.assertIn("skills/write/SKILL.md", files)

    def test_qwenpaw_to_ms_agent_profile_maps_to_uppercase(self):
        """qwenpaw -> ms-agent: PROFILE.md identity stays in PROFILE.md (both
        frameworks use the uppercase name)."""
        files = self._convert(
            {
                "SOUL.md": "# Soul\nQP soul.\n",
                "PROFILE.md": "# Profile\nQP_PERSONA_MARKER identity.\n",
            },
            "qwenpaw", "ms-agent",
        )
        self.assertIn("PROFILE.md", files)
        self.assertIn("QP_PERSONA_MARKER", files["PROFILE.md"])
        # ms-agent no longer uses a lowercase profile.md, and stays single-agent.
        self.assertNotIn("profile.md", files)
        self.assertFalse(any("bot-a" in p for p in files))

    def test_openclaw_to_hermes_identity_and_user(self):
        """openclaw (root-per-agent) -> hermes (single-agent): SOUL kept,
        USER.md maps to memories/USER.md."""
        files = self._convert(
            {
                "SOUL.md": "# Soul\nOC_ID_MARKER.\n",
                "USER.md": "# User\nOC_USER_MARKER.\n",
            },
            "openclaw", "hermes",
        )
        self.assertIn("SOUL.md", files)
        self.assertIn("OC_ID_MARKER", files["SOUL.md"])
        # openclaw USER.md -> hermes memories/USER.md
        self.assertIn("memories/USER.md", files)
        self.assertIn("OC_USER_MARKER", files["memories/USER.md"])

    def test_hermes_to_qwenpaw_identity_survives(self):
        """hermes -> qwenpaw: SOUL identity kept, memories/USER.md carried over."""
        files = self._convert(
            {
                "SOUL.md": "# Soul\nHM_ID_MARKER.\n",
                "memories/USER.md": "# User\nHM_USER_MARKER.\n",
            },
            "hermes", "qwenpaw",
        )
        self.assertIn("SOUL.md", files)
        self.assertIn("HM_ID_MARKER", files["SOUL.md"])
        self.assertIn("memory/USER.md", files)
        self.assertIn("HM_USER_MARKER", files["memory/USER.md"])

    def test_openclaw_to_ms_agent_memory_folds_into_agents(self):
        """openclaw -> ms-agent: ms-agent has no memory slot (memory is
        project-level at runtime), so MEMORY.md content is folded into the
        catch-all AGENTS.md rather than written as a dead global file."""
        files = self._convert(
            {
                "SOUL.md": "# Soul\nOC soul.\n",
                "MEMORY.md": "# Memory\nOC_MEM_MARKER.\n",
            },
            "openclaw", "ms-agent",
        )
        # no standalone memory file in the ms-agent global layout.
        self.assertNotIn("MEMORY.md", files)
        # content is preserved by folding into the catch-all instructions file.
        self.assertIn("AGENTS.md", files)
        self.assertIn("OC_MEM_MARKER", files["AGENTS.md"])
        # single-agent target: no agent-prefixed dirs.
        self.assertFalse(any("bot-a" in p for p in files))


class TestQoderPersonaOutbound(unittest.TestCase):
    """Converting OUT of qoder must not lose the per-agent persona file.

    Regression: ``agents/<name>.md`` (the persona body of a file-per-agent
    qoder sub-agent) is absent from the static semantic path map, so the
    resolver carried it over under its original path and the target-spec
    filter then dropped it -- persona lost on every qoder->X conversion
    while X->qoder had a working fold-in. Now the source persona file is
    flagged (identity_source) and folds into the target's persona/catch-all
    file, surfaced as Merged.
    """

    PERSONA = "# persona\n\u540d\u5b57\uff1a\u6d4b\u8bd5\u67b6\u6784\u5e08\nGOLD-QODER-PERSONA\n"
    SHARED = "# AGENTS.md\n## Shared Rules\n- GOLD-QODER-SHARED\n"

    def _convert(self, target_fw: str):
        """Run a real cmd_convert from an on-disk qoder workspace; return
        {rel_path: content} of everything written under out_dir."""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            (src / "agents").mkdir(parents=True)
            (src / "AGENTS.md").write_text(self.SHARED)
            (src / "agents" / "test-architect.md").write_text(self.PERSONA)
            out = Path(td) / "out"
            rc = cmd_convert(
                "qoder", target_fw,
                from_name="test-architect", target_name="default",
                local_dir=str(src), out_dir=str(out))
            self.assertEqual(rc, 0)
            return {
                str(p.relative_to(out)): p.read_text()
                for p in out.rglob("*") if p.is_file()
            }

    def test_persona_survives_to_every_target(self):
        """RISK-001: all 6 outbound targets keep the persona body."""
        expected_home = {
            "hermes": "SOUL.md",
            "openclaw": "workspace/AGENTS.md",
            "qwenpaw": "workspaces/default/AGENTS.md",
            "nanobot": "AGENTS.md",
            "openhuman": "SOUL.md",
            "ms-agent": "AGENTS.md",
        }
        for target, home in expected_home.items():
            files = self._convert(target)
            holders = [p for p, c in files.items() if "GOLD-QODER-PERSONA" in c]
            self.assertEqual(
                holders, [home],
                f"qoder->{target}: persona expected in {home}, got {holders}")
            # shared AGENTS.md rules still migrate too.
            self.assertTrue(
                any("GOLD-QODER-SHARED" in c for c in files.values()),
                f"qoder->{target}: shared rules lost")

    def test_reverse_direction_not_regressed(self):
        """hermes -> qoder still folds SOUL.md into agents/<target-name>.md."""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            src.mkdir()
            (src / "SOUL.md").write_text("# Soul\nGOLD-HERMES-PERSONA\n")
            out = Path(td) / "out"
            rc = cmd_convert(
                "hermes", "qoder",
                from_name="default", target_name="test-architect",
                local_dir=str(src), out_dir=str(out))
            self.assertEqual(rc, 0)
            persona = out / "agents" / "test-architect.md"
            self.assertTrue(persona.is_file())
            self.assertIn("GOLD-HERMES-PERSONA", persona.read_text())


class TestHermesOptionalSkillsOutbound(unittest.TestCase):
    """hermes ``optional-skills/`` must survive cross-framework conversion.

    Regression (RISK-004): only the ``skills/`` prefix took the skill-import
    route in merge_resources; ``optional-skills/`` fell through to the
    generic branch, was carried over under its original path and then
    dropped by the target-spec filter -- the whole optional skill tree
    silently vanished on every hermes->X conversion while ``skills/``
    migrated fine. Now it is normalized to ``skills/<name>/**`` cross-product.
    """

    def _make_src(self, td):
        src = Path(td) / "src"
        (src / "skills" / "daily-report").mkdir(parents=True)
        (src / "optional-skills" / "git-helper").mkdir(parents=True)
        (src / "SOUL.md").write_text("# Soul\npersona\n")
        (src / "skills" / "daily-report" / "SKILL.md").write_text(
            "GOLD-SKILL\n")
        (src / "optional-skills" / "git-helper" / "SKILL.md").write_text(
            "GOLD-HERMES-DEFAULT-OPTSKILL\n")
        return src

    def test_optional_skill_normalized_to_skills_on_every_target(self):
        for target in ("openclaw", "qwenpaw", "nanobot", "openhuman",
                       "qoder", "ms-agent"):
            with tempfile.TemporaryDirectory() as td:
                src = self._make_src(td)
                out = Path(td) / "out"
                rc = cmd_convert(
                    "hermes", target,
                    from_name="default", target_name="default",
                    local_dir=str(src), out_dir=str(out))
                self.assertEqual(rc, 0)
                hits = [
                    str(p.relative_to(out)) for p in out.rglob("*")
                    if p.is_file() and "OPTSKILL" in p.read_text()
                ]
                # normalized under skills/<name>/, wherever the workspace root is.
                self.assertEqual(
                    len(hits), 1,
                    f"hermes->{target}: optional skill lost or duplicated: {hits}")
                self.assertIn("skills/git-helper/SKILL.md", hits[0])
                self.assertNotIn("optional-skills", hits[0])

    def test_same_framework_keeps_original_prefix(self):
        """hermes -> hermes stays byte-faithful: optional-skills/ untouched."""
        with tempfile.TemporaryDirectory() as td:
            src = self._make_src(td)
            out = Path(td) / "out"
            rc = cmd_convert(
                "hermes", "hermes",
                from_name="default", target_name="default",
                local_dir=str(src), out_dir=str(out))
            self.assertEqual(rc, 0)
            kept = out / "optional-skills" / "git-helper" / "SKILL.md"
            self.assertTrue(kept.is_file())
            self.assertIn("OPTSKILL", kept.read_text())


class TestQoderCommandsToSkillOutbound(unittest.TestCase):
    """Qoder ``commands/<x>.md`` must convert to a target skill.

    The host runs qoder commands via the skill framework (a
    ``name``/``description`` frontmatter + body, triggered by ``/<x>``), so
    they are skills in all but path. No other framework has a ``commands/``
    slot, so carrying the path over verbatim let the target-spec filter drop
    it -- imported on paper, never loaded. Cross-product each command is
    re-homed as ``skills/<x>/SKILL.md``; qoder->qoder keeps it verbatim.
    """

    def _make_src(self, td):
        src = Path(td) / "src"
        (src / "agents").mkdir(parents=True)
        (src / "commands").mkdir(parents=True)
        (src / "AGENTS.md").write_text("# Agents\n")
        (src / "agents" / "default.md").write_text("# Default\npersona\n")
        (src / "commands" / "check-user-resources.md").write_text(
            "---\nname: check-user-resources\n"
            "description: check system resources\n---\n\nGOLD-QODER-COMMAND\n")
        return src

    def test_command_becomes_skill_on_every_target(self):
        for target in ("openclaw", "qwenpaw", "nanobot", "openhuman",
                       "hermes", "ms-agent"):
            with tempfile.TemporaryDirectory() as td:
                src = self._make_src(td)
                out = Path(td) / "out"
                rc = cmd_convert(
                    "qoder", target,
                    from_name="default", target_name="default",
                    local_dir=str(src), out_dir=str(out))
                self.assertEqual(rc, 0)
                hits = [
                    str(p.relative_to(out)) for p in out.rglob("*")
                    if p.is_file() and "GOLD-QODER-COMMAND" in p.read_text()
                ]
                self.assertEqual(
                    len(hits), 1,
                    f"qoder->{target}: command lost or duplicated: {hits}")
                self.assertIn(
                    "skills/check-user-resources/SKILL.md", hits[0])
                self.assertNotIn("commands/", hits[0])

    def test_same_framework_keeps_command_prefix(self):
        """qoder -> qoder stays byte-faithful: commands/ untouched."""
        with tempfile.TemporaryDirectory() as td:
            src = self._make_src(td)
            out = Path(td) / "out"
            rc = cmd_convert(
                "qoder", "qoder",
                from_name="default", target_name="default",
                local_dir=str(src), out_dir=str(out))
            self.assertEqual(rc, 0)
            kept = out / "commands" / "check-user-resources.md"
            self.assertTrue(kept.is_file())
            self.assertIn("GOLD-QODER-COMMAND", kept.read_text())
            self.assertFalse(
                (out / "skills" / "check-user-resources").exists())


class TestPrivateConfigDroppedOnConvert(unittest.TestCase):
    """Framework-private config files must not survive a cross convert.

    ``config.yaml`` exists in both hermes and ms-agent but with incompatible
    formats, and ``skill.json`` in both ms-agent and qwenpaw. They have no
    cross-framework meaning, so carrying them over left an unparseable file in
    the target workspace. They are dropped cross-product; same-framework sync
    still keeps them verbatim.
    """

    def test_hermes_to_ms_agent_drops_config_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            (src / "skills" / "s").mkdir(parents=True)
            (src / "SOUL.md").write_text("# Soul\nGOLD-PERSONA\n")
            (src / "config.yaml").write_text("llm:\n  model: x\nhooks: {}\n")
            (src / "skills" / "s" / "SKILL.md").write_text("GOLD-SKILL\n")
            out = Path(td) / "out"
            rc = cmd_convert(
                "hermes", "ms-agent",
                from_name="default", target_name="default",
                local_dir=str(src), out_dir=str(out))
            self.assertEqual(rc, 0)
            names = {p.name for p in out.rglob("*") if p.is_file()}
            self.assertNotIn("config.yaml", names)
            # persona + user skill still migrate
            all_text = "".join(
                p.read_text() for p in out.rglob("*") if p.is_file())
            self.assertIn("GOLD-PERSONA", all_text)
            self.assertIn("GOLD-SKILL", all_text)

    def test_ms_agent_to_hermes_drops_config_and_skills_json(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            src.mkdir()
            (src / "SOUL.md").write_text("# Who You Are\nGOLD-PERSONA\n")
            (src / "config.yaml").write_text("llm:\n  model: x\ntools: {}\n")
            (src / "skills.json").write_text('{"sources": [], "disabled": ["x"]}')
            out = Path(td) / "out"
            rc = cmd_convert(
                "ms-agent", "hermes",
                from_name="default", target_name="default",
                local_dir=str(src), out_dir=str(out))
            self.assertEqual(rc, 0)
            names = {p.name for p in out.rglob("*") if p.is_file()}
            self.assertNotIn("config.yaml", names)
            self.assertNotIn("skills.json", names)
            all_text = "".join(
                p.read_text() for p in out.rglob("*") if p.is_file())
            self.assertIn("GOLD-PERSONA", all_text)

    def test_openhuman_to_ms_agent_keeps_full_skill_tree(self):
        """openhuman -> ms-agent: a skill is an atomic directory, so the whole
        tree travels -- SKILL.md plus every sibling file, including per-skill
        sidecars like ``_meta.json`` / ``metadata.json``. ms-agent only reads
        SKILL.md, so extra files are harmless; the merger never guesses which
        filenames are ``private`` and risks dropping a real dependency.
        Regression for a report where skills vanished entirely.
        """
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            (src / "skills" / "weather").mkdir(parents=True)
            (src / "skills" / "news-daily").mkdir(parents=True)
            (src / "SOUL.md").write_text("# Soul\nGOLD-PERSONA\n")
            (src / "skills" / "weather" / "SKILL.md").write_text("GOLD-WEATHER\n")
            (src / "skills" / "weather" / "_meta.json").write_text('{"k": 1}')
            (src / "skills" / "news-daily" / "SKILL.md").write_text("GOLD-NEWS\n")
            (src / "skills" / "news-daily" / "metadata.json").write_text('{"k": 2}')
            out = Path(td) / "out"
            rc = cmd_convert(
                "openhuman", "ms-agent",
                from_name="default", target_name="default",
                local_dir=str(src), out_dir=str(out))
            self.assertEqual(rc, 0)
            rels = {
                str(p.relative_to(out))
                for p in out.rglob("*") if p.is_file()
            }
            # the whole skill tree travels verbatim, sidecars included.
            for expected in (
                    "skills/weather/SKILL.md",
                    "skills/weather/_meta.json",
                    "skills/news-daily/SKILL.md",
                    "skills/news-daily/metadata.json"):
                self.assertIn(expected, rels)
            self.assertEqual(
                (out / "skills" / "weather" / "SKILL.md").read_text(),
                "GOLD-WEATHER\n")

    def test_qwenpaw_to_ms_agent_drops_agent_and_skill_json(self):
        """qwenpaw -> ms-agent: qwenpaw's private ``agent.json`` (config) and
        ``skill.json`` (skill manifest) are dropped -- ms-agent uses neither
        format, so carrying them over would leave unloadable files in the
        target. The persona and real skills still migrate.
        """
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            # qwenpaw is root-per-agent: default agent lives in workspaces/default.
            ws = src / "workspaces" / "default"
            (ws / "skills" / "foo").mkdir(parents=True)
            (ws / "SOUL.md").write_text("# Soul\nGOLD-PERSONA\n")
            (ws / "agent.json").write_text('{"id": "bot"}')
            (ws / "skill.json").write_text('{"skills": [{"name": "a"}]}')
            (ws / "skills" / "foo" / "SKILL.md").write_text("GOLD-SKILL\n")
            out = Path(td) / "out"
            rc = cmd_convert(
                "qwenpaw", "ms-agent",
                from_name="default", target_name="default",
                local_dir=str(src), out_dir=str(out))
            self.assertEqual(rc, 0)
            names = {p.name for p in out.rglob("*") if p.is_file()}
            self.assertNotIn("agent.json", names)
            self.assertNotIn("skill.json", names)
            # persona + user skill still migrate.
            rels = {
                str(p.relative_to(out))
                for p in out.rglob("*") if p.is_file()
            }
            self.assertIn("skills/foo/SKILL.md", rels)
            all_text = "".join(
                p.read_text() for p in out.rglob("*") if p.is_file())
            self.assertIn("GOLD-PERSONA", all_text)

    def test_qwenpaw_to_ms_agent_keeps_full_skill_tree(self):
        """qwenpaw -> ms-agent: a skill is a whole directory, so its auxiliary
        files (references/, scripts/, ...) must migrate alongside SKILL.md --
        not just the SKILL.md itself. Regression: ms-agent's allowlist used
        ``skills/*/SKILL.md`` and dropped every deeper runtime dependency.
        """
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            sk = src / "workspaces" / "default" / "skills" / "Daily-AI-News"
            (sk / "references").mkdir(parents=True)
            (sk / "scripts").mkdir(parents=True)
            (src / "workspaces" / "default" / "SOUL.md").write_text("# Soul\nQP\n")
            (sk / "SKILL.md").write_text("# Daily AI News\n")
            (sk / "references" / "news_sources.md").write_text("sources\n")
            (sk / "scripts" / "generate_queries.py").write_text("print(1)\n")
            (sk / "scripts" / "requirements.txt").write_text("requests\n")
            out = Path(td) / "out"
            rc = cmd_convert(
                "qwenpaw", "ms-agent",
                from_name="default", target_name="default",
                local_dir=str(src), out_dir=str(out))
            self.assertEqual(rc, 0)
            rels = {
                str(p.relative_to(out))
                for p in out.rglob("*") if p.is_file()
            }
            for expected in (
                    "skills/Daily-AI-News/SKILL.md",
                    "skills/Daily-AI-News/references/news_sources.md",
                    "skills/Daily-AI-News/scripts/generate_queries.py",
                    "skills/Daily-AI-News/scripts/requirements.txt"):
                self.assertIn(expected, rels)

    def test_same_framework_keeps_config_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            src.mkdir()
            (src / "profile.md").write_text("# Profile\n")
            (src / "config.yaml").write_text("llm:\n  model: GOLD-CFG\n")
            out = Path(td) / "out"
            rc = cmd_convert(
                "ms-agent", "ms-agent",
                from_name="default", target_name="default",
                local_dir=str(src), out_dir=str(out))
            self.assertEqual(rc, 0)
            kept = out / "config.yaml"
            self.assertTrue(kept.is_file())
            self.assertIn("GOLD-CFG", kept.read_text())


class TestOpenhumanCuratedMemory(unittest.TestCase):
    """``MEMORY.md`` is OpenHuman's curated long-term memory (injected every
    session, maintained by the archivist sub-agent) and must map onto the other
    products' MEMORY slot. Because a named agent's ``workspace_root`` already
    resolves to ``personalities/<Profile>/``, the same pattern covers both the
    workspace-level file and each Profile's own copy.
    """

    def _make_src(self, td: Path) -> Path:
        src = td / "src"
        (src / "personalities" / "researcher-2" / "skills" / "paper-hunt").mkdir(
            parents=True)
        (src / "SOUL.md").write_text("# Soul\nGLOBAL-PERSONA\n")
        (src / "MEMORY.md").write_text("GLOBAL-MEMORY\n")
        prof = src / "personalities" / "researcher-2"
        (prof / "SOUL.md").write_text("# Soul\nPROFILE-PERSONA\n")
        (prof / "MEMORY.md").write_text("PROFILE-MEMORY\n")
        (prof / "skills" / "paper-hunt" / "SKILL.md").write_text("PROFILE-SKILL\n")
        return src

    def test_workspace_memory_travels_to_openclaw(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            src = self._make_src(td)
            out = td / "out"
            rc = cmd_convert(
                "openhuman", "openclaw",
                from_name="default", target_name="default",
                local_dir=str(src), out_dir=str(out))
            self.assertEqual(rc, 0)
            mem = out / "workspace" / "MEMORY.md"
            self.assertTrue(mem.is_file())
            self.assertIn("GLOBAL-MEMORY", mem.read_text())

    def test_profile_memory_and_skills_travel_to_hermes(self):
        """A Profile carries its *own* memory and skill tree, not the global
        ones -- the per-Profile scope is what ``workspace_root`` selects.
        """
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            src = self._make_src(td)
            out = td / "out"
            rc = cmd_convert(
                "openhuman", "hermes",
                from_name="researcher-2", target_name="default",
                local_dir=str(src), out_dir=str(out))
            self.assertEqual(rc, 0)
            mem = out / "memories" / "MEMORY.md"
            self.assertTrue(mem.is_file())
            self.assertIn("PROFILE-MEMORY", mem.read_text())
            self.assertNotIn("GLOBAL-MEMORY", mem.read_text())
            skill = out / "skills" / "paper-hunt" / "SKILL.md"
            self.assertTrue(skill.is_file())
            self.assertEqual(skill.read_text(), "PROFILE-SKILL\n")

    def test_memory_maps_back_from_hermes(self):
        """Inbound direction: hermes ``memories/MEMORY.md`` lands on the
        OpenHuman workspace root, not in a nested memory dir.
        """
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            src = td / "hermes"
            (src / "memories").mkdir(parents=True)
            (src / "SOUL.md").write_text("# Soul\nH-PERSONA\n")
            (src / "memories" / "MEMORY.md").write_text("H-MEMORY\n")
            out = td / "out"
            rc = cmd_convert(
                "hermes", "openhuman",
                from_name="default", target_name="default",
                local_dir=str(src), out_dir=str(out))
            self.assertEqual(rc, 0)
            mem = out / "MEMORY.md"
            self.assertTrue(mem.is_file())
            self.assertIn("H-MEMORY", mem.read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
