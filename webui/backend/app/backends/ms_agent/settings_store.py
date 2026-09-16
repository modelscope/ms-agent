"""Shared SDK settings transaction lock."""
from pathlib import Path

from ms_agent.utils.file_lock import file_lock

from app.backends.ms_agent.common import home


def settings_lock():
    return file_lock(Path(home()) / "settings.json")
