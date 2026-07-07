# Copyright (c) ModelScope Contributors. All rights reserved.
import io
import zipfile

import pytest

from ms_agent.project.workspace import Workspace


def test_write_read_bytes(tmp_path):
    ws = Workspace(str(tmp_path / 'ws'))
    ws.write_bytes('sub/data.bin', b'\x00\x01\x02')
    assert ws.read_bytes('sub/data.bin') == b'\x00\x01\x02'


def test_save_upload_stream_and_bytes(tmp_path):
    ws = Workspace(str(tmp_path / 'ws'))
    rel = ws.save_upload('report.pdf', io.BytesIO(b'PDFDATA'), subdir='uploads')
    assert ws.read_bytes(rel) == b'PDFDATA'
    # basename-only: a filename with dir components is stripped
    rel2 = ws.save_upload('../../evil.txt', b'x')
    assert 'evil.txt' in rel2 and '..' not in rel2


def test_save_upload_traversal_blocked(tmp_path):
    ws = Workspace(str(tmp_path / 'ws'))
    with pytest.raises(PermissionError):
        ws.save_upload('ok.txt', b'x', subdir='../../etc')


def test_zip_download(tmp_path):
    ws = Workspace(str(tmp_path / 'ws'))
    ws.write_file('a.txt', 'A')
    ws.write_file('d/b.txt', 'B')
    data = ws.zip_download('.')
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
    assert any(n.endswith('a.txt') for n in names)
    assert any(n.endswith('b.txt') for n in names)


def test_zip_download_skips_external_symlink(tmp_path):
    # A symlink planted in the workspace pointing outside must NOT be followed
    # and packaged (arbitrary-file-read / info disclosure via zip_download).
    secret = tmp_path / 'secret.txt'
    secret.write_text('TOP-SECRET')
    ws_dir = tmp_path / 'ws'
    ws = Workspace(str(ws_dir))
    ws.write_file('safe.txt', 'ok')
    (ws_dir / 'leak.txt').symlink_to(secret)  # escapes the workspace

    data = ws.zip_download('.')
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        blob = b''.join(zf.read(n) for n in names)
    assert any(n.endswith('safe.txt') for n in names)
    assert not any('leak' in n for n in names)   # symlink entry skipped
    assert b'TOP-SECRET' not in blob              # external content not leaked
