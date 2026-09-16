from __future__ import annotations

import os
from pathlib import Path

from ms_agent.utils.atomic_file import atomic_write_text
from ms_agent.utils.file_lock import locked

PROFILE_FILENAME = 'profile.md'


class ProfileManager:
    """Manages the user profile file (~/.ms_agent/profile.md).

    The profile is a free-form Markdown file that gets injected as-is
    into the system prompt's User Profile section.
    """

    def __init__(self, global_dir: str | None = None) -> None:
        # Default follows the runtime home (honors MS_AGENT_HOME) instead of a
        # hard-coded '~/.ms_agent' — a no-arg ProfileManager used to read a
        # different file than a UI writing to a redirected home (dead link).
        if global_dir is None:
            from ms_agent.project.paths import global_home
            self._dir = global_home()
        else:
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

    @locked(lambda self, content: self._dir / '.prompt-files')
    def write(self, content: str) -> None:
        atomic_write_text(self._path, content)
