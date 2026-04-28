# Copyright (c) ModelScope Contributors. All rights reserved.
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from ms_agent.tools.base import ToolBase
from ms_agent.utils.logger import get_logger

from .catalog import USER_SKILLS_DIR
from .schema import SkillSchemaParser

logger = get_logger()


class SkillToolSet(ToolBase):
    """Exposes skill discovery and management as standard tools
    registered through ToolManager.

    Provided tools:
      - skills_list:  browse available skills
      - skill_view:   read full skill content or attached files
      - skill_manage: create / edit / delete skills (optional)
    """

    TOOL_SERVER_NAME = "skills"

    def __init__(self, config, catalog, *, enable_manage: bool = False):
        super().__init__(config)
        self._catalog = catalog
        self._enable_manage = enable_manage

    async def connect(self) -> None:
        pass

    async def cleanup(self) -> None:
        pass

    # ------------------------------------------------------------------ #
    #  Tool schema
    # ------------------------------------------------------------------ #

    async def _get_tools_inner(self) -> Dict[str, Any]:
        tools = []

        tools.append({
            "tool_name": "skills_list",
            "description": (
                "List all available skills with their names and descriptions. "
                "Use this to discover what skills are available before viewing "
                "their full content."),
            "parameters": {
                "type": "object",
                "properties": {
                    "tag": {
                        "type": "string",
                        "description":
                            "Optional tag to filter skills by category",
                    }
                },
            },
        })

        tools.append({
            "tool_name": "skill_view",
            "description": (
                "View the full content of a skill, including its instructions, "
                "available scripts, references, and resources. "
                "You can also view a specific file within the skill directory. "
                "After reading a skill, follow its instructions using your "
                "available tools."),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_id": {
                        "type": "string",
                        "description": "The skill identifier",
                    },
                    "file_path": {
                        "type": "string",
                        "description": (
                            "Optional: relative path to a specific file "
                            "within the skill directory (e.g. "
                            "'scripts/search.py'). If omitted, returns "
                            "the main SKILL.md content."),
                    },
                },
                "required": ["skill_id"],
            },
        })

        if self._enable_manage:
            tools.append({
                "tool_name": "skill_manage",
                "description": (
                    "Create, edit, or delete a skill. Use this to save "
                    "reusable procedures that you learn during "
                    "conversations."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["create", "edit", "delete"],
                            "description": "The action to perform",
                        },
                        "skill_id": {
                            "type": "string",
                            "description":
                                "Skill identifier (hyphen-case)",
                        },
                        "content": {
                            "type": "string",
                            "description": (
                                "For create/edit: full SKILL.md content "
                                "including YAML frontmatter"),
                        },
                    },
                    "required": ["action", "skill_id"],
                },
            })

        return {self.TOOL_SERVER_NAME: tools}

    # ------------------------------------------------------------------ #
    #  Dispatch
    # ------------------------------------------------------------------ #

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        if tool_name == "skills_list":
            return self._handle_skills_list(tool_args)
        elif tool_name == "skill_view":
            return self._handle_skill_view(tool_args)
        elif tool_name == "skill_manage" and self._enable_manage:
            return self._handle_skill_manage(tool_args)
        raise ValueError(f"Unknown skill tool: {tool_name}")

    # ------------------------------------------------------------------ #
    #  skills_list
    # ------------------------------------------------------------------ #

    def _handle_skills_list(self, args: dict) -> str:
        tag_filter = args.get("tag")
        skills = self._catalog.get_enabled_skills()

        if tag_filter:
            skills = {
                sid: s for sid, s in skills.items()
                if tag_filter in (s.tags or [])
            }

        if not skills:
            return "No skills available."

        result = []
        for sid, skill in sorted(skills.items()):
            entry = {
                "skill_id": sid,
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "tags": skill.tags or [],
                "has_scripts": len(skill.scripts) > 0,
                "has_references": len(skill.references) > 0,
            }
            result.append(entry)

        return json.dumps(
            {"skills": result, "total": len(result)},
            ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------ #
    #  skill_view
    # ------------------------------------------------------------------ #

    def _handle_skill_view(self, args: dict) -> str:
        skill_id = args.get("skill_id", "")
        file_path = args.get("file_path")

        skill = self._catalog.get_skill(skill_id)
        if not skill:
            return json.dumps({"error": f"Skill '{skill_id}' not found"})

        if file_path:
            return self._read_skill_file(skill, file_path)

        result: Dict[str, Any] = {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "description": skill.description,
            "skill_dir": str(skill.skill_path),
            "content": skill.content,
            "linked_files": {
                "scripts": [s.name for s in skill.scripts],
                "references": [r.name for r in skill.references],
                "resources": [
                    r.name for r in skill.resources
                    if r.name not in ("SKILL.md", "LICENSE.txt")
                ],
            },
        }

        dep_status = self._check_requirements(skill)
        if dep_status:
            result["requirements_status"] = dep_status

        return json.dumps(result, ensure_ascii=False, indent=2)

    def _read_skill_file(self, skill, file_path: str) -> str:
        """Read a file inside the skill directory with traversal protection."""
        target = (skill.skill_path / file_path).resolve()
        skill_root = skill.skill_path.resolve()

        if not str(target).startswith(str(skill_root)):
            return json.dumps({"error": "Path traversal not allowed"})

        if not target.exists():
            return json.dumps({"error": f"File not found: {file_path}"})

        try:
            content = target.read_text(encoding="utf-8")
            return json.dumps(
                {"file_path": file_path, "content": content},
                ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"Failed to read file: {e}"})

    def _check_requirements(self, skill) -> Optional[dict]:
        frontmatter = SkillSchemaParser.parse_yaml_frontmatter(skill.content)
        if not frontmatter:
            return None

        requires = frontmatter.get("requires", {})
        if not requires:
            return None

        status: Dict[str, Any] = {}
        required_env = requires.get("env", [])
        if required_env:
            missing = [v for v in required_env if v not in os.environ]
            if missing:
                status["missing_env_vars"] = missing

        required_tools = requires.get("tools", [])
        if required_tools:
            status["required_tools"] = required_tools

        return status if status else None

    # ------------------------------------------------------------------ #
    #  skill_manage
    # ------------------------------------------------------------------ #

    def _handle_skill_manage(self, args: dict) -> str:
        action = args.get("action", "")
        skill_id = args.get("skill_id", "")

        if action == "create":
            return self._create_skill(skill_id, args.get("content", ""))
        elif action == "edit":
            return self._edit_skill(skill_id, args.get("content", ""))
        elif action == "delete":
            return self._delete_skill(skill_id)
        return json.dumps({"error": f"Unknown action: {action}"})

    def _create_skill(self, skill_id: str, content: str) -> str:
        custom_dir = self._get_custom_skills_dir()
        skill_dir = custom_dir / skill_id

        if skill_dir.exists():
            return json.dumps(
                {"error": f"Skill '{skill_id}' already exists"})

        frontmatter = SkillSchemaParser.parse_yaml_frontmatter(content)
        if (not frontmatter or "name" not in frontmatter
                or "description" not in frontmatter):
            return json.dumps({
                "error":
                    "Invalid SKILL.md: must have YAML frontmatter "
                    "with 'name' and 'description'"
            })

        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        skill = self._catalog.add_skill(str(skill_dir))
        if skill:
            return json.dumps({
                "success": True,
                "skill_id": skill.skill_id,
                "message": f"Skill '{skill.name}' created successfully",
            })
        return json.dumps({"error": "Failed to load created skill"})

    def _edit_skill(self, skill_id: str, content: str) -> str:
        skill = self._catalog.get_skill(skill_id)
        if not skill:
            return json.dumps(
                {"error": f"Skill '{skill_id}' not found"})

        frontmatter = SkillSchemaParser.parse_yaml_frontmatter(content)
        if (not frontmatter or "name" not in frontmatter
                or "description" not in frontmatter):
            return json.dumps({
                "error":
                    "Invalid content: must have YAML frontmatter "
                    "with 'name' and 'description'"
            })

        skill_md_path = skill.skill_path / "SKILL.md"
        skill_md_path.write_text(content, encoding="utf-8")

        reloaded = self._catalog.reload_skill(skill_id)
        if reloaded:
            return json.dumps({
                "success": True,
                "message": f"Skill '{skill_id}' updated successfully",
            })
        return json.dumps({"error": "Failed to reload updated skill"})

    def _delete_skill(self, skill_id: str) -> str:
        skill = self._catalog.get_skill(skill_id)
        if not skill:
            return json.dumps(
                {"error": f"Skill '{skill_id}' not found"})

        custom_dir = self._get_custom_skills_dir().resolve()
        if not str(skill.skill_path.resolve()).startswith(str(custom_dir)):
            return json.dumps(
                {"error": "Can only delete custom skills"})

        shutil.rmtree(skill.skill_path)
        self._catalog.remove_skill(skill_id)

        return json.dumps({
            "success": True,
            "message": f"Skill '{skill_id}' deleted successfully",
        })

    def _get_custom_skills_dir(self) -> Path:
        base = USER_SKILLS_DIR / "custom"
        base.mkdir(parents=True, exist_ok=True)
        return base
