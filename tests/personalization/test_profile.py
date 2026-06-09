import pytest

from ms_agent.personalization.profile import ProfileManager


class TestProfileManager:

    @pytest.fixture
    def profile_dir(self, tmp_path):
        return tmp_path / '.ms_agent'

    @pytest.fixture
    def manager(self, profile_dir):
        return ProfileManager(global_dir=str(profile_dir))

    def test_read_missing_profile_returns_empty(self, manager):
        assert manager.read() == ''

    def test_exists_false_when_missing(self, manager):
        assert manager.exists() is False

    def test_write_creates_parent_dirs(self, tmp_path):
        deep_dir = tmp_path / 'a' / 'b' / 'c'
        mgr = ProfileManager(global_dir=str(deep_dir))
        mgr.write('hello')
        assert mgr.read() == 'hello'
        assert deep_dir.exists()

    def test_roundtrip(self, manager):
        content = '# About Me\n\nI am a Python developer.\n'
        manager.write(content)
        assert manager.read() == content

    def test_exists_true_after_write(self, manager):
        manager.write('test')
        assert manager.exists() is True

    def test_write_overwrites(self, manager):
        manager.write('first')
        manager.write('second')
        assert manager.read() == 'second'

    def test_path_property(self, profile_dir, manager):
        assert manager.path == profile_dir / 'profile.md'

    def test_read_preserves_unicode(self, manager):
        content = '# 个人简介\n\n我是后端工程师。'
        manager.write(content)
        assert manager.read() == content

    def test_write_atomic_no_partial_file(self, manager):
        manager.write('complete content')
        tmp_file = manager.path.with_suffix('.tmp')
        assert not tmp_file.exists()
