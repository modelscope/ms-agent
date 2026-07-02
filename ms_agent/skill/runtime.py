"""SkillRuntime — unified runtime skill state management.

Wraps SkillCatalog + SkillPromptInjector + SkillsConfigManager into a
single entry point for skill enable/disable, listing, prompt refresh,
and hot-reload.

Key design:
- toggle() updates both memory (catalog) and disk (config_manager)
- list_all() returns full skill inventory with enabled flags (for UI)
- maybe_refresh_system_prompt() rebuilds messages[0] when state changed
- Version tracking avoids unnecessary rebuilds
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from ms_agent.config.skills_manager import SkillsConfigManager
    from ms_agent.skill.catalog import SkillCatalog
    from ms_agent.skill.prompt_injector import SkillPromptInjector


class SkillRuntime:

    def __init__(
        self,
        catalog: 'SkillCatalog',
        injector: Optional['SkillPromptInjector'] = None,
        config_manager: Optional['SkillsConfigManager'] = None,
    ) -> None:
        self._catalog = catalog
        self._injector = injector
        self._config_manager = config_manager
        self._version: int = 0
        self._last_applied_version: int = 0
        self._system_content_builder: Optional[Callable[[], str]] = None

    @property
    def catalog(self) -> 'SkillCatalog':
        return self._catalog

    @property
    def version(self) -> int:
        return self._version

    def set_system_content_builder(
        self, builder: Callable[[], str]
    ) -> None:
        self._system_content_builder = builder

    # -- toggle --

    def toggle(self, skill_id: str, enabled: bool) -> bool:
        """Toggle a skill's enabled state.

        Updates both memory (catalog._disabled_skills) and disk
        (skills.json disabled list) when config_manager is set.

        Returns True if the state actually changed.
        """
        skill = self._catalog.get_skill(skill_id)
        if skill is None:
            return False

        was_enabled = skill_id not in self._catalog._disabled_skills
        if enabled == was_enabled:
            return False

        if enabled:
            self._catalog.enable_skill(skill_id)
        else:
            self._catalog.disable_skill(skill_id)

        if self._config_manager:
            self._config_manager.set_skill_enabled(skill_id, enabled)

        self._version += 1
        return True

    # -- query --

    def list_all(self) -> List[Dict[str, Any]]:
        """Return all skills with enabled status (UI data source)."""
        result: List[Dict[str, Any]] = []
        for sid in sorted(self._catalog._skills):
            skill = self._catalog._skills[sid]
            result.append({
                'skill_id': sid,
                'name': skill.name,
                'description': skill.description,
                'enabled': sid not in self._catalog._disabled_skills,
                'tags': skill.tags,
                'has_scripts': bool(skill.scripts),
                'version': skill.version,
                'origin': getattr(skill, '_origin', 'config'),
                'plugin_id': getattr(skill, '_plugin_id', None),
                'capability': getattr(skill, '_capability', None),
            })
        return result

    # -- prompt refresh --

    def refresh_injection(self) -> str:
        """Rebuild the skill prompt section text."""
        if self._injector is None:
            return ''
        return self._injector.build_skill_prompt_section()

    def needs_refresh(self) -> bool:
        return self._version != self._last_applied_version

    def maybe_refresh_system_prompt(
        self, messages: list
    ) -> bool:
        """Rebuild messages[0] if skill state changed since last apply.

        Uses _system_content_builder (injected by LLMAgent) to fully
        rebuild the system prompt content, covering skills, personalization,
        and base prompt in one pass.

        Returns True if the system prompt was actually updated.
        """
        if not self.needs_refresh():
            return False
        if not messages or not self._system_content_builder:
            self._last_applied_version = self._version
            return False

        new_content = self._system_content_builder()
        changed = messages[0].content != new_content
        if changed:
            messages[0].content = new_content

        self._last_applied_version = self._version
        return changed

    # -- reload --

    def reload_skill(self, skill_id: str) -> bool:
        result = self._catalog.reload_skill(skill_id)
        if result is not None:
            self._version += 1
        return result is not None

    def reload_all(self) -> None:
        self._catalog.reload()
        self._version += 1
