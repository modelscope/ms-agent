"""Skill-update notice lifecycle: surface diffing, sidecar commit semantics,
and the five-phase state walk from the design doc."""
import time
import uuid
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from app.backends.ms_agent import skill_notice
from app.backends.ms_agent.config import session_dir
from app.backends.ms_agent.skill_notice import build_surface, pending_notice


@pytest.fixture(autouse=True)
def _isolated_user_tree(tmp_path, monkeypatch):
    """Keep the catalog's implicit <home>/skills scan out of these tests —
    other suites materialize skills into the shared test home."""
    import ms_agent.skill.catalog as cat_mod

    monkeypatch.setattr(cat_mod, "USER_SKILLS_DIR", tmp_path / "_no_user_tree")


def _proj_sess():
    """Unique ids per test — the sidecar lives under MS_AGENT_HOME, which the
    conftest scopes per run, not per test."""
    proj = type("P", (), {"id": f"p-{uuid.uuid4().hex[:8]}", "path": ""})()
    sess_id = f"s-{uuid.uuid4().hex[:8]}"
    sess = type("S", (), {"id": sess_id, "session_key": sess_id})()
    return proj, sess


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
        {"sources": [{"type": "local", "path": str(d)} for d in dirs]})
    cat = SkillCatalog(config=cfg)
    cat.load_from_config(cfg)
    return cat


def test_brand_new_session_inits_silently(tmp_path):
    proj, sess = _proj_sess()
    cat = _catalog(_mk_skill(tmp_path, "alpha").parent)

    notice, commit = pending_notice(cat, proj, sess)
    assert notice is None  # head is fresh by construction — no announcement
    # silent init already persisted the surface
    surface_file = Path(session_dir(proj, sess)) / "skill_surface.json"
    assert surface_file.exists()

    # next turn, unchanged: still silent
    notice, _ = pending_notice(cat, proj, sess)
    assert notice is None


def test_legacy_session_without_sidecar_gets_full_notice(tmp_path, monkeypatch):
    proj, sess = _proj_sess()
    # A session that predates the sidecar: history exists, surface unknown.
    monkeypatch.setattr(skill_notice, "session_has_history", lambda p, s: True)
    cat = _catalog(_mk_skill(tmp_path, "alpha").parent)

    notice, commit = pending_notice(cat, proj, sess)
    assert notice is not None
    assert "may have changed since this session started" in notice
    assert "alpha" in notice
    assert "Do not mention this notice to the user." in notice

    # not committed yet → re-fires
    notice2, _ = pending_notice(cat, proj, sess)
    assert notice2 is not None

    commit()  # turn enqueued → persist
    notice3, _ = pending_notice(cat, proj, sess)
    assert notice3 is None


def test_add_remove_and_content_update_lines(tmp_path):
    proj, sess = _proj_sess()
    tree = tmp_path / "tree"
    _mk_skill(tree, "alpha")
    _mk_skill(tree, "beta")
    cat = _catalog(tree)
    _, commit = pending_notice(cat, proj, sess)
    commit()

    # remove beta, add gamma, touch alpha's references/
    import shutil

    shutil.rmtree(tree / "beta")
    _mk_skill(tree, "gamma")
    ref = tree / "alpha" / "references"
    ref.mkdir()
    (ref / "guide.md").write_text("# guide\n", encoding="utf-8")

    cat2 = _catalog(tree)
    notice, commit2 = pending_notice(cat2, proj, sess)
    assert notice is not None
    assert "Newly added since last known state: gamma" in notice
    assert "Removed or disabled since last known state: beta" in notice
    assert "Content updated since last known state: alpha" in notice
    assert "re-read it via skill_view" in notice
    commit2()

    notice2, _ = pending_notice(cat2, proj, sess)
    assert notice2 is None


def test_reference_file_edit_alone_triggers_notice(tmp_path):
    proj, sess = _proj_sess()
    tree = tmp_path / "tree"
    skill = _mk_skill(tree, "alpha")
    ref = skill / "references"
    ref.mkdir()
    target = ref / "guide.md"
    target.write_text("v1", encoding="utf-8")

    cat = _catalog(tree)
    _, commit = pending_notice(cat, proj, sess)
    commit()

    # edit only the reference file (mtime/size change)
    time.sleep(0.01)
    target.write_text("v2 — longer content", encoding="utf-8")

    notice, _ = pending_notice(_catalog(tree), proj, sess)
    assert notice is not None
    assert "Content updated since last known state: alpha" in notice


def test_description_edit_triggers_notice(tmp_path):
    proj, sess = _proj_sess()
    tree = tmp_path / "tree"
    _mk_skill(tree, "alpha", desc="old description")
    cat = _catalog(tree)
    _, commit = pending_notice(cat, proj, sess)
    commit()

    _mk_skill(tree, "alpha", desc="new description")
    notice, _ = pending_notice(_catalog(tree), proj, sess)
    assert notice is not None
    assert "Content updated since last known state: alpha" in notice


def test_all_skills_removed_renders_empty_list(tmp_path):
    proj, sess = _proj_sess()
    tree = tmp_path / "tree"
    _mk_skill(tree, "alpha")
    _, commit = pending_notice(_catalog(tree), proj, sess)
    commit()

    import shutil

    shutil.rmtree(tree / "alpha")
    notice, _ = pending_notice(_catalog(tree), proj, sess)
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
