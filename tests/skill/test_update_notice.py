"""Notice mode: head stability gate + conditional prompt wording +
compaction preservation rule."""
from omegaconf import OmegaConf

from ms_agent.skill.catalog import SkillCatalog
from ms_agent.skill.prompt_injector import SkillPromptInjector
from ms_agent.skill.runtime import SkillRuntime


def _mk_skill(root, skill_id):
    d = root / skill_id
    d.mkdir(parents=True)
    (d / 'SKILL.md').write_text(
        f'---\nname: {skill_id}\ndescription: "d"\n---\n# {skill_id}\n',
        encoding='utf-8')
    return d


def _catalog(tmp_path):
    _mk_skill(tmp_path, 'alpha')
    cfg = OmegaConf.create(
        {'sources': [{'type': 'local', 'path': str(tmp_path)}]})
    cat = SkillCatalog(config=cfg)
    cat.load_from_config(cfg)
    return cat


class _Msg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class TestHeadGate:

    def test_notice_mode_pins_skill_section_but_head_still_refreshes(
            self, tmp_path):
        """Source-tiered refresh (2026-08): in update_notice mode the SKILL
        section is frozen at its session snapshot (skill changes ride the
        in-conversation notices), while instruction/persona layers keep
        hot-reloading through the content compare."""
        cat = _catalog(tmp_path)
        injector = SkillPromptInjector(cat, update_notice=True)
        rt = SkillRuntime(catalog=cat, injector=injector)
        rt.head_refresh_enabled = False

        frozen = rt.build_skill_section()
        assert 'alpha' in frozen
        # a skill change must NOT alter the pinned section...
        rt.toggle('alpha', False)
        assert rt.build_skill_section() == frozen
        # ...while the live injector output did change underneath
        assert injector.build_skill_prompt_section() != frozen

        instructions = {'text': 'OLD INSTRUCTIONS'}
        rt.set_system_content_builder(
            lambda: instructions['text'] + '\n\n' + rt.build_skill_section())
        messages = [_Msg('system', 'OLD INSTRUCTIONS\n\n' + frozen)]
        # nothing changed -> zero churn (skill toggle above is invisible)
        assert rt.maybe_refresh_system_prompt(messages) is False
        # an instruction-layer change (e.g. edited AGENTS.md) DOES apply
        instructions['text'] = 'EDITED INSTRUCTIONS'
        assert rt.maybe_refresh_system_prompt(messages) is True
        assert messages[0].content.startswith('EDITED INSTRUCTIONS')
        assert frozen in messages[0].content

    def test_enabled_gate_still_refreshes(self, tmp_path):
        cat = _catalog(tmp_path)
        rt = SkillRuntime(catalog=cat)
        rt.set_system_content_builder(lambda: 'NEW HEAD')

        messages = [_Msg('system', 'OLD HEAD')]
        assert rt.maybe_refresh_system_prompt(messages) is True
        assert messages[0].content == 'NEW HEAD'

    def test_non_system_head_never_clobbered(self, tmp_path):
        cat = _catalog(tmp_path)
        rt = SkillRuntime(catalog=cat)
        rt.set_system_content_builder(lambda: 'NEW HEAD')

        messages = [_Msg('user', 'hello')]
        assert rt.maybe_refresh_system_prompt(messages) is False
        assert messages[0].content == 'hello'


class TestNoticeWording:

    def test_update_notice_hint_present_when_enabled(self, tmp_path):
        cat = _catalog(tmp_path)
        injector = SkillPromptInjector(cat, update_notice=True)
        section = injector.build_skill_prompt_section()
        assert 'skill-update notice' in section
        assert 'LATEST one is authoritative' in section

    def test_hint_absent_by_default(self, tmp_path):
        cat = _catalog(tmp_path)
        section = SkillPromptInjector(cat).build_skill_prompt_section()
        assert 'skill-update notice' not in section


def test_summary_prompt_preserves_latest_notice():
    from ms_agent.session.strategies.summary_compactor import SUMMARY_PROMPT
    assert 'skill-update notice' in SUMMARY_PROMPT
