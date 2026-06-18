import os
import tempfile
import pytest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from ms_agent.skill.runtime import SkillRuntime


# -- Minimal mocks that mirror the real API surface --

@dataclass
class MockSkill:
    skill_id: str = 'test-skill'
    name: str = 'Test Skill'
    description: str = 'A test skill'
    content: str = '---\nname: Test\n---\nBody'
    tags: List[str] = field(default_factory=list)
    scripts: List[str] = field(default_factory=list)
    version: str = '1.0'
    skill_path: str = '/mock'


class MockCatalog:
    def __init__(self, skills: Optional[Dict[str, MockSkill]] = None):
        self._skills: Dict[str, MockSkill] = skills or {}
        self._disabled_skills: Set[str] = set()
        self._cache_version = 0

    def get_skill(self, skill_id):
        return self._skills.get(skill_id)

    def enable_skill(self, skill_id):
        self._disabled_skills.discard(skill_id)
        self._cache_version += 1

    def disable_skill(self, skill_id):
        self._disabled_skills.add(skill_id)
        self._cache_version += 1

    def reload_skill(self, skill_id):
        if skill_id in self._skills:
            return self._skills[skill_id]
        return None

    def reload(self):
        self._cache_version += 1


class MockInjector:
    def __init__(self, catalog):
        self._catalog = catalog

    def build_skill_prompt_section(self):
        enabled = [
            s.name for sid, s in sorted(self._catalog._skills.items())
            if sid not in self._catalog._disabled_skills
        ]
        if not enabled:
            return ''
        return 'Skills: ' + ', '.join(enabled)


class MockConfigManager:
    def __init__(self):
        self.disabled: List[str] = []

    def set_skill_enabled(self, skill_id, enabled):
        if enabled:
            self.disabled = [s for s in self.disabled if s != skill_id]
        else:
            if skill_id not in self.disabled:
                self.disabled.append(skill_id)


@dataclass
class MockMessage:
    content: str = ''
    role: str = 'system'


def make_runtime(skills=None, with_config=False, with_injector=True):
    catalog = MockCatalog(skills or {
        'alpha': MockSkill(skill_id='alpha', name='Alpha'),
        'beta': MockSkill(skill_id='beta', name='Beta'),
    })
    injector = MockInjector(catalog) if with_injector else None
    config_mgr = MockConfigManager() if with_config else None
    return SkillRuntime(catalog, injector, config_mgr), catalog, config_mgr


class TestToggle:
    def test_enable_disabled_skill(self):
        rt, cat, _ = make_runtime()
        cat._disabled_skills.add('alpha')
        assert rt.toggle('alpha', True) is True
        assert 'alpha' not in cat._disabled_skills

    def test_disable_enabled_skill(self):
        rt, cat, _ = make_runtime()
        assert rt.toggle('alpha', False) is True
        assert 'alpha' in cat._disabled_skills

    def test_nonexistent_returns_false(self):
        rt, _, _ = make_runtime()
        assert rt.toggle('ghost', False) is False

    def test_noop_returns_false(self):
        rt, _, _ = make_runtime()
        assert rt.toggle('alpha', True) is False  # already enabled

    def test_persists_to_config(self):
        rt, _, cfg = make_runtime(with_config=True)
        rt.toggle('alpha', False)
        assert 'alpha' in cfg.disabled
        rt.toggle('alpha', True)
        assert 'alpha' not in cfg.disabled

    def test_version_increments(self):
        rt, _, _ = make_runtime()
        v0 = rt.version
        rt.toggle('alpha', False)
        assert rt.version == v0 + 1
        rt.toggle('alpha', True)
        assert rt.version == v0 + 2

    def test_noop_does_not_increment(self):
        rt, _, _ = make_runtime()
        v0 = rt.version
        rt.toggle('alpha', True)  # noop
        assert rt.version == v0


class TestListAll:
    def test_includes_all_skills(self):
        rt, _, _ = make_runtime()
        items = rt.list_all()
        ids = [i['skill_id'] for i in items]
        assert 'alpha' in ids
        assert 'beta' in ids

    def test_enabled_flag_reflects_state(self):
        rt, cat, _ = make_runtime()
        cat._disabled_skills.add('beta')
        items = {i['skill_id']: i for i in rt.list_all()}
        assert items['alpha']['enabled'] is True
        assert items['beta']['enabled'] is False

    def test_sorted_by_id(self):
        rt, _, _ = make_runtime()
        items = rt.list_all()
        ids = [i['skill_id'] for i in items]
        assert ids == sorted(ids)


class TestRefresh:
    def test_needs_refresh_after_toggle(self):
        rt, _, _ = make_runtime()
        assert rt.needs_refresh() is False
        rt.toggle('alpha', False)
        assert rt.needs_refresh() is True

    def test_refresh_injection(self):
        rt, _, _ = make_runtime()
        text = rt.refresh_injection()
        assert 'Alpha' in text
        assert 'Beta' in text

    def test_refresh_injection_after_disable(self):
        rt, _, _ = make_runtime()
        rt.toggle('alpha', False)
        text = rt.refresh_injection()
        assert 'Alpha' not in text
        assert 'Beta' in text

    def test_refresh_injection_no_injector(self):
        rt, _, _ = make_runtime(with_injector=False)
        assert rt.refresh_injection() == ''


class TestSystemPromptRefresh:
    def test_maybe_refresh_updates_content(self):
        rt, _, _ = make_runtime()
        builder_calls = []

        def builder():
            builder_calls.append(1)
            return 'new system prompt'

        rt.set_system_content_builder(builder)
        messages = [MockMessage(content='old system prompt')]

        rt.toggle('alpha', False)
        result = rt.maybe_refresh_system_prompt(messages)
        assert result is True
        assert messages[0].content == 'new system prompt'
        assert len(builder_calls) == 1

    def test_maybe_refresh_noop_when_no_change(self):
        rt, _, _ = make_runtime()
        rt.set_system_content_builder(lambda: 'content')
        messages = [MockMessage(content='content')]

        result = rt.maybe_refresh_system_prompt(messages)
        assert result is False  # no toggle happened

    def test_maybe_refresh_skips_same_content(self):
        rt, _, _ = make_runtime()
        rt.set_system_content_builder(lambda: 'same')
        messages = [MockMessage(content='same')]

        rt.toggle('alpha', False)
        rt.toggle('alpha', True)  # toggle back
        # version changed but content is same
        rt.set_system_content_builder(lambda: 'same')
        result = rt.maybe_refresh_system_prompt(messages)
        assert result is False

    def test_maybe_refresh_clears_needs_refresh(self):
        rt, _, _ = make_runtime()
        rt.set_system_content_builder(lambda: 'x')
        rt.toggle('alpha', False)
        assert rt.needs_refresh() is True

        rt.maybe_refresh_system_prompt([MockMessage()])
        assert rt.needs_refresh() is False

    def test_maybe_refresh_no_builder(self):
        rt, _, _ = make_runtime()
        messages = [MockMessage()]
        rt.toggle('alpha', False)
        result = rt.maybe_refresh_system_prompt(messages)
        assert result is False
        assert rt.needs_refresh() is False  # version aligned anyway

    def test_maybe_refresh_empty_messages(self):
        rt, _, _ = make_runtime()
        rt.set_system_content_builder(lambda: 'x')
        rt.toggle('alpha', False)
        result = rt.maybe_refresh_system_prompt([])
        assert result is False


class TestReload:
    def test_reload_skill(self):
        rt, _, _ = make_runtime()
        assert rt.reload_skill('alpha') is True
        assert rt.needs_refresh() is True

    def test_reload_nonexistent(self):
        rt, _, _ = make_runtime()
        v = rt.version
        assert rt.reload_skill('ghost') is False
        assert rt.version == v

    def test_reload_all(self):
        rt, _, _ = make_runtime()
        v = rt.version
        rt.reload_all()
        assert rt.version == v + 1
