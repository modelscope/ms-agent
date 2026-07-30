# Copyright (c) Alibaba, Inc. and its affiliates.
"""Section-level Markdown merge engine tests."""
import unittest

from ms_agent.agent_hub._merge import (
    FullMergeResult,
    HeartbeatMerger,
    MergeAction,
    MergeResult,
    SectionMerger,
    _extract_user_diff_text,
    _resolve_target_path,
    merge_resources,
)


class TestSectionMergerParse(unittest.TestCase):
    def setUp(self):
        self.merger = SectionMerger()

    def test_parse_no_headings(self):
        sections = self.merger.parse_sections("just some text\nmore text")
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].title, "")

    def test_parse_with_headings(self):
        content = "preamble\n## Section A\nbody A\n## Section B\nbody B"
        sections = self.merger.parse_sections(content)
        titles = [s.title for s in sections]
        self.assertIn("## Section A", titles)
        self.assertIn("## Section B", titles)

    def test_sections_to_content_roundtrip(self):
        content = "preamble\n## Section A\nbody A\n## Section B\nbody B"
        sections = self.merger.parse_sections(content)
        restored = self.merger.sections_to_content(sections)
        self.assertIn("## Section A", restored)
        self.assertIn("body A", restored)

    def test_parse_empty_string(self):
        sections = self.merger.parse_sections("")
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].title, "")


class TestSectionMergerDiff(unittest.TestCase):
    def setUp(self):
        self.merger = SectionMerger()

    def test_unchanged_section(self):
        content = "## Section A\nbody A"
        default = "## Section A\nbody A"
        unchanged, modified, added = self.merger.diff_sections(content, default)
        self.assertEqual(len(modified), 0)
        self.assertEqual(len(added), 0)
        titled_unchanged = [s for s in unchanged if s.title]
        self.assertEqual(len(titled_unchanged), 1)

    def test_modified_section(self):
        content = "## Section A\nmodified body"
        default = "## Section A\noriginal body"
        unchanged, modified, added = self.merger.diff_sections(content, default)
        self.assertEqual(len(modified), 1)
        self.assertEqual(modified[0].title, "## Section A")

    def test_added_section(self):
        content = "## Section A\nbody A\n## New Section\nnew body"
        default = "## Section A\nbody A"
        unchanged, modified, added = self.merger.diff_sections(content, default)
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].title, "## New Section")

    def test_modified_preamble(self):
        content = "custom preamble\n## Section A\nbody"
        default = "default preamble\n## Section A\nbody"
        unchanged, modified, added = self.merger.diff_sections(content, default)
        preamble_modified = any(s.title == "" for s in modified)
        self.assertTrue(preamble_modified)


class TestSectionMergerMerge(unittest.TestCase):
    def setUp(self):
        self.merger = SectionMerger()

    def test_merge_same_product_keeps_user_modifications(self):
        user = "## Section A\nuser modified\n## Section B\ndefault B"
        source_default = "## Section A\noriginal A\n## Section B\ndefault B"
        target_default = "## Section A\noriginal A\n## Section B\ndefault B"
        result = self.merger.merge(user, source_default, target_default)
        self.assertIn("user modified", result.content)

    def test_merge_appends_user_added_sections(self):
        user = "## Section A\nbody A\n## Custom Section\ncustom content"
        source_default = "## Section A\nbody A"
        target_default = "## Section A\nbody A"
        result = self.merger.merge(user, source_default, target_default)
        self.assertIn("## Custom Section", result.content)
        self.assertIn("custom content", result.content)

    def test_merge_uses_target_default_for_unchanged(self):
        user = "## Section A\noriginal A"
        source_default = "## Section A\noriginal A"
        target_default = "## Section A\ntarget version A"
        result = self.merger.merge(user, source_default, target_default)
        self.assertIn("target version A", result.content)

    def test_merge_returns_actions(self):
        user = "## Section A\nmodified"
        source_default = "## Section A\noriginal"
        target_default = "## Section A\noriginal"
        result = self.merger.merge(user, source_default, target_default)
        self.assertIsInstance(result, MergeResult)
        self.assertGreater(len(result.actions), 0)


class TestHeartbeatMerger(unittest.TestCase):
    def setUp(self):
        self.merger = HeartbeatMerger()

    def test_merge_adds_new_tasks(self):
        user = "## Active Tasks\n- [ ] New task from user\n- [ ] Default task"
        source_default = "## Active Tasks\n- [ ] Default task"
        target_default = "## Active Tasks\n- [ ] Default task"
        result = self.merger.merge(user, source_default, target_default)
        self.assertIn("New task from user", result.content)

    def test_merge_no_new_tasks(self):
        user = "## Active Tasks\n- [ ] Default task"
        source_default = "## Active Tasks\n- [ ] Default task"
        target_default = "## Active Tasks\n- [ ] Default task"
        result = self.merger.merge(user, source_default, target_default)
        task_actions = [a for a in result.actions if a.action == "task_merged"]
        self.assertEqual(len(task_actions), 0)

    def test_extract_task_lines_skips_comments(self):
        body = "- [ ] Task 1\n<!-- comment -->\n- [ ] Task 2"
        lines = self.merger._extract_task_lines(body)
        self.assertEqual(len(lines), 2)
        self.assertNotIn("<!-- comment -->", lines)


class TestExtractUserDiffText(unittest.TestCase):
    def test_extracts_user_additions(self):
        user = "default line\nuser added line"
        default = "default line"
        diff = _extract_user_diff_text(user, default)
        self.assertIn("user added line", diff)
        self.assertNotIn("default line", diff)

    def test_no_changes_returns_empty(self):
        content = "same content"
        default = "same content"
        diff = _extract_user_diff_text(content, default)
        self.assertEqual(diff, "")

    def test_no_default_returns_all_content(self):
        content = "all user content"
        diff = _extract_user_diff_text(content, "")
        self.assertEqual(diff, "all user content")


class TestResolveTargetPath(unittest.TestCase):
    def test_same_product_returns_same_path(self):
        self.assertEqual(_resolve_target_path("nanobot", "SOUL.md", "nanobot"), "SOUL.md")

    def test_cross_product_soul_md(self):
        self.assertEqual(_resolve_target_path("nanobot", "SOUL.md", "openclaw"), "SOUL.md")
        self.assertEqual(_resolve_target_path("nanobot", "SOUL.md", "hermes"), "SOUL.md")

    def test_cross_product_user_md(self):
        self.assertEqual(_resolve_target_path("nanobot", "USER.md", "hermes"), "memories/USER.md")

    def test_cross_product_memory_md(self):
        self.assertEqual(_resolve_target_path("nanobot", "memory/MEMORY.md", "openclaw"), "MEMORY.md")

    def test_cross_product_ms_agent_profile(self):
        # ms-agent profile.md <-> qwenpaw PROFILE.md (persona semantic group)
        self.assertEqual(_resolve_target_path("ms-agent", "profile.md", "qwenpaw"), "PROFILE.md")
        self.assertEqual(_resolve_target_path("qwenpaw", "PROFILE.md", "ms-agent"), "profile.md")

    def test_cross_product_ms_agent_memory(self):
        self.assertEqual(_resolve_target_path("ms-agent", "MEMORY.md", "openclaw"), "MEMORY.md")
        self.assertEqual(_resolve_target_path("openclaw", "MEMORY.md", "ms-agent"), "MEMORY.md")
        self.assertEqual(_resolve_target_path("ms-agent", "MEMORY.md", "nanobot"), "memory/MEMORY.md")

    def test_cross_product_no_mapping_passthrough(self):
        result = _resolve_target_path("nanobot", "skills/my-skill/SKILL.md", "openclaw")
        self.assertEqual(result, "skills/my-skill/SKILL.md")

    def test_cross_product_none_mapping(self):
        result = _resolve_target_path("nanobot", "memory/history.jsonl", "hermes")
        self.assertIsNone(result)


class TestMergeResources(unittest.TestCase):
    def test_same_product_imports_directly(self):
        incoming = {"SOUL.md": "my soul", "USER.md": "my user"}
        result = merge_resources(
            incoming=incoming,
            source_product="nanobot",
            target_product="nanobot",
            source_defaults={},
            target_defaults={},
        )
        self.assertIn("SOUL.md", result.merged_files)
        self.assertEqual(result.merged_files["SOUL.md"], "my soul")

    def test_fills_missing_from_target_defaults(self):
        """merge_resources fills target defaults for absent source files."""
        result = merge_resources(
            incoming={},
            source_product="nanobot",
            target_product="nanobot",
            source_defaults={},
            target_defaults={"SOUL.md": "default soul"},
        )
        self.assertIn("SOUL.md", result.merged_files)
        self.assertEqual(result.merged_files["SOUL.md"], "default soul")

    def test_fill_missing_defaults_kept_when_target_lacks_them(self):
        """Defaults for files the target doesn't have are kept by convert_resources."""
        from ms_agent.agent_hub._commands import convert_resources
        result = convert_resources(
            resources={"skills/bot/SKILL.md": "# bot"},
            source_fw="qoder",
            target_fw="qwenpaw",
            existing_files=set(),  # target has nothing
        )
        # Skill + target defaults should all be present
        self.assertIn("skills/bot/SKILL.md", result)

    def test_fill_missing_defaults_filtered_when_target_has_them(self):
        """Defaults for files the target already has are filtered by convert_resources."""
        from ms_agent.agent_hub._commands import convert_resources
        result = convert_resources(
            resources={"skills/bot/SKILL.md": "# bot"},
            source_fw="qoder",
            target_fw="qwenpaw",
            existing_files={"SOUL.md"},  # target already has SOUL.md
        )
        # SOUL.md default should be filtered (target already has it)
        self.assertNotIn("SOUL.md", result)
        # But the skill should still be present
        self.assertIn("skills/bot/SKILL.md", result)

    def test_skill_import(self):
        incoming = {"skills/my-skill/SKILL.md": "# Skill content"}
        result = merge_resources(
            incoming=incoming,
            source_product="nanobot",
            target_product="nanobot",
            source_defaults={},
            target_defaults={},
        )
        self.assertIn("skills/my-skill/SKILL.md", result.merged_files)

    def test_skill_skip_if_exists(self):
        incoming = {"skills/existing-skill/SKILL.md": "# Skill"}
        result = merge_resources(
            incoming=incoming,
            source_product="nanobot",
            target_product="nanobot",
            source_defaults={},
            target_defaults={},
            existing_skills=["existing-skill"],
        )
        self.assertNotIn("skills/existing-skill/SKILL.md", result.merged_files)
        skip_actions = [a for a in result.actions if a.action == "skip"]
        self.assertEqual(len(skip_actions), 1)

    def test_cross_product_soul_md_merged(self):
        incoming = {"SOUL.md": "## Identity\nuser identity\n## Rules\ndefault rules"}
        source_defaults = {"SOUL.md": "## Identity\ndefault identity\n## Rules\ndefault rules"}
        target_defaults = {"SOUL.md": "## Identity\ndefault identity\n## Rules\ndefault rules"}
        result = merge_resources(
            incoming=incoming,
            source_product="nanobot",
            target_product="openclaw",
            source_defaults=source_defaults,
            target_defaults=target_defaults,
        )
        self.assertIn("SOUL.md", result.merged_files)
        self.assertIn("user identity", result.merged_files["SOUL.md"])

    def test_returns_full_merge_result(self):
        result = merge_resources(
            incoming={},
            source_product="nanobot",
            target_product="nanobot",
            source_defaults={},
            target_defaults={},
        )
        self.assertIsInstance(result, FullMergeResult)
        self.assertIsInstance(result.merged_files, dict)
        self.assertIsInstance(result.actions, list)


if __name__ == "__main__":
    unittest.main()


class TestDropUnchangedDefaults(unittest.TestCase):
    """drop_unchanged_defaults: the single shared 'user-customized subset' filter
    used by upload, convert AND watch. Files byte-identical to a framework
    default template carry no user content and must be dropped; modified files,
    non-default files (skills) and frameworks without defaults stay untouched."""

    def _spec(self, fw, name="bot-a"):
        from ms_agent.agent_hub._commands import build_spec
        return build_spec(fw, name)

    def test_drops_unchanged_default_text(self):
        from ms_agent.agent_hub._sync import drop_unchanged_defaults
        from ms_agent.agent_hub._defaults import get_defaults
        defaults = get_defaults("hermes")
        resources = {
            "SOUL.md": defaults["SOUL.md"],                      # unchanged -> drop
            "memories/USER.md": "# custom\nreal user note\n",    # modified   -> keep
            "skills/write/SKILL.md": "# Write\n",                # not default -> keep
        }
        out = drop_unchanged_defaults(resources, "hermes", self._spec("hermes"))
        self.assertNotIn("SOUL.md", out)
        self.assertIn("memories/USER.md", out)
        self.assertIn("skills/write/SKILL.md", out)

    def test_drops_unchanged_default_bytes(self):
        from ms_agent.agent_hub._sync import drop_unchanged_defaults
        from ms_agent.agent_hub._defaults import get_defaults
        defaults = get_defaults("hermes")
        resources = {
            "SOUL.md": defaults["SOUL.md"].encode("utf-8"),      # bytes, unchanged -> drop
            "memories/MEMORY.md": b"# real memory\n",            # bytes, modified  -> keep
        }
        out = drop_unchanged_defaults(resources, "hermes", self._spec("hermes"))
        self.assertNotIn("SOUL.md", out)
        self.assertIn("memories/MEMORY.md", out)

    def test_noop_for_framework_without_defaults(self):
        from ms_agent.agent_hub._sync import drop_unchanged_defaults
        resources = {"AGENTS.md": "x", "commands/c.md": "y"}
        out = drop_unchanged_defaults(resources, "qoder", self._spec("qoder", "default"))
        self.assertEqual(out, resources)

    def test_all_mode_strips_agent_prefix_before_compare(self):
        from ms_agent.agent_hub._sync import drop_unchanged_defaults
        from ms_agent.agent_hub._defaults import get_defaults
        from ms_agent.agent_hub._commands import build_spec
        defaults = get_defaults("qwenpaw")
        spec = build_spec("qwenpaw", "all")
        resources = {
            "bot-a/SOUL.md": defaults["SOUL.md"],       # prefixed unchanged default -> drop
            "bot-a/PROFILE.md": "# Profile\nreal\n",    # modified -> keep
        }
        out = drop_unchanged_defaults(resources, "qwenpaw", spec)
        self.assertNotIn("bot-a/SOUL.md", out)
        self.assertIn("bot-a/PROFILE.md", out)
