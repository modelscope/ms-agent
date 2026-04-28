# Copyright (c) ModelScope Contributors. All rights reserved.
"""Tests for the Skill module.

Covers:
  - SkillSource / parse_skill_source
  - SkillCatalog (load, filter, cache, hot-reload)
  - SkillPromptInjector
  - SkillToolSet (skills_list, skill_view, skill_manage)
  - LLMAgent integration (prepare_skills, create_messages)
  - SkillLoader
  - SkillSchema parsing / validation
  - End-to-end pipeline

Fixture skills: examples/skills/claude_skills (docx, pdf)
"""
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from omegaconf import DictConfig, OmegaConf

CLAUDE_SKILLS_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "examples" / "skills" / "claude_skills"
)


def _make_skill_dir(base: Path, skill_id: str, name: str, desc: str,
                    *, always: bool = False, tags=None,
                    requires=None, extra_body: str = "") -> Path:
    """Create a minimal skill directory with SKILL.md."""
    d = base / skill_id
    d.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"name: {name}",
        f'description: "{desc}"',
    ]
    if always:
        lines.append("always: true")
    if tags:
        lines.append(f"tags: {tags}")
    if requires:
        lines.append("requires:")
        if "tools" in requires:
            lines.append(f"  tools: {requires['tools']}")
        if "env" in requires:
            lines.append(f"  env: {requires['env']}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")
    lines.append(f"Instructions for {name}.")
    if extra_body:
        lines.append(extra_body)
    (d / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")
    return d


# ============================================================
# 1. SkillSource / parse_skill_source
# ============================================================

class TestSkillSource(unittest.TestCase):

    def test_local_existing_path(self):
        from ms_agent.skill.sources import parse_skill_source
        src = parse_skill_source(str(CLAUDE_SKILLS_DIR))
        self.assertEqual(src.type.value, "local")
        self.assertEqual(src.path, str(CLAUDE_SKILLS_DIR))

    def test_modelscope_uri(self):
        from ms_agent.skill.sources import parse_skill_source
        src = parse_skill_source("modelscope://owner/repo@v1.0#subdir")
        self.assertEqual(src.type.value, "modelscope")
        self.assertEqual(src.repo_id, "owner/repo")
        self.assertEqual(src.revision, "v1.0")
        self.assertEqual(src.subdir, "subdir")

    def test_git_url(self):
        from ms_agent.skill.sources import parse_skill_source
        src = parse_skill_source("https://github.com/user/repo.git")
        self.assertEqual(src.type.value, "git")
        self.assertEqual(src.url, "https://github.com/user/repo.git")

    def test_owner_repo_pattern(self):
        from ms_agent.skill.sources import parse_skill_source
        src = parse_skill_source("ms-agent/research_skills")
        self.assertEqual(src.type.value, "modelscope")
        self.assertEqual(src.repo_id, "ms-agent/research_skills")

    def test_nonexistent_path_becomes_local(self):
        from ms_agent.skill.sources import parse_skill_source
        src = parse_skill_source("/nonexistent/path/to/skills")
        self.assertEqual(src.type.value, "local")


# ============================================================
# 2. SkillCatalog
# ============================================================

class TestSkillCatalog(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _make_skill_dir(self.tmp, "alpha", "Alpha", "Skill alpha",
                        tags="[demo]")
        _make_skill_dir(self.tmp, "beta", "Beta", "Skill beta",
                        always=True, tags="[demo, test]")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_catalog(self, path=None):
        from ms_agent.skill.catalog import SkillCatalog
        from ms_agent.skill.sources import SkillSource, SkillSourceType
        catalog = SkillCatalog()
        catalog.load_from_sources([
            SkillSource(type=SkillSourceType.LOCAL_DIR,
                        path=str(path or self.tmp))
        ])
        return catalog

    def test_load_local_skills(self):
        catalog = self._make_catalog()
        skills = catalog.get_enabled_skills()
        self.assertIn("alpha", skills)
        self.assertIn("beta", skills)
        self.assertEqual(skills["alpha"].name, "Alpha")

    def test_load_claude_skills(self):
        catalog = self._make_catalog(CLAUDE_SKILLS_DIR)
        skills = catalog.get_enabled_skills()
        self.assertIn("docx", skills)
        self.assertIn("pdf", skills)
        self.assertEqual(skills["docx"].name, "docx")

    def test_always_skills(self):
        catalog = self._make_catalog()
        always = catalog.get_always_skills()
        self.assertIn("beta", always)
        self.assertNotIn("alpha", always)

    def test_disable_skill(self):
        catalog = self._make_catalog()
        catalog.disable_skill("alpha")
        skills = catalog.get_enabled_skills()
        self.assertNotIn("alpha", skills)
        self.assertIn("beta", skills)

    def test_enable_after_disable(self):
        catalog = self._make_catalog()
        catalog.disable_skill("alpha")
        catalog.enable_skill("alpha")
        self.assertIn("alpha", catalog.get_enabled_skills())

    def test_whitelist_filters(self):
        catalog = self._make_catalog()
        catalog._whitelist = {"alpha"}
        skills = catalog.get_enabled_skills()
        self.assertIn("alpha", skills)
        self.assertNotIn("beta", skills)

    def test_whitelist_empty_disables_all(self):
        catalog = self._make_catalog()
        catalog._whitelist = set()
        self.assertEqual(len(catalog.get_enabled_skills()), 0)

    def test_whitelist_none_allows_all(self):
        catalog = self._make_catalog()
        catalog._whitelist = None
        self.assertEqual(len(catalog.get_enabled_skills()), 2)

    def test_get_skill_by_id(self):
        catalog = self._make_catalog()
        skill = catalog.get_skill("alpha")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.name, "Alpha")

    def test_get_nonexistent_skill(self):
        catalog = self._make_catalog()
        self.assertIsNone(catalog.get_skill("nonexistent"))

    def test_remove_skill(self):
        catalog = self._make_catalog()
        self.assertTrue(catalog.remove_skill("alpha"))
        self.assertIsNone(catalog.get_skill("alpha"))

    def test_remove_nonexistent(self):
        catalog = self._make_catalog()
        self.assertFalse(catalog.remove_skill("nonexistent"))

    def test_add_skill_dynamically(self):
        _make_skill_dir(self.tmp, "gamma", "Gamma", "Skill gamma")
        catalog = self._make_catalog()
        catalog.remove_skill("gamma")
        self.assertIsNone(catalog.get_skill("gamma"))
        skill = catalog.add_skill(str(self.tmp / "gamma"))
        self.assertIsNotNone(skill)
        self.assertEqual(skill.name, "Gamma")

    def test_summary_cache(self):
        catalog = self._make_catalog()
        s1 = catalog.get_skills_summary()
        self.assertIn("Alpha", s1)
        self.assertIn("Beta", s1)
        s2 = catalog.get_skills_summary()
        self.assertIs(s1, s2)

    def test_summary_invalidated_on_change(self):
        catalog = self._make_catalog()
        s1 = catalog.get_skills_summary()
        catalog.disable_skill("alpha")
        s2 = catalog.get_skills_summary()
        self.assertNotEqual(s1, s2)
        self.assertNotIn("Alpha", s2)

    def test_later_source_overrides_earlier(self):
        tmp2 = Path(tempfile.mkdtemp())
        try:
            _make_skill_dir(tmp2, "alpha", "Alpha Override",
                            "Overridden description")
            from ms_agent.skill.catalog import SkillCatalog
            from ms_agent.skill.sources import SkillSource, SkillSourceType
            catalog = SkillCatalog()
            catalog.load_from_sources([
                SkillSource(type=SkillSourceType.LOCAL_DIR,
                            path=str(self.tmp)),
                SkillSource(type=SkillSourceType.LOCAL_DIR,
                            path=str(tmp2)),
            ])
            self.assertEqual(
                catalog.get_skill("alpha").name, "Alpha Override")
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

    def test_reload(self):
        catalog = self._make_catalog()
        (self.tmp / "alpha" / "SKILL.md").write_text(
            '---\nname: Alpha\ndescription: "Updated"\n---\n# Alpha\n',
            encoding="utf-8")
        catalog.reload()
        self.assertEqual(catalog.get_skill("alpha").description, "Updated")

    def test_load_from_config_path_string(self):
        from ms_agent.skill.catalog import SkillCatalog
        cfg = OmegaConf.create({"path": str(self.tmp)})
        catalog = SkillCatalog(config=cfg)
        catalog.load_from_config(cfg)
        self.assertIn("alpha", catalog.get_enabled_skills())

    def test_load_from_config_path_list(self):
        from ms_agent.skill.catalog import SkillCatalog
        cfg = OmegaConf.create({"path": [str(self.tmp)]})
        catalog = SkillCatalog(config=cfg)
        catalog.load_from_config(cfg)
        self.assertIn("alpha", catalog.get_enabled_skills())

    def test_load_from_config_with_disabled(self):
        from ms_agent.skill.catalog import SkillCatalog
        cfg = OmegaConf.create({
            "path": [str(self.tmp)],
            "disabled": ["alpha"],
        })
        catalog = SkillCatalog(config=cfg)
        catalog.load_from_config(cfg)
        self.assertNotIn("alpha", catalog.get_enabled_skills())
        self.assertIn("beta", catalog.get_enabled_skills())


# ============================================================
# 3. SkillPromptInjector
# ============================================================

class TestSkillPromptInjector(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _make_skill_dir(self.tmp, "always-skill", "AlwaysSkill",
                        "Always active", always=True)
        _make_skill_dir(self.tmp, "normal-skill", "NormalSkill",
                        "Normal skill")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_injector(self):
        from ms_agent.skill.catalog import SkillCatalog
        from ms_agent.skill.prompt_injector import SkillPromptInjector
        from ms_agent.skill.sources import SkillSource, SkillSourceType
        catalog = SkillCatalog()
        catalog.load_from_sources([
            SkillSource(type=SkillSourceType.LOCAL_DIR,
                        path=str(self.tmp))
        ])
        return SkillPromptInjector(catalog)

    def test_build_with_always_and_normal(self):
        inj = self._make_injector()
        section = inj.build_skill_prompt_section()
        self.assertIn("Active Skills", section)
        self.assertIn("AlwaysSkill", section)
        self.assertIn("Available Skills", section)
        self.assertIn("NormalSkill", section)

    def test_always_skill_body_injected(self):
        inj = self._make_injector()
        section = inj.build_skill_prompt_section()
        self.assertIn("Instructions for AlwaysSkill", section)

    def test_frontmatter_stripped_from_always(self):
        inj = self._make_injector()
        section = inj.build_skill_prompt_section()
        self.assertNotIn("always: true", section)

    def test_empty_catalog_returns_empty(self):
        from ms_agent.skill.catalog import SkillCatalog
        from ms_agent.skill.prompt_injector import SkillPromptInjector
        catalog = SkillCatalog()
        inj = SkillPromptInjector(catalog)
        self.assertEqual(inj.build_skill_prompt_section(), "")

    def test_strip_frontmatter_static(self):
        from ms_agent.skill.prompt_injector import SkillPromptInjector
        content = "---\nname: Test\n---\n\nBody text."
        result = SkillPromptInjector._strip_frontmatter(content)
        self.assertEqual(result, "Body text.")
        self.assertNotIn("---", result)

    def test_no_always_skills_omits_active_section(self):
        """When no skills are marked always, only the Available section appears."""
        from ms_agent.skill.catalog import SkillCatalog
        from ms_agent.skill.prompt_injector import SkillPromptInjector
        from ms_agent.skill.sources import SkillSource, SkillSourceType
        catalog = SkillCatalog()
        catalog.load_from_sources([
            SkillSource(type=SkillSourceType.LOCAL_DIR,
                        path=str(CLAUDE_SKILLS_DIR))
        ])
        inj = SkillPromptInjector(catalog)
        section = inj.build_skill_prompt_section()
        self.assertNotIn("Active Skills", section)
        self.assertIn("Available Skills", section)
        self.assertIn("docx", section)
        self.assertIn("pdf", section)


# ============================================================
# 4. SkillToolSet
# ============================================================

class TestSkillToolSet(unittest.TestCase):

    def setUp(self):
        from ms_agent.skill.catalog import SkillCatalog
        from ms_agent.skill.skill_tools import SkillToolSet
        from ms_agent.skill.sources import SkillSource, SkillSourceType

        self.tmp = Path(tempfile.mkdtemp())
        _make_skill_dir(self.tmp, "demo", "Demo Skill", "A demo skill",
                        tags="[demo, test]",
                        requires={"tools": "[web_search]",
                                  "env": "[NONEXISTENT_VAR]"})
        scripts_dir = self.tmp / "demo" / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        (scripts_dir / "helper.py").write_text(
            "print('hello')", encoding="utf-8")

        self.catalog = SkillCatalog()
        self.catalog.load_from_sources([
            SkillSource(type=SkillSourceType.LOCAL_DIR,
                        path=str(self.tmp))
        ])

        config = DictConfig({})
        self.toolset = SkillToolSet(config, self.catalog, enable_manage=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_get_tools_includes_all(self):
        tools = asyncio.get_event_loop().run_until_complete(
            self.toolset._get_tools_inner())
        names = [t["tool_name"] for t in tools["skills"]]
        self.assertIn("skills_list", names)
        self.assertIn("skill_view", names)
        self.assertIn("skill_manage", names)

    def test_get_tools_without_manage(self):
        from ms_agent.skill.skill_tools import SkillToolSet
        ts = SkillToolSet(DictConfig({}), self.catalog, enable_manage=False)
        tools = asyncio.get_event_loop().run_until_complete(
            ts._get_tools_inner())
        names = [t["tool_name"] for t in tools["skills"]]
        self.assertNotIn("skill_manage", names)

    def test_skills_list(self):
        result = self.toolset._handle_skills_list({})
        data = json.loads(result)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["skills"][0]["skill_id"], "demo")
        self.assertEqual(data["skills"][0]["name"], "Demo Skill")

    def test_skills_list_with_tag_filter(self):
        result = self.toolset._handle_skills_list({"tag": "demo"})
        data = json.loads(result)
        self.assertEqual(data["total"], 1)

    def test_skills_list_with_nonexistent_tag(self):
        result = self.toolset._handle_skills_list(
            {"tag": "nonexistent"})
        self.assertEqual(result, "No skills available.")

    def test_skill_view_main_content(self):
        result = self.toolset._handle_skill_view({"skill_id": "demo"})
        data = json.loads(result)
        self.assertEqual(data["skill_id"], "demo")
        self.assertIn("Demo Skill", data["content"])
        self.assertIn("scripts", data["linked_files"])

    def test_skill_view_nonexistent(self):
        result = self.toolset._handle_skill_view(
            {"skill_id": "nonexistent"})
        data = json.loads(result)
        self.assertIn("error", data)

    def test_skill_view_file(self):
        result = self.toolset._handle_skill_view({
            "skill_id": "demo",
            "file_path": "scripts/helper.py",
        })
        data = json.loads(result)
        self.assertIn("print('hello')", data["content"])

    def test_skill_view_path_traversal_blocked(self):
        result = self.toolset._handle_skill_view({
            "skill_id": "demo",
            "file_path": "../../etc/passwd",
        })
        data = json.loads(result)
        self.assertIn("error", data)

    def test_skill_view_missing_file(self):
        result = self.toolset._handle_skill_view({
            "skill_id": "demo",
            "file_path": "scripts/nonexistent.py",
        })
        data = json.loads(result)
        self.assertIn("error", data)

    def test_skill_view_requirements_check(self):
        result = self.toolset._handle_skill_view({"skill_id": "demo"})
        data = json.loads(result)
        self.assertIn("requirements_status", data)
        status = data["requirements_status"]
        self.assertIn("NONEXISTENT_VAR", status["missing_env_vars"])

    def test_skill_manage_create_and_delete(self):
        content = (
            '---\nname: New Skill\ndescription: "A new skill"\n---\n'
            '# New Skill\n\nInstructions.')
        with patch.object(self.toolset, '_get_custom_skills_dir',
                          return_value=self.tmp / "_custom"):
            result = self.toolset._handle_skill_manage({
                "action": "create",
                "skill_id": "new-skill",
                "content": content,
            })
            data = json.loads(result)
            self.assertTrue(data.get("success"))

            self.assertIsNotNone(self.catalog.get_skill("new-skill"))

            result = self.toolset._handle_skill_manage({
                "action": "delete",
                "skill_id": "new-skill",
            })
            data = json.loads(result)
            self.assertTrue(data.get("success"))
            self.assertIsNone(self.catalog.get_skill("new-skill"))

    def test_skill_manage_create_duplicate(self):
        content = (
            '---\nname: Demo Dup\ndescription: "dup"\n---\n# Dup\n')
        with patch.object(self.toolset, '_get_custom_skills_dir',
                          return_value=self.tmp):
            result = self.toolset._handle_skill_manage({
                "action": "create",
                "skill_id": "demo",
                "content": content,
            })
            data = json.loads(result)
            self.assertIn("error", data)

    def test_skill_manage_create_invalid_frontmatter(self):
        with patch.object(self.toolset, '_get_custom_skills_dir',
                          return_value=self.tmp / "_custom2"):
            result = self.toolset._handle_skill_manage({
                "action": "create",
                "skill_id": "bad-skill",
                "content": "No frontmatter here.",
            })
            data = json.loads(result)
            self.assertIn("error", data)

    def test_skill_manage_edit(self):
        new_content = (
            '---\nname: Demo Skill\ndescription: "Updated desc"\n---\n'
            '# Demo Skill Updated\n')
        result = self.toolset._handle_skill_manage({
            "action": "edit",
            "skill_id": "demo",
            "content": new_content,
        })
        data = json.loads(result)
        self.assertTrue(data.get("success"))
        self.assertEqual(
            self.catalog.get_skill("demo").description, "Updated desc")

    def test_call_tool_dispatch(self):
        result = asyncio.get_event_loop().run_until_complete(
            self.toolset.call_tool(
                "skills", tool_name="skills_list", tool_args={}))
        self.assertIn("demo", result)

    def test_skill_view_claude_skills(self):
        """Verify skill_view works with real claude_skills fixtures."""
        from ms_agent.skill.catalog import SkillCatalog
        from ms_agent.skill.skill_tools import SkillToolSet
        from ms_agent.skill.sources import SkillSource, SkillSourceType

        catalog = SkillCatalog()
        catalog.load_from_sources([
            SkillSource(type=SkillSourceType.LOCAL_DIR,
                        path=str(CLAUDE_SKILLS_DIR))
        ])
        ts = SkillToolSet(DictConfig({}), catalog, enable_manage=False)

        result = ts._handle_skill_view({"skill_id": "pdf"})
        data = json.loads(result)
        self.assertEqual(data["name"], "pdf")
        self.assertIn("PDF Processing Guide", data["content"])
        self.assertIn("scripts", data["linked_files"])

        result = ts._handle_skill_view({"skill_id": "docx"})
        data = json.loads(result)
        self.assertEqual(data["name"], "docx")
        self.assertIn("DOCX creation", data["content"])


# ============================================================
# 5. SkillLoader
# ============================================================

class TestSkillLoader(unittest.TestCase):

    def test_load_claude_skills(self):
        from ms_agent.skill.loader import SkillLoader
        loader = SkillLoader()
        skills = loader.load_skills(str(CLAUDE_SKILLS_DIR))
        ids = [s.skill_id for s in skills.values()]
        self.assertIn("docx", ids)
        self.assertIn("pdf", ids)

    def test_reload_skill(self):
        from ms_agent.skill.loader import SkillLoader
        loader = SkillLoader()
        loader.load_skills(str(CLAUDE_SKILLS_DIR))
        reloaded = loader.reload_skill(str(CLAUDE_SKILLS_DIR / "pdf"))
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.name, "pdf")

    def test_skill_has_scripts(self):
        from ms_agent.skill.loader import SkillLoader
        loader = SkillLoader()
        skills = loader.load_skills(str(CLAUDE_SKILLS_DIR))
        pdf_skill = skills.get("pdf") or skills.get("pdf@latest")
        self.assertIsNotNone(pdf_skill)
        script_names = [s.name for s in pdf_skill.scripts]
        self.assertTrue(
            len(script_names) > 0,
            "pdf skill should have scripts")

    def test_skill_has_references(self):
        from ms_agent.skill.loader import SkillLoader
        loader = SkillLoader()
        skills = loader.load_skills(str(CLAUDE_SKILLS_DIR))
        pdf_skill = skills.get("pdf") or skills.get("pdf@latest")
        self.assertIsNotNone(pdf_skill)
        ref_names = [r.name for r in pdf_skill.references]
        self.assertIn("reference.md", ref_names)
        self.assertIn("forms.md", ref_names)


# ============================================================
# 6. Integration: LLMAgent.prepare_skills + create_messages
# ============================================================

class TestLLMAgentSkillIntegration(unittest.TestCase):

    def _make_agent(self, skills_path):
        from ms_agent.agent.llm_agent import LLMAgent
        config = OmegaConf.create({
            "llm": {
                "model": "qwen-max",
                "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            },
            "skills": {
                "path": [str(skills_path)],
            },
            "prompt": {
                "system": "You are a test agent.",
            },
        })
        return LLMAgent(config=config, tag="test-agent")

    def test_prepare_skills_loads_catalog(self):
        agent = self._make_agent(CLAUDE_SKILLS_DIR)
        agent.tool_manager = MagicMock()
        asyncio.get_event_loop().run_until_complete(
            agent.prepare_skills())
        self.assertIsNotNone(agent._skill_catalog)
        self.assertIsNotNone(agent._skill_injector)
        agent.tool_manager.register_tool.assert_called_once()

    def test_prepare_skills_noop_without_config(self):
        from ms_agent.agent.llm_agent import LLMAgent
        config = OmegaConf.create({
            "llm": {
                "model": "qwen-max",
                "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            },
            "prompt": {"system": "Test"},
        })
        agent = LLMAgent(config=config, tag="no-skill-agent")
        asyncio.get_event_loop().run_until_complete(
            agent.prepare_skills())
        self.assertIsNone(agent._skill_catalog)
        self.assertIsNone(agent._skill_injector)

    def test_create_messages_injects_skill_section(self):
        agent = self._make_agent(CLAUDE_SKILLS_DIR)
        agent.tool_manager = MagicMock()
        asyncio.get_event_loop().run_until_complete(
            agent.prepare_skills())

        msgs = asyncio.get_event_loop().run_until_complete(
            agent.create_messages("Hello"))

        system_content = msgs[0].content
        self.assertIn("Available Skills", system_content)
        self.assertIn("docx", system_content)
        self.assertIn("pdf", system_content)
        self.assertIn("skill_view", system_content)

    def test_create_messages_no_injection_without_skills(self):
        from ms_agent.agent.llm_agent import LLMAgent
        config = OmegaConf.create({
            "llm": {
                "model": "qwen-max",
                "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            },
            "prompt": {"system": "You are a test agent."},
        })
        agent = LLMAgent(config=config, tag="no-skill")
        msgs = asyncio.get_event_loop().run_until_complete(
            agent.create_messages("Hello"))
        self.assertNotIn("Available Skills", msgs[0].content)

    def test_create_messages_with_always_skill(self):
        """Verify always-skill injection using an inline fixture."""
        from ms_agent.agent.llm_agent import LLMAgent
        tmp = Path(tempfile.mkdtemp())
        try:
            _make_skill_dir(tmp, "greeter", "Greeter",
                            "Auto-greet", always=True)
            _make_skill_dir(tmp, "helper", "Helper", "A helper")
            config = OmegaConf.create({
                "llm": {"model": "qwen-max"},
                "skills": {"path": [str(tmp)]},
                "prompt": {"system": "Test agent."},
            })
            agent = LLMAgent(config=config, tag="always-test")
            agent.tool_manager = MagicMock()
            asyncio.get_event_loop().run_until_complete(
                agent.prepare_skills())
            msgs = asyncio.get_event_loop().run_until_complete(
                agent.create_messages("Hi"))
            content = msgs[0].content
            self.assertIn("Active Skills", content)
            self.assertIn("Greeter", content)
            self.assertIn("Instructions for Greeter", content)
            self.assertIn("Available Skills", content)
            self.assertIn("helper", content)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ============================================================
# 7. Schema parsing and validation
# ============================================================

class TestSchemaPreserved(unittest.TestCase):

    def test_skill_schema_parser_works(self):
        from ms_agent.skill.schema import SkillSchemaParser
        skill = SkillSchemaParser.parse_skill_directory(
            CLAUDE_SKILLS_DIR / "pdf")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.skill_id, "pdf")
        self.assertEqual(skill.name, "pdf")
        self.assertTrue(len(skill.scripts) > 0)

    def test_docx_skill_has_references(self):
        from ms_agent.skill.schema import SkillSchemaParser
        skill = SkillSchemaParser.parse_skill_directory(
            CLAUDE_SKILLS_DIR / "docx")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.skill_id, "docx")
        ref_names = [r.name for r in skill.references]
        self.assertIn("docx-js.md", ref_names)
        self.assertIn("ooxml.md", ref_names)

    def test_frontmatter_parsing(self):
        from ms_agent.skill.schema import SkillSchemaParser
        content = '---\nname: Test\ndescription: "desc"\n---\nBody'
        fm = SkillSchemaParser.parse_yaml_frontmatter(content)
        self.assertEqual(fm["name"], "Test")

    def test_skill_schema_validation(self):
        from ms_agent.skill.schema import SkillSchemaParser
        skill = SkillSchemaParser.parse_skill_directory(
            CLAUDE_SKILLS_DIR / "pdf")
        errors = SkillSchemaParser.validate_skill_schema(skill)
        self.assertEqual(len(errors), 0)


# ============================================================
# 8. End-to-end pipeline
# ============================================================

class TestEndToEnd(unittest.TestCase):

    def test_full_pipeline_with_claude_skills(self):
        from ms_agent.skill.catalog import SkillCatalog
        from ms_agent.skill.prompt_injector import SkillPromptInjector
        from ms_agent.skill.skill_tools import SkillToolSet

        cfg = OmegaConf.create({"path": [str(CLAUDE_SKILLS_DIR)]})
        catalog = SkillCatalog(config=cfg)
        catalog.load_from_config(cfg)

        skills = catalog.get_enabled_skills()
        self.assertIn("docx", skills)
        self.assertIn("pdf", skills)

        injector = SkillPromptInjector(catalog)
        section = injector.build_skill_prompt_section()
        self.assertIn("Available Skills", section)
        self.assertIn("docx", section)
        self.assertIn("pdf", section)

        toolset = SkillToolSet(
            DictConfig({}), catalog, enable_manage=False)

        list_result = toolset._handle_skills_list({})
        data = json.loads(list_result)
        self.assertGreaterEqual(data["total"], 2)

        view_result = toolset._handle_skill_view(
            {"skill_id": "pdf"})
        view_data = json.loads(view_result)
        self.assertEqual(view_data["name"], "pdf")
        self.assertIn("scripts", view_data["linked_files"])


if __name__ == "__main__":
    unittest.main()
