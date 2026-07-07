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
