"""Skill-update notice lifecycle: surface diffing, sidecar commit semantics,
and the five-phase state walk from the design doc."""
import time
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from ms_agent.skill import notice as skill_notice
from ms_agent.skill.notice import build_surface, pending_notice
from ms_agent.session.session_log import SessionLog


@pytest.fixture(autouse=True)
def _isolated_user_tree(tmp_path, monkeypatch):
    """Keep the catalog's implicit <home>/skills scan out of these tests —
    other suites materialize skills into the shared test home."""
    import ms_agent.skill.catalog as cat_mod

    monkeypatch.setattr(cat_mod, "USER_SKILLS_DIR", tmp_path / "_no_user_tree")
    monkeypatch.setattr(cat_mod, "global_standard_skills_tree",
                        lambda: tmp_path / "_no_standard_tree")


def _mk_skill(root: Path, skill_id: str, desc: str = "d") -> Path:
    d = root / skill_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f'---\nname: {skill_id}\ndescription: "{desc}"\n---\n# {skill_id}\n',
        encoding="utf-8",
    )
    return d


def _catalog(*dirs):
    from ms_agent.skill.catalog import SkillCatalog

    cfg = OmegaConf.create(
        {"sources": [{
            "type": "local",
            "path": str(d)
        } for d in dirs]})
    cat = SkillCatalog(config=cfg)
    cat.load_from_config(cfg)
    return cat


def test_brand_new_session_inits_silently(tmp_path):
    log = SessionLog(tmp_path / "session", session_key="notice")
    cat = _catalog(_mk_skill(tmp_path, "alpha").parent)

    notice, commit = pending_notice(cat, log)
    assert notice is None  # head is fresh by construction — no announcement
    # A new-session baseline must not be committed before the first message.
    surface_file = log.directory / "skill_surface.json"
    assert not surface_file.exists()
    log.append({"role": "user", "content": "first"})
    commit()
    assert surface_file.exists()

    # next turn, unchanged: still silent
    notice, _ = pending_notice(cat, log)
    assert notice is None


def test_legacy_session_without_sidecar_gets_full_notice(
        tmp_path, monkeypatch):
    log = SessionLog(tmp_path / "session", session_key="notice")
    # A session that predates the sidecar: history exists, surface unknown.
    log.append({"role": "user", "content": "older turn"})
    cat = _catalog(_mk_skill(tmp_path, "alpha").parent)

    notice, commit = pending_notice(cat, log)
    assert notice is not None
    assert "may have changed since this session started" in notice
    assert "alpha" in notice
    assert "Do not mention this notice to the user." in notice

    # not committed yet → re-fires
    notice2, _ = pending_notice(cat, log)
    assert notice2 is not None

    commit()  # turn enqueued → persist
    notice3, _ = pending_notice(cat, log)
    assert notice3 is None


def test_add_remove_and_content_update_lines(tmp_path):
    log = SessionLog(tmp_path / "session", session_key="notice")
    tree = tmp_path / "tree"
    _mk_skill(tree, "alpha")
    _mk_skill(tree, "beta")
    cat = _catalog(tree)
    _, commit = pending_notice(cat, log)
    commit()

    # remove beta, add gamma, touch alpha's references/
    import shutil

    shutil.rmtree(tree / "beta")
    _mk_skill(tree, "gamma")
    ref = tree / "alpha" / "references"
    ref.mkdir()
    (ref / "guide.md").write_text("# guide\n", encoding="utf-8")

    cat2 = _catalog(tree)
    notice, commit2 = pending_notice(cat2, log)
    assert notice is not None
    assert "Newly added since last known state: gamma" in notice
    assert "Removed or disabled since last known state: beta" in notice
    assert "Content updated since last known state: alpha" in notice
    assert "re-read it via skill_view" in notice
    commit2()

    notice2, _ = pending_notice(cat2, log)
    assert notice2 is None


def test_reference_file_edit_alone_triggers_notice(tmp_path):
    log = SessionLog(tmp_path / "session", session_key="notice")
    tree = tmp_path / "tree"
    skill = _mk_skill(tree, "alpha")
    ref = skill / "references"
    ref.mkdir()
    target = ref / "guide.md"
    target.write_text("v1", encoding="utf-8")

    cat = _catalog(tree)
    _, commit = pending_notice(cat, log)
    commit()

    # edit only the reference file (mtime/size change)
    time.sleep(0.01)
    target.write_text("v2 — longer content", encoding="utf-8")

    notice, _ = pending_notice(_catalog(tree), log)
    assert notice is not None
    assert "Content updated since last known state: alpha" in notice


def test_surface_reuses_signature_from_full_catalog_load(
        tmp_path, monkeypatch):
    cat = _catalog(_mk_skill(tmp_path, "alpha").parent)

    def _unexpected_walk(_path):
        raise AssertionError(
            "notice must reuse the SDK materialization signature")

    monkeypatch.setattr(skill_notice, "_files_sig", _unexpected_walk)
    surface = build_surface(cat)

    assert surface["alpha"]["files"] == cat.get_skill("alpha")._files_signature


def test_description_edit_triggers_notice(tmp_path):
    log = SessionLog(tmp_path / "session", session_key="notice")
    tree = tmp_path / "tree"
    _mk_skill(tree, "alpha", desc="old description")
    cat = _catalog(tree)
    _, commit = pending_notice(cat, log)
    commit()

    _mk_skill(tree, "alpha", desc="new description")
    notice, _ = pending_notice(_catalog(tree), log)
    assert notice is not None
    assert "Content updated since last known state: alpha" in notice


def test_all_skills_removed_renders_empty_list(tmp_path):
    log = SessionLog(tmp_path / "session", session_key="notice")
    tree = tmp_path / "tree"
    _mk_skill(tree, "alpha")
    _, commit = pending_notice(_catalog(tree), log)
    commit()

    import shutil

    shutil.rmtree(tree / "alpha")
    notice, _ = pending_notice(_catalog(tree), log)
    assert notice is not None
    assert "(no skills are currently available)" in notice
    assert "Removed or disabled since last known state: alpha" in notice


def test_surface_tracks_enabled_only(tmp_path):
    tree = tmp_path / "tree"
    _mk_skill(tree, "alpha")
    _mk_skill(tree, "beta")
    cat = _catalog(tree)
    cat.disable_skill("beta")
    surface = build_surface(cat)
    assert set(surface) == {"alpha"}


@pytest.mark.parametrize('enabled', [True, False])
def test_tui_keeps_independent_notice_delivery(tmp_path, monkeypatch, enabled):
    from ms_agent.agent.llm_agent import LLMAgent
    from ms_agent.llm.utils import Message
    from ms_agent.skill.runtime import SkillRuntime
    from ms_agent.tui.live_config import _sync_skills

    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path / 'home'))
    tree = tmp_path / 'tree'
    skill = _mk_skill(tree, 'alpha')
    catalog = _catalog(tree)
    agent = LLMAgent.__new__(LLMAgent)
    agent.config = OmegaConf.create({
        'output_dir': str(tmp_path / 'work'),
        'skills': {
            'update_notice': enabled,
            'sources': [{
                'type': 'local',
                'path': str(tree)
            }]
        },
    })
    agent._skill_catalog = catalog
    agent._skill_runtime = SkillRuntime(catalog=catalog)
    agent.session_log = SessionLog(tmp_path / 'session', session_key='tui')
    first = [Message(role='user', content='first')]
    _sync_skills(agent, None)
    assert agent._attach_skill_update_notice(first) is None
    assert first[0].content == 'first'
    agent.session_log.append({'role': 'user', 'content': 'first'})

    (skill / 'SKILL.md'
     ).write_text('---\nname: alpha\ndescription: Changed\n---\nNew body\n')
    next_turn = [Message(role='user', content='continue')]
    _sync_skills(agent, next_turn)
    assert next_turn[0].content.count('Skill inventory updated.') == int(enabled)
    original = next_turn[0].content
    assert agent._attach_skill_update_notice(next_turn) is None
    assert next_turn[0].content == original
    assert not (agent.session_log.directory / 'skill_surface.json').exists()

    unchanged = [Message(role='user', content='unchanged')]
    _sync_skills(agent, unchanged)
    assert agent._attach_skill_update_notice(unchanged) is None
    assert unchanged[0].content == 'unchanged'


@pytest.mark.parametrize('payload',
                         ['null', '[]', '{"skills": {"alpha": 1}}', '{'])
def test_corrupt_baseline_resynchronizes_without_breaking_chat(
        tmp_path, payload):
    log = SessionLog(tmp_path / 'session', session_key='corrupt')
    log.append({'role': 'user', 'content': 'earlier turn'})
    (log.directory / 'skill_surface.json').write_text(payload)
    catalog = _catalog(_mk_skill(tmp_path / 'tree', 'alpha').parent)
    notice, commit = pending_notice(catalog, log)
    assert 'CURRENT full list' in notice and 'alpha' in notice
    commit()
    assert pending_notice(catalog, log) == (None, None)
