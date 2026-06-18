import pytest
from ms_agent.project.workspace import FileEntry, Workspace


class TestWorkspace:
    @pytest.fixture
    def ws(self, tmp_path):
        root = tmp_path / 'workspace'
        root.mkdir()
        return Workspace(str(root))

    def test_list_empty_dir(self, ws):
        entries = ws.list_dir()
        assert entries == []

    def test_write_and_read_roundtrip(self, ws):
        ws.write_file('hello.txt', 'world')
        assert ws.read_file('hello.txt') == 'world'

    def test_write_creates_parent_dirs(self, ws):
        ws.write_file('sub/deep/file.txt', 'content')
        assert ws.read_file('sub/deep/file.txt') == 'content'

    def test_list_dir_shows_files_and_dirs(self, ws):
        ws.write_file('file.txt', 'data')
        (ws.root / 'subdir').mkdir()
        (ws.root / 'subdir' / 'child.txt').write_text('x')
        entries = ws.list_dir()
        names = {e.name for e in entries}
        assert names == {'file.txt', 'subdir'}
        file_entry = next(e for e in entries if e.name == 'file.txt')
        assert file_entry.type == 'file'
        assert file_entry.size > 0
        dir_entry = next(e for e in entries if e.name == 'subdir')
        assert dir_entry.type == 'dir'
        assert dir_entry.children_count == 1

    def test_list_hides_dotfiles(self, ws):
        ws.write_file('.hidden', 'secret')
        (ws.root / '.ms-agent').mkdir()
        ws.write_file('visible.txt', 'data')
        entries = ws.list_dir()
        names = {e.name for e in entries}
        assert '.hidden' not in names
        assert '.ms-agent' not in names
        assert 'visible.txt' in names

    def test_delete_file(self, ws):
        ws.write_file('to_delete.txt', 'bye')
        ws.delete('to_delete.txt')
        with pytest.raises(FileNotFoundError):
            ws.read_file('to_delete.txt')

    def test_delete_directory(self, ws):
        ws.write_file('dir/file.txt', 'content')
        ws.delete('dir')
        assert not (ws.root / 'dir').exists()

    def test_delete_nonexistent_raises(self, ws):
        with pytest.raises(FileNotFoundError):
            ws.delete('ghost.txt')

    def test_path_traversal_blocked(self, ws):
        with pytest.raises(PermissionError, match='traversal'):
            ws.read_file('../../etc/passwd')

    def test_path_traversal_via_dotdot(self, ws):
        with pytest.raises(PermissionError, match='traversal'):
            ws.write_file('../outside.txt', 'escape')

    def test_import_file(self, ws, tmp_path):
        source = tmp_path / 'external.txt'
        source.write_text('imported')
        ws.import_path(str(source))
        assert ws.read_file('external.txt') == 'imported'

    def test_import_directory(self, ws, tmp_path):
        source_dir = tmp_path / 'source_pkg'
        source_dir.mkdir()
        (source_dir / 'a.txt').write_text('aaa')
        (source_dir / 'b.txt').write_text('bbb')
        ws.import_path(str(source_dir))
        assert ws.read_file('source_pkg/a.txt') == 'aaa'
        assert ws.read_file('source_pkg/b.txt') == 'bbb'

    def test_import_nonexistent_raises(self, ws):
        with pytest.raises(FileNotFoundError):
            ws.import_path('/nonexistent/path')

    def test_read_nonexistent_file_raises(self, ws):
        with pytest.raises(FileNotFoundError):
            ws.read_file('no_such_file.txt')

    def test_list_nonexistent_dir_raises(self, ws):
        with pytest.raises(FileNotFoundError):
            ws.list_dir('no_such_dir')
