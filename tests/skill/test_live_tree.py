"""Live-tree skill discovery: anchored relative sources, implicit per-scope
trees, marker-walk loading, catalog resync and turn-boundary sync."""
import json

import pytest
from omegaconf import OmegaConf

from ms_agent.config.skills_manager import (SkillsConfigManager,
                                            resolve_source_entry)
from ms_agent.skill.catalog import SkillCatalog
from ms_agent.skill.loader import SkillLoader
from ms_agent.skill.runtime import SkillRuntime
from ms_agent.tui.managed_config import merge_skills_into_config


def _mk_skill(root, skill_id, description='d'):
    d = root / skill_id
    d.mkdir(parents=True)
    (d / 'SKILL.md').write_text(
        f'---\nname: {skill_id}\ndescription: "{description}"\n---\n# {skill_id}\n',
        encoding='utf-8')
    return d


# ---------------------------------------------------------------- resolution


class TestResolveSourceEntry:

    def test_dot_relative_anchors_at_base(self, tmp_path):
        (tmp_path / 'docker-expert').mkdir()
        out = resolve_source_entry('./docker-expert', tmp_path)
        assert out == str((tmp_path / 'docker-expert').resolve())

    def test_parent_relative(self, tmp_path):
        target = tmp_path / 'shared'
        target.mkdir()
        base = tmp_path / 'proj'
        base.mkdir()
        assert resolve_source_entry('../shared', base) == str(target.resolve())

    def test_bare_name_anchors(self, tmp_path):
        out = resolve_source_entry('docker-expert', tmp_path)
        assert out == str((tmp_path / 'docker-expert').resolve())

    def test_absolute_passthrough(self, tmp_path):
        assert resolve_source_entry('/abs/path', tmp_path) == '/abs/path'

    def test_remote_schemes_passthrough(self, tmp_path):
        for raw in ('modelscope://org/pack', 'https://x/y', 'git://x/y',
                    '@owner/repo'):
            assert resolve_source_entry(raw, tmp_path) == raw

    def test_owner_repo_shorthand_stays_hub_id(self, tmp_path):
        assert resolve_source_entry('owner/repo', tmp_path) == 'owner/repo'

    def test_owner_repo_that_exists_locally_is_a_path(self, tmp_path):
        (tmp_path / 'owner' / 'repo').mkdir(parents=True)
        out = resolve_source_entry('owner/repo', tmp_path)
        assert out == str((tmp_path / 'owner' / 'repo').resolve())


class TestManagerAnchoring:

    @pytest.fixture
    def mgr(self, tmp_path):
        return SkillsConfigManager(global_dir=str(tmp_path / 'home'))

    def test_project_relative_source_anchors_at_project_root(
            self, mgr, tmp_path):
        proj = tmp_path / 'proj'
        (proj / '.ms_agent').mkdir(parents=True)
        (proj / 'docker-expert').mkdir()
        (proj / '.ms_agent' / 'skills.json').write_text(
            json.dumps({'sources': ['./docker-expert']}), encoding='utf-8')

        sources = mgr.list_sources(scope='project', project_path=str(proj))
        assert str((proj / 'docker-expert').resolve()) in sources

    def test_file_keeps_raw_relative_string_after_writes(self, mgr, tmp_path):
        proj = tmp_path / 'proj'
        (proj / '.ms_agent').mkdir(parents=True)
        cfg = proj / '.ms_agent' / 'skills.json'
        cfg.write_text(json.dumps({'sources': ['./docker-expert']}),
                       encoding='utf-8')

        mgr.set_skill_enabled('x', False, scope='project',
                              project_path=str(proj))
        data = json.loads(cfg.read_text(encoding='utf-8'))
        assert data['sources'] == ['./docker-expert']

    def test_remove_source_accepts_resolved_form(self, mgr, tmp_path):
        proj = tmp_path / 'proj'
        (proj / '.ms_agent').mkdir(parents=True)
        (proj / 'docker-expert').mkdir()
        cfg = proj / '.ms_agent' / 'skills.json'
        cfg.write_text(json.dumps({'sources': ['./docker-expert']}),
                       encoding='utf-8')

        mgr.remove_source(str((proj / 'docker-expert').resolve()),
                          scope='project', project_path=str(proj))
        data = json.loads(cfg.read_text(encoding='utf-8'))
        assert data['sources'] == []

    def test_implicit_global_tree_prepended(self, mgr, tmp_path):
        tree = tmp_path / 'home' / 'skills'
        _mk_skill(tree, 'dropped')
        sources = mgr.list_sources()
        assert sources and sources[0] == str(tree.resolve())

    def test_implicit_project_tree(self, mgr, tmp_path):
        proj = tmp_path / 'proj'
        tree = proj / '.ms_agent' / 'skills'
        _mk_skill(tree, 'proj-skill')
        sources = mgr.list_sources(scope='project', project_path=str(proj))
        assert str(tree.resolve()) in sources

    def test_no_tree_no_implicit_and_empty_shape_kept(self, mgr):
        assert mgr.load_global() == {}

    def test_merged_contains_both_trees(self, mgr, tmp_path):
        _mk_skill(tmp_path / 'home' / 'skills', 'g')
        proj = tmp_path / 'proj'
        _mk_skill(proj / '.ms_agent' / 'skills', 'p')
        merged = mgr.load_merged(project_path=str(proj))
        assert str((tmp_path / 'home' / 'skills').resolve()) in merged['sources']
        assert str((proj / '.ms_agent' / 'skills').resolve()) in merged['sources']


# ------------------------------------------------------------------- loader


class TestLoaderMarkerWalk:

    def test_finds_nested_skill_roots(self, tmp_path):
        _mk_skill(tmp_path, 'top')
        _mk_skill(tmp_path / 'webui', 'nested')
        _mk_skill(tmp_path / 'a' / 'b', 'deep')
        loaded = SkillLoader().load_skills(str(tmp_path))
        ids = {s.skill_id for s in loaded.values()}
        assert ids == {'top', 'nested', 'deep'}

    def test_skill_root_is_a_leaf(self, tmp_path):
        d = _mk_skill(tmp_path, 'outer')
        # A SKILL.md inside the skill's own support dir must not double-load.
        _mk_skill(d / 'references', 'inner')
        loaded = SkillLoader().load_skills(str(tmp_path))
        ids = {s.skill_id for s in loaded.values()}
        assert ids == {'outer'}

    def test_hidden_dirs_skipped(self, tmp_path):
        _mk_skill(tmp_path / '.hub', 'ghost')
        _mk_skill(tmp_path, 'real')
        loaded = SkillLoader().load_skills(str(tmp_path))
        ids = {s.skill_id for s in loaded.values()}
        assert ids == {'real'}


# ---------------------------------------------------- catalog resync + sync


def _skills_config(sources=(), disabled=()):
    return OmegaConf.create({
        'sources': [{'type': 'local', 'path': str(p)} for p in sources],
        'disabled': list(disabled),
    })


class TestCatalogResync:

    def test_resync_picks_up_new_source(self, tmp_path):
        s1 = _mk_skill(tmp_path, 'alpha')
        cfg = _skills_config([s1])
        cat = SkillCatalog(config=cfg)
        cat.load_from_config(cfg)
        assert cat.get_skill('alpha')

        s2 = _mk_skill(tmp_path / 'later', 'beta')
        cat.resync(_skills_config([s1, s2.parent]))
        assert cat.get_skill('alpha') and cat.get_skill('beta')

    def test_resync_drops_removed_skills(self, tmp_path):
        s1 = _mk_skill(tmp_path, 'alpha')
        cfg = _skills_config([s1])
        cat = SkillCatalog(config=cfg)
        cat.load_from_config(cfg)
        cat.resync(_skills_config([]))
        assert cat.get_skill('alpha') is None

    def test_duplicate_sources_load_once(self, tmp_path):
        _mk_skill(tmp_path, 'alpha')
        cfg = _skills_config([tmp_path, tmp_path])
        cat = SkillCatalog(config=cfg)
        cat.load_from_config(cfg)
        assert len(cat._sources) == len(
            {(s.type, s.path) for s in cat._sources})


class TestRuntimeSync:

    def test_known_clean_sync_skips_catalog_io(self, tmp_path, monkeypatch):
        s1 = _mk_skill(tmp_path, 'alpha')
        cfg = _skills_config([s1])
        cat = SkillCatalog(config=cfg)
        cat.load_from_config(cfg)
        rt = SkillRuntime(catalog=cat)
        calls = []
        original_resync = cat.resync

        def _resync(value):
            calls.append(value)
            return original_resync(value)

        monkeypatch.setattr(cat, 'resync', _resync)

        assert rt.sync_with_config(cfg, force=False) is False
        assert calls == []

        assert rt.sync_with_config(cfg) is False
        assert calls == [cfg]

    def test_sync_bumps_version_only_on_change(self, tmp_path):
        s1 = _mk_skill(tmp_path, 'alpha')
        cfg = _skills_config([s1])
        cat = SkillCatalog(config=cfg)
        cat.load_from_config(cfg)
        rt = SkillRuntime(catalog=cat)

        assert rt.sync_with_config(cfg) is False  # no change → no bump
        v0 = rt.version

        s2 = _mk_skill(tmp_path / 'more', 'beta')
        assert rt.sync_with_config(
            _skills_config([s1, s2.parent])) is True
        assert rt.version == v0 + 1
        assert rt.needs_refresh()

    def test_sync_sees_disabled_change(self, tmp_path):
        s1 = _mk_skill(tmp_path, 'alpha')
        cfg = _skills_config([s1])
        cat = SkillCatalog(config=cfg)
        cat.load_from_config(cfg)
        rt = SkillRuntime(catalog=cat)

        assert rt.sync_with_config(
            _skills_config([s1], disabled=['alpha'])) is True
        assert 'alpha' not in cat.get_enabled_skills()


# ------------------------------------------------- replayable managed merge


class TestReplayableMerge:

    def test_re_merge_replaces_managed_layer(self, tmp_path):
        home = tmp_path / 'home'
        proj = tmp_path / 'proj'
        proj.mkdir()
        mgr = SkillsConfigManager(global_dir=str(home))
        mgr.add_source(str(_mk_skill(tmp_path, 'one')), scope='project',
                       project_path=str(proj))

        cfg = OmegaConf.create({})
        merge_skills_into_config(cfg, str(home), str(proj))
        first = [e['path'] for e in cfg.skills.sources]
        assert str((tmp_path / 'one').resolve()) in first

        # Managed layer changes: source removed, another added, one disabled.
        mgr.remove_source(str((tmp_path / 'one').resolve()), scope='project',
                          project_path=str(proj))
        mgr.add_source(str(_mk_skill(tmp_path, 'two')), scope='project',
                       project_path=str(proj))
        mgr.set_skill_enabled('one', False, scope='project',
                              project_path=str(proj))

        merge_skills_into_config(cfg, str(home), str(proj))
        paths = [e['path'] for e in cfg.skills.sources]
        assert str((tmp_path / 'two').resolve()) in paths
        assert str((tmp_path / 'one').resolve()) not in paths
        assert list(cfg.skills.disabled) == ['one']

    def test_yaml_layer_survives_re_merge(self, tmp_path):
        home = tmp_path / 'home'
        proj = tmp_path / 'proj'
        proj.mkdir()
        mgr = SkillsConfigManager(global_dir=str(home))
        mgr.add_source(str(_mk_skill(tmp_path, 'managed-skill')),
                       scope='project', project_path=str(proj))

        cfg = OmegaConf.create({
            'skills': {
                'sources': [{'type': 'local', 'path': '/yaml/declared'}],
                'disabled': ['yaml-off'],
            }
        })
        merge_skills_into_config(cfg, str(home), str(proj))
        merge_skills_into_config(cfg, str(home), str(proj))  # replay

        paths = [e['path'] for e in cfg.skills.sources]
        assert paths.count('/yaml/declared') == 1
        assert 'yaml-off' in list(cfg.skills.disabled)

    def test_managed_disabled_clears_on_re_merge(self, tmp_path):
        home = tmp_path / 'home'
        proj = tmp_path / 'proj'
        proj.mkdir()
        mgr = SkillsConfigManager(global_dir=str(home))
        mgr.set_skill_enabled('s', False, scope='project',
                              project_path=str(proj))

        cfg = OmegaConf.create({})
        merge_skills_into_config(cfg, str(home), str(proj))
        assert 's' in list(cfg.skills.disabled)

        mgr.set_skill_enabled('s', True, scope='project',
                              project_path=str(proj))
        merge_skills_into_config(cfg, str(home), str(proj))
        assert 's' not in list(cfg.skills.disabled or [])
