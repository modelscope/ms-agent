"""Workspace adapter — SDK Workspace(project.path) with a flat recursive listing.

The frontend renders a tree from a flat list of relative paths, so we walk the
project dir (== output_dir) recursively. Framework internals are hidden, but
``.ms_agent`` itself is SHOWN so users can see and manage the project-scoped
state it holds (e.g. finer-grained permission files) — only its pure-machinery
subtrees (the ``snapshots`` git store, transient ``locks``) stay hidden, along
with the top-level ``sessions`` dir (session logs)."""
from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from app.backends.errors import BadRequest, Conflict, NotFound
from app.backends.ms_agent.common import pm
from app.core.filetypes import guess_type, is_binary_ext
from app.schemas.workspace import WorkspaceFile, WorkspaceFileCreate, WorkspaceFileUpdate

_HIDDEN_TOP = {"sessions"}

# Dot-directories that are framework internals and should never appear in the
# workspace listing. User-facing dot-dirs (like .github) are kept visible.
# NOTE: ``.ms_agent`` is intentionally NOT here — the project-scoped state it
# holds (user memory, and future finer-grained permission files) must be visible
# and hand-manageable, else such files could only ever be auto-added, never
# deleted. Its pure-machinery subtrees (``_HIDDEN_MSA_SUBDIRS``) and its
# machine-format memory dumps (``_HIDDEN_MSA_MEMORY_SUFFIXES``) are hidden
# separately.
# The bare-root ``.locks/.ms_agent_artifacts/.index/.temp`` are the SDK's LEGACY
# spots (see ms_agent/project/paths.py — all relocated under .ms_agent/) — kept
# here as a safety net for workspaces written by older SDKs / tools that still
# litter the workspace root.
_HIDDEN_DOT = {
    ".git", ".ms_agent_webui", ".venv", "__pycache__",
    ".locks", ".ms_agent_artifacts", ".index", ".temp",
}

# Subtrees directly under the (now visible) ``.ms_agent`` dir that are pure
# machinery and don't belong in the raw file tree at all:
#   - ``snapshots``: the git object store for workspace diffing (per-file
#     browsing/deletion would corrupt the snapshot history);
#   - ``locks``: transient file locks (deleting a live lock disrupts writes).
# (``memory`` is NOT here — it's shown, but its machine-format dumps are hidden
# by suffix; see ``_HIDDEN_MSA_MEMORY_SUFFIXES``.)
_HIDDEN_MSA_SUBDIRS = {"snapshots", "locks"}

# ``.ms_agent/memory/`` holds BOTH the user's memory (visible, hand-editable,
# reloaded by the SDK in-project — ``MEMORY.md``, mem0 store subdirs) AND the
# SDK's machine-format state dumps. The dumps are ``<tag>.yaml`` + ``<tag>.json``
# PAIRS written by utils.save_history for the main agent (``Agent-default``) and
# for EVERY agent-tool sub-agent (``worker-<uuid>``, … — the tag/prefix is
# arbitrary and grows as more agent tools run). They serialize message history +
# the resolved agent config (which INCLUDES secrets like API keys) and are
# rewritten each turn — SDK state, not user content. So keep memory/ visible but
# hide any ``.yaml``/``.json`` under it (matches every tag, current and future),
# leaving ``MEMORY.md`` and other human-readable memory files in view.
_HIDDEN_MSA_MEMORY_SUFFIXES = {".yaml", ".yml", ".json"}

# Upper bound on inline file content returned by GET (the editor preview only
# needs a readable slice; larger files stay listable but preview-truncated).
_MAX_PREVIEW_BYTES = 512 * 1024


def _project_path(pid: str) -> str:
    proj = pm().get(pid)
    if proj is None:
        raise NotFound("project not found")
    return proj.path


def _ws(pid: str):
    from ms_agent.project import Workspace

    return Workspace(_project_path(pid))


def _safe(ws, rel: str) -> Path:
    target = (ws.root / rel).resolve()
    try:
        target.relative_to(ws.root)
    except ValueError:
        raise BadRequest("path traversal blocked")
    return target


def _hidden(rel: Path) -> bool:
    parts = rel.parts
    if parts and parts[0] in _HIDDEN_TOP:
        return True
    # Only hide specific internal dot-dirs, not all dot-prefixed paths
    # (user-facing dirs like .github, .vscode, .env files are kept visible).
    if any(p in _HIDDEN_DOT for p in parts):
        return True
    # Under .ms_agent: hide the pure-machinery subtrees (snapshots/locks) whole,
    # and — inside the otherwise-visible memory/ — the SDK's <tag>.yaml/.json
    # state dumps (any tag), keeping user memory (MEMORY.md, …) in view.
    for i in range(len(parts) - 1):
        if parts[i] != ".ms_agent":
            continue
        if parts[i + 1] in _HIDDEN_MSA_SUBDIRS:
            return True
        if (parts[i + 1] == "memory"
                and rel.suffix.lower() in _HIDDEN_MSA_MEMORY_SUFFIXES):
            return True
    return False


def _entry(pid: str, root: Path, target: Path) -> WorkspaceFile:
    stat = target.stat()
    is_dir = target.is_dir()
    return WorkspaceFile(
        project_id=pid,
        path=str(target.relative_to(root)),
        kind="folder" if is_dir else "file",
        # A directory's own inode size is meaningless to a user, so it reports
        # the RECURSIVE total of the files it contains (see `_fill_dir_sizes` /
        # `_dir_size`); the raw stat size is only used for files.
        size=0 if is_dir else stat.st_size,
        updated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        preview=None,
        content_type=None if is_dir else guess_type(target.name),
    )


def _fill_dir_sizes(entries: list[WorkspaceFile]) -> None:
    """Roll each file's size up into every ancestor folder entry, in place.

    Single pass over the already-collected listing (no extra disk walk): a
    folder ends up reporting the total bytes of its whole subtree instead of a
    bare 0, which reads as "empty" next to its non-empty children.
    """
    folders = {e.path: e for e in entries if e.kind == "folder"}
    if not folders:
        return
    for e in entries:
        if e.kind == "folder":
            continue
        parent = PurePosixPath(e.path.replace("\\", "/")).parent
        while str(parent) not in (".", "/", ""):
            folder = folders.get(str(parent))
            if folder is not None:
                folder.size += e.size
            parent = parent.parent


def _dir_size(target: Path) -> int:
    """Recursive byte total of a directory (single-entry reads)."""
    total = 0
    for p in target.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def list_files(pid: str) -> list[WorkspaceFile]:
    ws = _ws(pid)
    root = ws.root
    out: list[WorkspaceFile] = []
    for target in root.rglob("*"):
        rel = target.relative_to(root)
        if _hidden(rel):
            continue
        out.append(_entry(pid, root, target))
    _fill_dir_sizes(out)
    out.sort(key=lambda f: f.path)
    return out


def create_file(pid: str, body: WorkspaceFileCreate) -> WorkspaceFile:
    ws = _ws(pid)
    target = _safe(ws, body.path)
    if target.exists():
        raise Conflict("file already exists")
    if body.kind == "folder":
        target.mkdir(parents=True, exist_ok=True)
    else:
        ws.write_file(body.path, body.content)
    return _entry(pid, ws.root, target)


def get_file(pid: str, path: str) -> WorkspaceFile:
    ws = _ws(pid)
    target = _safe(ws, path)
    # A path hidden from the listing must not be readable by direct path either
    # (else e.g. an .ms_agent/memory dump — which embeds API keys — would still
    # leak via a guessed URL). 404 so hidden files' existence isn't revealed.
    if _hidden(Path(path)):
        raise NotFound("file not found")
    if not target.exists():
        raise NotFound("file not found")
    entry = _entry(pid, ws.root, target)
    if target.is_dir():
        # Match the listing: a folder reports its subtree's total bytes.
        entry.size = _dir_size(target)
        return entry
    if target.is_file() and not is_binary_ext(path):
        # Known-binary extensions (archives, media, executables, …) are never
        # inlined as text — not even when their bytes happen to decode (e.g. an
        # archive an older buggy upload corrupted into a lossy text blob). The
        # frontend renders/downloads them via .../raw instead.
        try:
            text = ws.read_file(path)
            entry.preview = text[:200]
            # Cap the inline content so a huge file can't bloat the response;
            # the editor preview only needs a readable slice.
            entry.content = text[:_MAX_PREVIEW_BYTES]
        except (UnicodeDecodeError, OSError):
            entry.preview = None
            entry.content = None
    return entry


def update_file(pid: str, path: str, body: WorkspaceFileUpdate) -> WorkspaceFile:
    ws = _ws(pid)
    target = _safe(ws, path)
    if not target.is_file():
        raise NotFound("file not found")
    ws.write_file(path, body.content)
    return _entry(pid, ws.root, target)


def delete_file(pid: str, path: str) -> None:
    ws = _ws(pid)
    target = _safe(ws, path)
    if not target.exists():
        raise NotFound("file not found")
    ws.delete(path)


def move_file(pid: str, src: str, dst: str) -> WorkspaceFile:
    """Rename/move ``src`` to ``dst`` (both workspace-relative). Works for files
    and folders (children move along). Refuses to clobber an existing target or
    to move a folder into its own subtree."""
    ws = _ws(pid)
    s = _safe(ws, src)
    d = _safe(ws, dst)
    if not s.exists():
        raise NotFound("file not found")
    if d == s:
        return _entry(pid, ws.root, s)
    if d.exists():
        raise Conflict("target already exists")
    if s.is_dir():
        # Block moving a folder into itself or a descendant (would recurse).
        try:
            d.relative_to(s)
            raise BadRequest("cannot move a folder into itself")
        except ValueError:
            pass
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return _entry(pid, ws.root, d)


def _dedup_target(base: Path, data: bytes) -> Path:
    """Non-clobbering destination for a chat upload under ``user_files/``.

    The FIRST upload of a given browser file name keeps that name as-is. A
    LATER upload of the same name is compared byte-for-byte against that first
    file: identical bytes (re-upload of the same file) REUSE it (no new file);
    different bytes are stored timestamped (``<stem>-<epoch_ms><ext>``) so they
    never overwrite the first. A same-millisecond collision falls back to a
    counter.
    """
    if not base.exists():
        return base
    try:
        if base.read_bytes() == data:
            return base  # identical re-upload of the first file → reuse
    except OSError:
        pass
    ts = int(time.time() * 1000)
    stem, suffix, parent = base.stem, base.suffix, base.parent
    cand = parent / f"{stem}-{ts}{suffix}"
    i = 1
    while cand.exists():
        cand = parent / f"{stem}-{ts}-{i}{suffix}"
        i += 1
    return cand


def save_upload(pid: str, rel: str, data: bytes, dedup: bool = False) -> WorkspaceFile:
    """Persist a raw uploaded file (binary-safe) under the workspace.

    Uploads write bytes directly instead of going through the text-only
    ``write_file`` so images/archives/etc. aren't corrupted by UTF-8 coercion.
    By default a same-path file is overwritten (explicit-path uploads / import).
    With ``dedup`` (chat attachments landing flat in ``user_files/``) the first
    upload of a name keeps it; a later same-named upload reuses that first file
    when the bytes are identical, else is timestamped
    (``<stem>-<epoch_ms><ext>``), so the returned ``path`` is the real location
    the caller must use for links + agent references.
    """
    ws = _ws(pid)
    if not rel:
        raise BadRequest("missing file path")
    base = _safe(ws, rel)
    if base.is_dir():
        raise Conflict("a folder already exists at this path")
    target = _dedup_target(base, data) if dedup else base
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return _entry(pid, ws.root, target)


def raw_file(pid: str, path: str) -> tuple[Path, str]:
    """Resolve an existing file to (path, mime) for raw byte serving."""
    ws = _ws(pid)
    target = _safe(ws, path)
    # Same guard as get_file: never serve the bytes of a listing-hidden file
    # (e.g. an .ms_agent/memory state dump with embedded secrets) by direct path.
    if _hidden(Path(path)):
        raise NotFound("file not found")
    if not target.is_file():
        raise NotFound("file not found")
    return target, guess_type(target.name) or "application/octet-stream"
