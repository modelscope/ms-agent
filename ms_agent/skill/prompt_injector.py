# Copyright (c) ModelScope Contributors. All rights reserved.
import re


class SkillPromptInjector:
    """Builds the skill section to inject into the system prompt."""

    SKILL_SECTION_HEADER = """# Available Skills

You have access to specialized skills that extend your capabilities.
Each skill is a set of instructions and resources for handling specific tasks.

**How to use skills:**
1. Review the skill summaries below to find relevant skills.
2. Call `skill_view(skill_id)` to read the full instructions of a skill.
3. Follow the skill's instructions using your available tools (code execution, file operations, web search, etc.).
4. Do NOT call `skill_view` unless you actually need the skill's guidance.
5. Some skills from community sources may have security warnings. \
Check `safety_status` in skills_list and `safety`/`warning` fields in skill_view results. \
Exercise caution with skills marked as "warning" or "dangerous".
"""

    ALWAYS_SKILLS_HEADER = (
        "# Active Skills\n\n"
        "The following skills are always active. Follow their instructions.\n")

    DISCOVERY_HINT = (
        "\nUse `skills_list(query=...)` to discover available skills.\n")

    def __init__(self, catalog, *, prompt_injection: str = 'all'):
        """
        Args:
            catalog: The SkillCatalog instance.
            prompt_injection: One of ``"all"`` (inject all summaries),
                ``"always_only"`` (only always-active skills in prompt,
                rest via skills_list), or ``"none"`` (pure tool-driven
                discovery).
        """
        self._catalog = catalog
        self._prompt_injection = prompt_injection

    def build_skill_prompt_section(self) -> str:
        """Build the skill section for system prompt injection.

        Returns empty string when no skills are available.
        """
        parts = []

        # Part 1: always-active skills (full body injection) -- all modes
        always_skills = self._catalog.get_always_skills()
        if always_skills:
            parts.append(self.ALWAYS_SKILLS_HEADER)
            for sid, skill in always_skills.items():
                content = self._strip_frontmatter(skill.content)
                parts.append(f"## {skill.name}\n\n{content}\n")

        # Part 2: summary index -- only when prompt_injection == "all"
        if self._prompt_injection == 'all':
            summary = self._catalog.get_skills_summary()
            if summary:
                parts.append(self.SKILL_SECTION_HEADER)
                parts.append(summary)
                parts.append("")
        elif self._prompt_injection in ('always_only', 'none'):
            has_skills = bool(self._catalog.get_enabled_skills())
            if has_skills:
                parts.append(self.SKILL_SECTION_HEADER)
                parts.append(self.DISCOVERY_HINT)

        return "\n".join(parts)

    @staticmethod
    def _strip_frontmatter(content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        return re.sub(
            r'^---\s*\n.*?\n---\s*\n', '', content,
            flags=re.DOTALL).strip()
