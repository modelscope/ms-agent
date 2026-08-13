# Copyright (c) ModelScope Contributors. All rights reserved.
"""Regression tripwire: tool names referenced in injected prompt text must
exist in the skill toolset. If a tool is renamed, this fails before the model
starts calling a tool that no longer exists (P0 item 9)."""
import inspect

from ms_agent.skill import skill_tools
from ms_agent.skill.prompt_injector import SkillPromptInjector

REFERENCED = ('skills_list', 'skill_view')


def test_prompt_text_references_real_tool_names():
    prompt_text = (SkillPromptInjector.SKILL_SECTION_HEADER
                   + SkillPromptInjector.DISCOVERY_HINT)
    source = inspect.getsource(skill_tools)
    for name in REFERENCED:
        assert name in prompt_text, f'{name} vanished from the prompt text'
        assert f"'{name}'" in source, (
            f'{name} is referenced in the skill prompt text but no longer '
            f'appears in skill_tools.py — rename both together')


def test_manage_tool_still_dispatched():
    # skill_manage is not advertised in the header (manage is opt-in), but the
    # dispatcher must keep accepting it while any doc/skill references it.
    source = inspect.getsource(skill_tools)
    assert "'skill_manage'" in source
