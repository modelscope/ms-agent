"""History reconstruction: attachment block -> structured user files."""
from types import SimpleNamespace

from app.backends.ms_agent.sessions import (
    _attached_files,
    _reconstruct,
    _split_attached,
)


def _project(path):
    return SimpleNamespace(id="p1", path=str(path))


def test_split_attached_none():
    assert _split_attached("just text") == ("just text", [])


def test_split_attached_text_and_paths():
    content = (
        "summarize this\n\n"
        "[Attached files] (paths are relative to the project workspace root; "
        "use the file tools to read them):\n"
        "- user_files/a.txt\n"
        "- user_files/b.png\n"
    )
    text, paths = _split_attached(content)
    assert text == "summarize this"
    assert paths == ["user_files/a.txt", "user_files/b.png"]


def test_split_attached_files_only():
    content = (
        "[Attached files] (paths are relative to the project workspace root; "
        "use the file tools to read them):\n"
        "- user_files/only.pdf\n"
    )
    text, paths = _split_attached(content)
    assert text == ""
    assert paths == ["user_files/only.pdf"]


def test_attached_files_exists_flag_and_kind(tmp_path):
    (tmp_path / "user_files").mkdir()
    (tmp_path / "user_files" / "here.png").write_bytes(b"x")
    files = _attached_files(
        _project(tmp_path), ["user_files/here.png", "user_files/gone.txt"]
    )
    here, gone = files
    assert here.name == "here.png" and here.exists is True and here.type == "image"
    assert here.size == 1  # one byte written
    assert here.url == "/api/projects/p1/workspace/files/user_files/here.png/raw"
    assert gone.name == "gone.txt" and gone.exists is False and gone.type == "file"
    assert gone.size is None


def test_reconstruct_user_message_strips_block(tmp_path):
    (tmp_path / "user_files").mkdir()
    (tmp_path / "user_files" / "a.txt").write_text("hi")
    rows = [
        {
            "seq": 0,
            "role": "user",
            "content": (
                "1\n\n[Attached files] (paths are relative to the project "
                "workspace root; use the file tools to read them):\n"
                "- user_files/a.txt\n"
            ),
        }
    ]
    msgs = _reconstruct(rows, _project(tmp_path))
    assert len(msgs) == 1
    m = msgs[0]
    assert m.role == "user"
    assert m.content == "1"  # attachment block stripped from display text
    assert len(m.files) == 1 and m.files[0].path == "user_files/a.txt"
    assert m.files[0].exists is True


def test_reconstruct_plain_user_message_unchanged(tmp_path):
    rows = [{"seq": 0, "role": "user", "content": "hello world"}]
    msgs = _reconstruct(rows, _project(tmp_path))
    assert msgs[0].content == "hello world"
    assert msgs[0].files == []


def _file_step(msgs, kind):
    for m in msgs:
        for p in m.parts:
            if p.kind == "step" and p.step and p.step.kind == kind:
                return p.step
    return None


def test_reconstruct_file_read_step_exists_flag(tmp_path):
    """A file_read step is tagged with whether the workspace file still exists,
    so the frontend can open it (present) or show a deleted card (gone)."""
    (tmp_path / "kept.md").write_text("# hi")
    rows = [
        {
            "seq": 0,
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "file_system---read_file",
                    "arguments": '{"path": "kept.md"}',
                },
                {
                    "id": "c2",
                    "tool_name": "file_system---write_file",
                    "arguments": '{"path": "gone.md"}',
                },
            ],
        }
    ]
    msgs = _reconstruct(rows, _project(tmp_path))
    read = _file_step(msgs, "file_read")
    write = _file_step(msgs, "file_write")
    assert read is not None and read.meta["path"] == "kept.md"
    assert read.meta["exists"] is True
    assert write is not None and write.meta["path"] == "gone.md"
    assert write.meta["exists"] is False


def test_reconstruct_file_step_no_project_omits_exists(tmp_path):
    """Without a project (legacy call), file steps don't carry an exists flag."""
    rows = [
        {
            "seq": 0,
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "file_system---read_file",
                    "arguments": '{"path": "kept.md"}',
                }
            ],
        }
    ]
    read = _file_step(_reconstruct(rows), "file_read")
    assert read is not None and "exists" not in read.meta
