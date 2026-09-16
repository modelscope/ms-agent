"""Keep persisted WebUI tool defaults complete after external config writes."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ms_agent.config.tool_settings import merge_tool_settings

from app.backends.errors import BadRequest, Conflict
from app.backends.ms_agent.defaults import DEFAULT_TOOLS, RETIRED_TOOLS
from ms_agent.utils.file_lock import file_lock


def normalize_tool_settings(data: dict) -> dict:
    """Fill missing defaults; preserve explicit switches and tool selections.

    Only global tool settings belong here. Project overrides, session paths,
    model credentials and template merging are handled by their own callers.
    """
    if not isinstance(data, dict):
        raise ValueError("settings.json must contain an object")
    tools = merge_tool_settings(DEFAULT_TOOLS, data.get("tools", {}))
    for name in RETIRED_TOOLS:
        tools.pop(name, None)
    return {**data, "tools": tools}


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def ensure_tool_settings(home_dir: str | Path) -> dict:
    """Read current settings, validate and atomically save missing tool fields.

    External import services can replace settings.json without calling the SDK.
    Never reuse a cached pre-import configuration or restore deleted credentials.
    Recheck the source before replacement to avoid an observed external edit.
    External writers must use the same lock for a strict no-lost-update guarantee.
    """
    path = Path(home_dir) / "settings.json"
    with file_lock(path):
        for _ in range(3):
            before = _read(path)
            try:
                data = json.loads(before) if before is not None else {}
                normalized = normalize_tool_settings(data)
            except (UnicodeDecodeError, ValueError) as exc:
                # The message names fields, never raw file contents or keys.
                detail = ("settings.json must contain valid JSON"
                          if isinstance(exc, (UnicodeDecodeError, json.JSONDecodeError))
                          else str(exc))
                raise BadRequest(f"Invalid WebUI settings: {detail}") from exc
            if normalized == data:
                return data

            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".settings-", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(normalized, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                if _read(path) != before:
                    continue
                os.replace(temporary, path)
                return normalized
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    raise Conflict("settings.json changed during normalization; please retry.")
