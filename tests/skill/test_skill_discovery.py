import hashlib
import os
from pathlib import Path

from ms_agent.skill.loader import SkillLoader
from ms_agent.skill.schema import SkillSchemaParser


def _make_skill(root: Path, name: str, description: str = 'description'):
    skill = root / name
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text(
        f'---\nname: {name}\ndescription: {description}\n---\nbody',
        encoding='utf-8',
    )
    return skill


def _legacy_signature(root: Path) -> str:
    digest = hashlib.sha256()
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if not name.startswith('.'))
        for name in sorted(name for name in files if not name.startswith('.')):
            path = Path(current) / name
            try:
                file_stat = path.stat()
            except OSError:
                continue
            relative = path.relative_to(root).as_posix()
            digest.update(
                f'{relative}|{file_stat.st_mtime_ns}|{file_stat.st_size}\n'.
                encode())
    return digest.hexdigest()[:16]


def test_discovery_reads_metadata_without_support_tree_walk(
        tmp_path, monkeypatch):
    skill = _make_skill(tmp_path, 'alpha')
    (skill / 'references').mkdir()
    (skill / 'references' / 'large.md').write_text('payload', encoding='utf-8')

    def _unexpected_rglob(*args, **kwargs):
        raise AssertionError(
            'metadata discovery must not traverse support files')

    monkeypatch.setattr(Path, 'rglob', _unexpected_rglob)
    discovered = SkillLoader().discover_skills(str(tmp_path))

    assert list(discovered) == ['alpha@latest']
    descriptor = discovered['alpha@latest']
    assert descriptor.skill_id == 'alpha'
    assert descriptor.name == 'alpha'
    assert descriptor.skill_path == skill.resolve()


def test_discovery_matches_loader_marker_walk_rules(tmp_path):
    _make_skill(tmp_path, 'top')
    outer = _make_skill(tmp_path / 'group', 'outer')
    _make_skill(outer / 'references', 'nested-inside-skill')
    _make_skill(tmp_path / '.hidden', 'hidden')

    discovered = SkillLoader().discover_skills(str(tmp_path))

    assert {item.skill_id for item in discovered.values()} == {'top', 'outer'}


def test_discovery_caches_unchanged_skill_markdown(tmp_path, monkeypatch):
    _make_skill(tmp_path, 'alpha')
    loader = SkillLoader()
    original_read_text = Path.read_text
    reads = []

    def _read_text(path, *args, **kwargs):
        reads.append(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', _read_text)
    assert loader.discover_skills(str(tmp_path))
    assert loader.discover_skills(str(tmp_path))

    assert reads == [tmp_path / 'alpha' / 'SKILL.md']


def test_full_parse_reuses_exact_legacy_files_signature(tmp_path):
    skill = _make_skill(tmp_path, 'alpha')
    (skill / 'z.txt').write_text('z', encoding='utf-8')
    (skill / 'a').mkdir()
    (skill / 'a' / 'b.txt').write_text('b', encoding='utf-8')
    (skill / '.hidden').mkdir()
    (skill / '.hidden' / 'ignored.txt').write_text('ignored', encoding='utf-8')
    (skill / '__pycache__').mkdir()
    (skill / '__pycache__' / 'tracked.pyc').write_bytes(b'bytecode')

    schema = SkillSchemaParser.parse_skill_directory(skill)

    assert schema is not None
    assert schema._files_signature == _legacy_signature(skill)


def test_signature_changes_for_visible_resource_but_not_hidden_file(tmp_path):
    skill = _make_skill(tmp_path, 'alpha')
    resource = skill / 'reference.txt'
    resource.write_text('before', encoding='utf-8')
    first = SkillSchemaParser.parse_skill_directory(skill)._files_signature

    resource.write_text('after with different size', encoding='utf-8')
    second = SkillSchemaParser.parse_skill_directory(skill)._files_signature
    assert second != first

    (skill / '.transient').write_text('ignored', encoding='utf-8')
    third = SkillSchemaParser.parse_skill_directory(skill)._files_signature
    assert third == second
