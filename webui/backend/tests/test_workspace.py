"""Workspace adapter: binary-safe upload + type-aware read (ms_agent backend).

Guards the upload regression where files were persisted empty and binary
content was corrupted by UTF-8 coercion. Uses the real on-disk SDK workspace
(conftest isolates MS_AGENT_HOME), no LLM/network needed.
"""
import re

from app.backends.ms_agent import workspace
from app.backends.ms_agent.bootstrap import bootstrap
from app.backends.ms_agent.projects import create_project
from app.schemas.project import ProjectCreate

# 1x1 transparent PNG — real binary bytes that are NOT valid UTF-8.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


def _new_project(name: str) -> str:
    bootstrap()
    return create_project(ProjectCreate(name=name)).id


def test_upload_text_roundtrips_content_and_type():
    pid = _new_project("ws-text")
    body = "hello\nworld\n"
    workspace.save_upload(pid, "notes/readme.md", body.encode("utf-8"))

    got = workspace.get_file(pid, "notes/readme.md")
    assert got.content == body            # full text is returned for editing
    assert got.size == len(body.encode())
    assert got.content_type == "text/markdown"


def test_upload_binary_is_not_corrupted_and_has_no_text_content():
    pid = _new_project("ws-binary")
    workspace.save_upload(pid, "logo.png", _PNG)

    got = workspace.get_file(pid, "logo.png")
    # Undecodable -> the editor must not try to render it as text.
    assert got.content is None
    assert got.content_type == "image/png"

    # Raw bytes survive the round-trip verbatim (no UTF-8 mangling).
    target, mime = workspace.raw_file(pid, "logo.png")
    assert mime == "image/png"
    assert target.read_bytes() == _PNG


def test_upload_overwrites_same_path():
    pid = _new_project("ws-overwrite")
    workspace.save_upload(pid, "a.txt", b"one")
    workspace.save_upload(pid, "a.txt", b"two")
    assert workspace.get_file(pid, "a.txt").content == "two"


def test_dedup_upload_keeps_first_name_timestamps_rest():
    pid = _new_project("ws-dedup")
    first = workspace.save_upload(pid, "user_files/a.txt", b"one", dedup=True)
    second = workspace.save_upload(pid, "user_files/a.txt", b"two", dedup=True)
    # First upload keeps the plain name; a later same-named upload with
    # DIFFERENT bytes is timestamped (<stem>-<ms>.ext) so it never clobbers it.
    assert first.path == "user_files/a.txt"
    assert re.fullmatch(r"user_files/a-\d+(?:-\d+)?\.txt", second.path)
    assert first.path != second.path
    assert workspace.get_file(pid, "user_files/a.txt").content == "one"
    assert workspace.get_file(pid, second.path).content == "two"


def test_dedup_upload_reuses_identical_bytes():
    pid = _new_project("ws-dedup-same")
    first = workspace.save_upload(pid, "user_files/a.txt", b"same", dedup=True)
    second = workspace.save_upload(pid, "user_files/a.txt", b"same", dedup=True)
    # Re-uploading the exact same file reuses the first path (no new file).
    assert first.path == second.path == "user_files/a.txt"


def test_listing_carries_content_type():
    pid = _new_project("ws-list")
    workspace.save_upload(pid, "data.json", b"{}")
    files = {f.path: f for f in workspace.list_files(pid)}
    assert files["data.json"].content_type == "application/json"


def test_archive_is_never_inlined_as_text_even_if_decodable():
    # Regression: an archive whose bytes happen to be valid UTF-8 (e.g. one
    # corrupted into a lossy text blob by an older buggy upload) must still be
    # treated as binary, not poured into the editor.
    pid = _new_project("ws-archive")
    workspace.save_upload(pid, "archive.zip", b"PK totally decodable text")
    got = workspace.get_file(pid, "archive.zip")
    assert got.content is None
    assert got.content_type == "application/zip"


def test_typescript_is_text_not_video():
    # mimetypes maps `.ts` -> video/mp2t; the override keeps it text so the
    # frontend renders it in Monaco, not as a video element.
    pid = _new_project("ws-ts")
    workspace.save_upload(pid, "index.ts", b"export const x = 1\n")
    got = workspace.get_file(pid, "index.ts")
    assert got.content == "export const x = 1\n"
    assert got.content_type == "text/typescript"


def test_move_renames_file_in_place():
    pid = _new_project("ws-mv-rename")
    workspace.save_upload(pid, "a.txt", b"hi")
    moved = workspace.move_file(pid, "a.txt", "b.txt")
    assert moved.path == "b.txt"
    assert workspace.get_file(pid, "b.txt").content == "hi"
    paths = {f.path for f in workspace.list_files(pid)}
    assert "a.txt" not in paths and "b.txt" in paths


def test_move_into_folder_carries_children():
    pid = _new_project("ws-mv-folder")
    workspace.save_upload(pid, "src/one.txt", b"1")
    workspace.save_upload(pid, "src/sub/two.txt", b"2")
    workspace.move_file(pid, "src", "dst")
    paths = {f.path for f in workspace.list_files(pid)}
    assert "dst/one.txt" in paths and "dst/sub/two.txt" in paths
    assert not any(p.startswith("src") for p in paths)


def test_move_rejects_existing_target():
    import pytest
    from app.backends.errors import Conflict

    pid = _new_project("ws-mv-conflict")
    workspace.save_upload(pid, "a.txt", b"a")
    workspace.save_upload(pid, "b.txt", b"b")
    with pytest.raises(Conflict):
        workspace.move_file(pid, "a.txt", "b.txt")


def test_move_rejects_folder_into_own_subtree():
    import pytest
    from app.backends.errors import BadRequest

    pid = _new_project("ws-mv-self")
    workspace.save_upload(pid, "dir/f.txt", b"x")
    with pytest.raises(BadRequest):
        workspace.move_file(pid, "dir", "dir/child")


def test_listing_hides_framework_internal_dot_dirs():
    """Framework-internal dot dirs never surface in the listing — including the
    LEGACY workspace-root spots older SDK tools littered (.locks etc.); a
    user-facing dot dir like .github stays visible."""
    import pathlib

    pid = _new_project("ws-hidden")
    root = pathlib.Path(workspace._project_path(pid))
    for d in (".locks", ".ms_agent_artifacts", ".index", ".temp"):
        (root / d).mkdir(parents=True, exist_ok=True)
        (root / d / "x.lock").write_text("x")
    (root / ".github").mkdir(exist_ok=True)
    (root / ".github" / "ci.yml").write_text("on: push")
    (root / "kept.txt").write_text("k")

    paths = {f.path for f in workspace.list_files(pid)}
    assert "kept.txt" in paths
    assert ".github" in paths or ".github/ci.yml" in paths  # user dot-dir kept
    hidden = {".locks", ".ms_agent_artifacts", ".index", ".temp"}
    assert not any(p.split("/")[0] in hidden for p in paths)


def test_listing_shows_ms_agent_and_user_memory_but_hides_dumps():
    """`.ms_agent` is visible (future permission files stay hand-manageable);
    its pure-machinery subtrees (snapshots git store, transient locks) are
    hidden wholesale; and under the VISIBLE memory/ dir the user's own memory
    (MEMORY.md) shows while the SDK's <tag>.yaml/.json state dumps — the main
    Agent-default AND agent-tool workers, any tag — stay hidden."""
    import pathlib

    pid = _new_project("ws-msa")
    root = pathlib.Path(workspace._project_path(pid))
    # Visible: .ms_agent + a (future) permission json.
    (root / ".ms_agent").mkdir(parents=True, exist_ok=True)
    (root / ".ms_agent" / "permissions.json").write_text("{}")
    # Machinery hidden wholesale.
    (root / ".ms_agent" / "snapshots" / "objects").mkdir(parents=True, exist_ok=True)
    (root / ".ms_agent" / "snapshots" / "objects" / "ab12").write_text("blob")
    (root / ".ms_agent" / "locks").mkdir(parents=True, exist_ok=True)
    (root / ".ms_agent" / "locks" / "plan.lock").write_text("x")
    # memory/: user memory VISIBLE, save_history dumps (any tag) HIDDEN.
    (root / ".ms_agent" / "memory").mkdir(parents=True, exist_ok=True)
    (root / ".ms_agent" / "memory" / "MEMORY.md").write_text("- remembered")
    (root / ".ms_agent" / "memory" / "Agent-default.yaml").write_text("llm: {}")
    (root / ".ms_agent" / "memory" / "Agent-default.json").write_text("[]")
    (root / ".ms_agent" / "memory" / "worker-a1b2c3d4.yaml").write_text("llm: {}")
    (root / ".ms_agent" / "memory" / "worker-a1b2c3d4.json").write_text("[]")

    paths = {f.path for f in workspace.list_files(pid)}
    assert ".ms_agent" in paths  # the dir itself surfaces
    assert ".ms_agent/permissions.json" in paths  # manageable state visible
    assert ".ms_agent/memory/MEMORY.md" in paths  # user memory visible
    # Machinery hidden.
    assert not any(
        p.startswith(".ms_agent/snapshots") or p.startswith(".ms_agent/locks")
        for p in paths
    )
    # save_history dumps (any tag) hidden, but the memory dir itself is fine.
    assert not any(
        p.endswith(".yaml") or p.endswith(".json")
        for p in paths
        if p.startswith(".ms_agent/memory/")
    )


def test_by_path_read_of_hidden_file_is_404():
    """A listing-hidden file (e.g. an .ms_agent/memory state dump, which embeds
    API keys) must not be readable by direct path via get_file / raw_file —
    otherwise hiding it from the tree would be cosmetic."""
    import pathlib

    from app.backends.errors import NotFound

    pid = _new_project("ws-bypath")
    root = pathlib.Path(workspace._project_path(pid))
    (root / ".ms_agent" / "memory").mkdir(parents=True, exist_ok=True)
    (root / ".ms_agent" / "memory" / "Agent-default.yaml").write_text(
        "llm:\n  deepseek_api_key: sk-secret\n"
    )
    (root / "shown.txt").write_text("ok")

    dump = ".ms_agent/memory/Agent-default.yaml"
    for fn in (workspace.get_file, workspace.raw_file):
        try:
            fn(pid, dump)
            assert False, f"{fn.__name__} leaked a hidden file"
        except NotFound:
            pass
    # A normal (visible) file still reads fine.
    assert workspace.get_file(pid, "shown.txt").content == "ok"
