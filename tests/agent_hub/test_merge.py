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
    merged_away_pairs,
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

    def test_parse_ignores_headings_inside_html_comment(self):
        # ms-agent's PROFILE/AGENTS templates carry example ``## `` headings
        # INSIDE an <!-- guidance --> block. Those are not real sections; the
        # whole comment must stay in one preamble section so the template
        # header is never mangled when user content is folded in.
        content = (
            "---\nversion: 1\n---\n\n"
            "<!--\n# About Me\n## Preferences\n## Context\n-->\n"
            "## Real Section\nreal body")
        sections = self.merger.parse_sections(content)
        titles = [s.title for s in sections]
        self.assertIn("## Real Section", titles)
        self.assertNotIn("## Preferences", titles)
        self.assertNotIn("## Context", titles)
        # round-trip keeps the commented headings verbatim inside the preamble.
        restored = self.merger.sections_to_content(sections)
        self.assertIn("<!--", restored)
        self.assertIn("## Preferences", restored)


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

    def test_merge_keeps_all_duplicate_titled_sections(self):
        """Regression (BUG-025): two user sections sharing one heading must
        BOTH survive the merge, in their original order (the old
        ``{title: sec}`` map silently kept only the last one)."""
        result = self.merger.merge(
            "## Rules\n\nMARK-A\n\n## Rules\n\nMARK-B\n",
            "## Rules\n\ndefault rules\n",
            "## Rules\n\ntarget rules\n",
        )
        self.assertIn("MARK-A", result.content)
        self.assertIn("MARK-B", result.content)
        self.assertLess(
            result.content.find("MARK-A"), result.content.find("MARK-B"))
        # The target default body they replaced is gone, not duplicated.
        self.assertNotIn("target rules", result.content)

    def test_user_diff_keeps_template_line_reused_in_user_paragraph(self):
        """Regression (BUG-026): a line the user REUSES inside their own new
        paragraph must survive extraction -- the old global line-set filter
        deleted it out of the middle of the paragraph. A pristine template
        still extracts to empty."""
        from ms_agent.agent_hub._merge import _extract_user_diff_text
        template = "# T\n\n- keep this line\n- another line\n"
        user = template + "\n## My List\n\nHEAD\n- keep this line\nTAIL\n"
        out = _extract_user_diff_text(user, template)
        self.assertIn("HEAD", out)
        self.assertIn("- keep this line", out)
        self.assertIn("TAIL", out)
        self.assertNotIn("- another line", out)
        self.assertEqual(_extract_user_diff_text(template, template), "")

    def test_heartbeat_new_tasks_appear_exactly_once(self):
        """Regression (BUG-028): the base section merge already keeps the
        user's Active Tasks section; the task-level pass must only fill in
        MISSING tasks, not append every new task a second time."""
        from ms_agent.agent_hub._defaults import get_defaults
        from ms_agent.agent_hub._merge import merge_resources
        src = get_defaults("qwenpaw")["HEARTBEAT.md"]
        user = src.replace(
            "## Active Tasks",
            "## Active Tasks\n\n- [ ] MARK-TASK-NEW\n- [x] MARK-TASK-DONE")
        r = merge_resources({"HEARTBEAT.md": user}, "qwenpaw", "nanobot",
                            source_defaults=get_defaults("qwenpaw"),
                            target_defaults=get_defaults("nanobot"))
        txt = r.merged_files.get("HEARTBEAT.md", "")
        self.assertEqual(txt.count("MARK-TASK-NEW"), 1)
        # checkbox states preserved verbatim.
        self.assertIn("- [ ] MARK-TASK-NEW", txt)
        self.assertIn("- [x] MARK-TASK-DONE", txt)

    def test_heartbeat_multiline_comment_lines_are_not_tasks(self):
        """Regression (BUG-029): lines INSIDE a multi-line <!-- ... -->
        comment must not be extracted as tasks (only the opener/closer used
        to be excluded)."""
        from ms_agent.agent_hub._merge import HeartbeatMerger
        m = HeartbeatMerger()
        tasks = m._extract_task_lines(
            "<!--\ncomment A\ncomment B\n-->\n"
            "- [ ] REAL\n<!-- single -->\nplain")
        self.assertEqual(tasks, ["- [ ] REAL", "plain"])

    def test_heartbeat_target_without_active_tasks_keeps_user_tasks(self):
        """Regression (BUG-030): when the target template lacks an
        '## Active Tasks' section, the user's tasks must land in a newly
        created section instead of being silently dropped."""
        from ms_agent.agent_hub._merge import HeartbeatMerger
        r = HeartbeatMerger().merge(
            "## Active Tasks\n\n- [ ] MARK-ORPHAN-TASK\n",
            "## Active Tasks\n\n<!-- add -->\n",
            "# Heartbeat\n\nno active tasks section here\n")
        self.assertIn("- [ ] MARK-ORPHAN-TASK", r.content)
        self.assertIn("## Active Tasks", r.content)
        self.assertIn("no active tasks section here", r.content)

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
        # qoder user-level auto memory joins the same MEMORY.md group.
        self.assertEqual(
            _resolve_target_path("qoder", "memory/MEMORY.md", "hermes"),
            "memories/MEMORY.md")
        self.assertEqual(
            _resolve_target_path("qoder", "memory/MEMORY.md", "openclaw"),
            "MEMORY.md")
        self.assertEqual(
            _resolve_target_path("hermes", "memories/MEMORY.md", "qoder"),
            "memory/MEMORY.md")
        # ms-agent has no memory slot, so qoder memory has no semantic target
        # there either (folds into the catch-all instead).
        self.assertIsNone(
            _resolve_target_path("qoder", "memory/MEMORY.md", "ms-agent"))

    def test_cross_product_ms_agent_profile(self):
        # qwenpaw has no USER.md slot (its profile lives in the composite
        # PROFILE.md), so the USER group does not declare it: ms-agent
        # PROFILE.md -> qwenpaw resolves to None and folds into the catch-all
        # with a visible "merged" hint instead of writing a dead file.
        # qwenpaw PROFILE.md -> ms-agent has no counterpart (narrow group),
        # so it resolves to None too (overflow into catch-all).
        self.assertIsNone(_resolve_target_path("ms-agent", "PROFILE.md", "qwenpaw"))
        self.assertIsNone(_resolve_target_path("qwenpaw", "PROFILE.md", "ms-agent"))

    def test_cross_product_qoder_user_md_is_loose_memory(self):
        # qoder has no memory/USER.md convention (its memory topic files are
        # free-form), so it is NOT in the USER group: the file falls back to
        # its source path and is handled as loose memory (re-homed / inlined
        # per target), never written as a dead profile file.
        self.assertEqual(
            _resolve_target_path("qoder", "memory/USER.md", "hermes"),
            "memory/USER.md")
        self.assertEqual(
            _resolve_target_path("qoder", "memory/USER.md", "nanobot"),
            "memory/USER.md")
        # Frameworks WITH a real USER slot keep their group mappings.
        self.assertEqual(
            _resolve_target_path("openclaw", "USER.md", "hermes"),
            "memories/USER.md")
        self.assertEqual(
            _resolve_target_path("nanobot", "USER.md", "ms-agent"),
            "PROFILE.md")

    def test_cross_product_ms_agent_no_memory_slot(self):
        # ms-agent has NO memory slot (memory is project-level at runtime, not
        # part of the global home layout). An inbound MEMORY.md therefore has no
        # semantic target and returns None, letting the merger fold it into the
        # catch-all instructions file instead of writing a dead MEMORY.md.
        self.assertIsNone(_resolve_target_path("openclaw", "MEMORY.md", "ms-agent"))
        self.assertIsNone(_resolve_target_path("nanobot", "memory/MEMORY.md", "ms-agent"))

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

    def test_qoder_memory_maps_and_topic_files_pass_through(self):
        """The memory index maps onto the target's MEMORY.md slot while loose
        topic files land under openclaw's import convention
        ``memory/imports/<source>/``; index links are rewritten to keep
        resolving, and both travel verbatim (memory is user data, never
        rebased onto a target template)."""
        result = merge_resources(
            incoming={
                "memory/MEMORY.md": "# Memory Index\n\n- [t](t.md) — x\n",
                "memory/t.md": "---\nname: t\n---\n\ntopic body\n",
            },
            source_product="qoder",
            target_product="openclaw",
            source_defaults={},
            target_defaults={},
        )
        self.assertEqual(result.merged_files["MEMORY.md"],
                         "# Memory Index\n\n- [t](memory/imports/qoder/t.md) — x\n")
        self.assertEqual(result.merged_files["memory/imports/qoder/t.md"],
                         "---\nname: t\n---\n\ntopic body\n")

    def test_loose_memory_inlined_for_hermes_as_entry_store(self):
        """hermes reads two fixed ``§``-delimited entry stores and never
        scans its memory directory: loose detail inlines into
        ``memories/MEMORY.md`` and the file is converted to entries -- more
        than one, round-trip stable, within the char budget."""
        result = merge_resources(
            incoming={
                "memory/MEMORY.md": "# Memory Index\n\n- [t](t.md) — x\n",
                "memory/t.md": "topic body MARKER\n",
            },
            source_product="qoder",
            target_product="hermes",
            source_defaults={},
            target_defaults={},
        )
        store = result.merged_files["memories/MEMORY.md"]
        self.assertNotIn("memories/t.md", result.merged_files)
        self.assertNotIn("memory/t.md", result.merged_files)
        entries = [e.strip() for e in store.split("\n§\n") if e.strip()]
        # The index bullet AND the inlined topic both became entries.
        self.assertGreater(len(entries), 1)
        self.assertTrue(any("MARKER" in e for e in entries))
        # The dangling link was de-linked (its file no longer exists).
        self.assertNotIn("](t.md)", store)
        # Drift-guard round trip: parsing the written file reproduces it.
        self.assertEqual(store.strip(), "\n§\n".join(entries))
        self.assertLessEqual(max(map(len, entries)), 2200)

    def test_hermes_inlined_frontmatter_not_leaked_as_entry(self):
        """A topic file's YAML frontmatter sits mid-document once inlined,
        where the extractor's head-strip cannot reach it: it must be removed
        per file so metadata never becomes a junk entry."""
        result = merge_resources(
            incoming={
                "memory/MEMORY.md": "# idx\n",
                "memory/t.md": "---\nname: t\nmetadata:\n  type: user\n---\n\nreal content HERE\n",
            },
            source_product="qoder",
            target_product="hermes",
            source_defaults={},
            target_defaults={},
        )
        store = result.merged_files["memories/MEMORY.md"]
        entries = [e.strip() for e in store.split("\n§\n") if e.strip()]
        self.assertTrue(any("real content HERE" in e for e in entries))
        self.assertFalse(
            any("name: t" in e or e.strip().startswith("---")
                for e in entries), str(entries))

    def test_loose_memory_inlined_for_openhuman_memory_md(self):
        """openhuman's memory is the root ``MEMORY.md`` alone (its wiki vault
        is derived output), so loose detail -- including an unmapped USER
        profile -- inlines into it instead of being written beside it."""
        result = merge_resources(
            incoming={
                "memory/MEMORY.md": "# Memory Index\n",
                "memory/t.md": "topic body\n",
                "memory/USER.md": "profile body\n",
            },
            source_product="qoder",
            target_product="openhuman",
            source_defaults={},
            target_defaults={},
        )
        merged = result.merged_files["MEMORY.md"]
        self.assertIn("# Memory Index", merged)
        self.assertIn("topic body", merged)
        self.assertIn("profile body", merged)
        self.assertFalse(any(k.startswith("wiki/")
                             for k in result.merged_files))

    def test_loose_memory_inlined_for_nanobot(self):
        """nanobot reads ONLY ``memory/MEMORY.md``: loose detail inlines as
        sourced sections (index as base, links to inlined files de-linked,
        merges recorded for the CLI hint table); with no source index the
        inlined sections alone form the file."""
        result = merge_resources(
            incoming={
                "memory/MEMORY.md": "# idx\n\n- [pref](pref.md) — zh\n",
                "memory/pref.md": "prefers Chinese\n",
            },
            source_product="qoder",
            target_product="nanobot",
            source_defaults={},
            target_defaults={},
        )
        merged = result.merged_files["memory/MEMORY.md"]
        self.assertTrue(merged.startswith("# idx"))
        self.assertIn("## Imported from qoder memory/pref.md", merged)
        self.assertIn("prefers Chinese", merged)
        self.assertNotIn("](pref.md)", merged)
        self.assertNotIn("memory/pref.md", result.merged_files)
        self.assertIn(("memory/pref.md", "memory/MEMORY.md"),
                      merged_away_pairs(result))

        orphan = merge_resources(
            incoming={"memory/t.md": "topic body\n"},
            source_product="qoder",
            target_product="nanobot",
            source_defaults={},
            target_defaults={},
        )
        self.assertIn("## Imported from qoder memory/t.md",
                      orphan.merged_files["memory/MEMORY.md"])

    def test_loose_non_md_memory_not_rehomed(self):
        """Non-Markdown payloads (openclaw ``memory/*.json``, nanobot
        ``history.jsonl``) keep their original path -- the target-spec
        filter decides their fate exactly as before."""
        result = merge_resources(
            incoming={"memory/notes.json": "{}"},
            source_product="qoder",
            target_product="hermes",
            source_defaults={},
            target_defaults={},
        )
        self.assertIn("memory/notes.json", result.merged_files)
        self.assertNotIn("memories/notes.json", result.merged_files)

    def test_loose_memory_keeps_path_for_ms_agent(self):
        """ms-agent has no home-level memory slot: loose detail keeps its
        original path at the merge level and the target-spec filter drops
        it (memory stays out of ms-agent by design)."""
        result = merge_resources(
            incoming={"memory/t.md": "topic body\n"},
            source_product="qoder",
            target_product="ms-agent",
            source_defaults={},
            target_defaults={},
        )
        self.assertEqual(result.merged_files.get("memory/t.md"),
                         "topic body\n")

    def test_hermes_entry_budget_skips_overflow(self):
        """An entry that would bust hermes' 2200-char budget is SKIPPED
        (never truncated) and counted, so the written store stays within the
        budget its memory tools enforce."""
        result = merge_resources(
            incoming={
                "memory/MEMORY.md": "# idx\n",
                "memory/big.md": "x" * 2500 + "\n",
                "memory/small.md": "small note\n",
            },
            source_product="qoder",
            target_product="hermes",
            source_defaults={},
            target_defaults={},
        )
        store = result.merged_files["memories/MEMORY.md"]
        entries = [e.strip() for e in store.split("\n§\n") if e.strip()]
        self.assertLessEqual(max(map(len, entries)), 2200)
        self.assertTrue(any("small note" in e for e in entries))
        self.assertFalse(any("x" * 100 in e for e in entries))
        self.assertTrue(
            any(a.action == "merged" and "skipped over" in a.detail
                for a in result.actions))

    def test_hermes_source_entries_rendered_as_markdown(self):
        """hermes as SOURCE: its ``§`` entry stores are rendered as plain
        Markdown paragraphs for the target (no stray ``§`` noise), and a
        source with no index gets a minimal qoder index built so the moved
        detail files are discoverable (qoder reads ONLY its index)."""
        result = merge_resources(
            incoming={
                "memories/MEMORY.md": "entry one\n§\nentry two\n",
                "memories/note.md": "note body\n",
            },
            source_product="hermes",
            target_product="qoder",
            source_defaults={},
            target_defaults={},
        )
        index = result.merged_files["memory/MEMORY.md"]
        self.assertNotIn("§", index)
        self.assertIn("entry one", index)
        self.assertIn("entry two", index)
        # The loose note moved to memory/note.md and the created index
        # references it (qoder discovers detail ONLY through the index).
        self.assertEqual(result.merged_files["memory/note.md"], "note body\n")
        self.assertIn("](note.md)", index)

        # Index-less source: the loose file re-homes and a minimal index is
        # created referencing it.
        flat = merge_resources(
            incoming={"memories/note.md": "note body\n"},
            source_product="hermes",
            target_product="qoder",
            source_defaults={},
            target_defaults={},
        )
        self.assertEqual(flat.merged_files["memory/note.md"], "note body\n")
        self.assertIn("](note.md)", flat.merged_files["memory/MEMORY.md"])

    def test_memory_index_not_rebased_onto_target_default(self):
        """Memory is user data: a target default template for the memory slot
        (nanobot ships one) must never be merged under the incoming index --
        the placeholder boilerplate would be read back as real memories."""
        result = merge_resources(
            incoming={"MEMORY.md": "# real memory\nREAL-MARKER\n"},
            source_product="openclaw",
            target_product="nanobot",
            source_defaults={},
            target_defaults={
                "memory/MEMORY.md":
                "# Long-term Memory\n\n(Important facts about the user)\n"
            },
        )
        self.assertEqual(result.merged_files["memory/MEMORY.md"],
                         "# real memory\nREAL-MARKER\n")

    def test_user_content_folds_into_qwenpaw_catch_all(self):
        """USER content for a target with no USER slot (qwenpaw) folds into
        the catch-all AGENTS.md with a merged hint -- never a dead
        memory/USER.md file (qwenpaw injects AGENTS/SOUL/PROFILE only)."""
        result = merge_resources(
            incoming={"USER.md": "# User\nCall me CAPTAIN-USER.\n"},
            source_product="openclaw",
            target_product="qwenpaw",
            source_defaults={},
            target_defaults={},
        )
        self.assertNotIn("memory/USER.md", result.merged_files)
        self.assertIn("CAPTAIN-USER", result.merged_files.get("AGENTS.md", ""))
        self.assertIn(("USER.md", "AGENTS.md"), merged_away_pairs(result))

    def test_openhuman_memory_goals_folds_cross_framework(self):
        """MEMORY_GOALS.md has no counterpart elsewhere: same-framework it
        travels verbatim, cross-framework it folds into the catch-all with a
        merged hint instead of being silently dropped."""
        same = merge_resources(
            incoming={"MEMORY_GOALS.md": "[g1] goal\n"},
            source_product="openhuman",
            target_product="openhuman",
            source_defaults={},
            target_defaults={},
        )
        self.assertEqual(same.merged_files["MEMORY_GOALS.md"], "[g1] goal\n")
        cross = merge_resources(
            incoming={"MEMORY_GOALS.md": "[g1] GOAL-MARKER\n"},
            source_product="openhuman",
            target_product="openclaw",
            source_defaults={},
            target_defaults={},
        )
        self.assertNotIn("MEMORY_GOALS.md", cross.merged_files)
        self.assertIn("GOAL-MARKER", cross.merged_files.get("AGENTS.md", ""))

    def test_openhuman_injection_cap_skips_and_reports(self):
        """openhuman injects MEMORY.md under a hard 2000-char cap: inlined
        detail beyond the cap is skipped and reported, not written where it
        would never be read."""
        result = merge_resources(
            incoming={
                "memory/MEMORY.md": "# idx\n",
                "memory/huge.md": "y" * 2500 + "\n",
            },
            source_product="qoder",
            target_product="openhuman",
            source_defaults={},
            target_defaults={},
        )
        merged = result.merged_files["MEMORY.md"]
        self.assertLessEqual(len(merged), 2000)
        self.assertNotIn("yyyy", merged)
        self.assertTrue(
            any(a.action == "skip" and "injection cap" in a.detail
                for a in result.actions))

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
