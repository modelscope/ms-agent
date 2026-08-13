"""Shared file-type classification for the workspace preview.

The frontend picks a preview by MIME type + whether the file is text-decodable:
text -> Monaco, image/video/audio -> media element, else -> unsupported. Two
quirks are handled centrally here so both the ms_agent and mock backends agree:

* ``mimetypes`` maps a few *source* extensions to non-text MIME types — most
  notably ``.ts`` -> ``video/mp2t`` — which would mis-flag TypeScript as video.
  ``guess_type`` overrides those so content_type stays trustworthy.
* Some extensions are *always* binary containers (archives, executables, media,
  fonts, office docs). Their bytes must never be shown as text even if they
  happen to decode — e.g. an archive that an older buggy upload corrupted into a
  lossy text blob. ``is_binary_ext`` flags them so callers skip inline content.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

# Source/text extensions that ``mimetypes`` resolves to a media MIME type.
# Overridden to a text type so media detection never trips on them.
_TEXT_TYPE_OVERRIDES = {
    ".ts": "text/typescript",
    ".mts": "text/typescript",
    ".cts": "text/typescript",
}

# Extensions whose contents are always binary and must not be inlined as text.
# Media is included so those files are served via .../raw and rendered, never
# poured into the code editor. (`.ts` is intentionally absent — in a code
# workspace it's TypeScript, not an MPEG transport stream.)
_BINARY_EXTS = {
    # archives / compression
    ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".tar", ".jar",
    ".war", ".whl", ".lz", ".lzma", ".cab", ".deb", ".rpm",
    # executables / libraries / bytecode
    ".exe", ".dll", ".so", ".dylib", ".bin", ".class", ".pyc", ".pyo",
    ".wasm", ".msi", ".apk", ".dex",
    # disk images
    ".iso", ".dmg", ".img",
    # documents (binary containers)
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt",
    ".ods", ".odp",
    # fonts
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # databases
    ".sqlite", ".db", ".mdb",
    # images
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tif",
    ".tiff", ".avif", ".heic", ".svg",
    # video
    ".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi", ".ogv", ".mpg",
    ".mpeg", ".flv", ".wmv",
    # audio
    ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".wma", ".opus",
    ".mid", ".midi",
}


def guess_type(name: str) -> str | None:
    """Best-effort MIME type, with source-extension overrides applied."""
    ext = Path(name).suffix.lower()
    if ext in _TEXT_TYPE_OVERRIDES:
        return _TEXT_TYPE_OVERRIDES[ext]
    return mimetypes.guess_type(name)[0]


def is_binary_ext(name: str) -> bool:
    """True for extensions that must never be previewed as editable text."""
    return Path(name).suffix.lower() in _BINARY_EXTS
