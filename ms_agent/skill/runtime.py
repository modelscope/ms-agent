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
        # False when the host delivers skill updates as in-conversation
        # notices (``skills.update_notice``): the SKILL SECTION of the system
        # prompt is then frozen at its session-start snapshot (byte-stable —
        # prefix-cache friendly; changes are announced via notices), while the
        # OTHER head layers (base/persona/instructions/profile/memory) keep
        # hot-reloading through the content compare — an edited AGENTS.md must
        # apply next round even in notice mode (source-tiered refresh).
        self.head_refresh_enabled: bool = True
        self._frozen_skill_section: Optional[str] = None

    @property
    def catalog(self) -> 'SkillCatalog':
        return self._catalog

    @property
    def version(self) -> int:
        return self._version

    def set_system_content_builder(self, builder: Callable[[], str]) -> None:
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

    def build_skill_section(self) -> str:
        """The skill section for the system prompt, honoring notice mode.

        With ``head_refresh_enabled`` (default) this is a live rebuild. In
        notice mode (``skills.update_notice``) the section is computed once
        and frozen for the session: skill changes must not perturb the head
        (they are announced in-conversation instead), yet the head as a whole
        stays hot-reloadable for the instruction/persona layers.
        """
        if self._injector is None:
            return ''
        if self.head_refresh_enabled:
            return self._injector.build_skill_prompt_section()
        if self._frozen_skill_section is None:
            self._frozen_skill_section = \
                self._injector.build_skill_prompt_section()
        return self._frozen_skill_section

    def maybe_refresh_system_prompt(self, messages: list) -> bool:
        """Keep messages[0] in step with the current skill state.

        Rebuilds the system prompt via _system_content_builder (injected by
        LLMAgent — covers base prompt, personalization and skill injection)
        and replaces messages[0].content when it differs. Content comparison
        every round — NOT a version gate — because the round context may be
        rebuilt from the SessionLog (context_assembler.assemble, resume from
        cache), which resurrects the system prompt as persisted at write
        time; an apply-once version latch would let that stale copy through
        on every later round. An in-step prompt compares equal — zero churn.

        Runs in notice mode too: the builder pins the skill section via
        build_skill_section(), so only instruction/persona/profile changes can
        alter the head there — skill toggles still never touch it.

        Returns True if the system prompt was actually updated.
        """
        if not messages or not self._system_content_builder:
            self._last_applied_version = self._version
            return False
        head = messages[0]
        if getattr(head, 'role', None) != 'system':
            # Never clobber a non-system head (restored log without a
            # system row).
            self._last_applied_version = self._version
            return False

        new_content = self._system_content_builder()
        changed = head.content != new_content
        if changed:
            head.content = new_content

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

    def sync_with_config(self, skills_config, *, force: bool = True) -> bool:
        """Resync the catalog from an updated skills config; bump the
        version only when the effective skill surface (inventory, metadata,
        disabled set) actually changed, so maybe_refresh_system_prompt()
        rebuilds messages[0] on real change and stays a no-op otherwise.

        Existing callers retain the full-resync behavior by default.  A host
        with an authoritative change tracker may pass ``force=False`` to skip
        I/O for a known-clean turn.  Returns True when the surface changed.
        """
        if not force:
            return False
        before = self._surface()
        self._catalog.resync(skills_config)
        after = self._surface()
        if before != after:
            self._version += 1
            return True
        return False

    def _surface(self):
        catalog = self._catalog
        inventory = {
            sid: (skill.name, skill.description, skill.version)
            for sid, skill in catalog._skills.items()
        }
        return (inventory, frozenset(catalog._disabled_skills))
