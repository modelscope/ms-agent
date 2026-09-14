from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from ms_agent.personalization.types import PersonalizationConfig
from ms_agent.utils.atomic_file import atomic_write_json
from ms_agent.utils.file_lock import locked
from ms_agent.utils.json_store import read_json, json_transaction

SETTINGS_FILE = 'settings.json'
SECTION_KEY = 'personalization'


class PersonalizationSettings:
    """Reads/writes the personalization section of settings.json.

    Only touches the 'personalization' key -- other settings (llm, theme, etc.)
    are preserved as-is during save.
    """

    def __init__(self, global_dir: str | None = None) -> None:
        # Follows MS_AGENT_HOME by default (see ProfileManager for rationale).
        if global_dir is None:
            from ms_agent.project.paths import global_home
            self._path = global_home() / SETTINGS_FILE
        else:
            self._path = Path(os.path.expanduser(global_dir)) / SETTINGS_FILE

    def load(self) -> PersonalizationConfig:
        data = self._read_section()
        return PersonalizationConfig(
            global_instruction=data.get('global_instruction', ''),
            memory_enabled=data.get('memory_enabled', False),
            memory_backend=data.get('memory_backend'),
        )

    @locked(lambda self, *args, **kwargs: self._path)
    def save(self, config: PersonalizationConfig) -> None:
        full = self._read_full()
        full.setdefault(SECTION_KEY, {}).update({
            'global_instruction': config.global_instruction,
            'memory_enabled': config.memory_enabled,
            'memory_backend': config.memory_backend,
        })
        self._write_full(full)

    def update(self, **patch) -> PersonalizationConfig:
        unknown = patch.keys() - {'global_instruction', 'memory_enabled', 'memory_backend'}
        if unknown:
            raise ValueError('Unknown personalization field')
        with json_transaction(self._path) as data:
            data.setdefault(SECTION_KEY, {}).update(patch)
        return self.load()

    def _read_section(self) -> Dict[str, Any]:
        full = self._read_full()
        return full.get(SECTION_KEY, {})

    def _read_full(self) -> Dict[str, Any]:
        return read_json(self._path)

    def _write_full(self, data: Dict[str, Any]) -> None:
        atomic_write_json(self._path, data)
