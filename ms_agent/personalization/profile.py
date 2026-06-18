from __future__ import annotations

import os
from pathlib import Path

PROFILE_FILENAME = 'profile.md'


class ProfileManager:
    """Manages the user profile file (~/.ms_agent/profile.md).

    The profile is a free-form Markdown file that gets injected as-is
    into the system prompt's User Profile section.
    """

    def __init__(self, global_dir: str = '~/.ms_agent') -> None:
        self._dir = Path(os.path.expanduser(global_dir))
        self._path = self._dir / PROFILE_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.is_file()

    def read(self) -> str:
        if not self._path.is_file():
            return ''
        return self._path.read_text(encoding='utf-8')

    def write(self, content: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix('.tmp')
        tmp.write_text(content, encoding='utf-8')
        tmp.rename(self._path)
