from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from ms_agent.personalization.types import PersonalizationConfig

SETTINGS_FILE = 'settings.json'
SECTION_KEY = 'personalization'


class PersonalizationSettings:
    """Reads/writes the personalization section of settings.json.

    Only touches the 'personalization' key -- other settings (llm, theme, etc.)
    are preserved as-is during save.
    """

    def __init__(self, global_dir: str = '~/.ms_agent') -> None:
        self._path = Path(os.path.expanduser(global_dir)) / SETTINGS_FILE

    def load(self) -> PersonalizationConfig:
        data = self._read_section()
        return PersonalizationConfig(
            global_instruction=data.get('global_instruction', ''),
            memory_enabled=data.get('memory_enabled', False),
            memory_backend=data.get('memory_backend'),
        )

    def save(self, config: PersonalizationConfig) -> None:
        full = self._read_full()
        full[SECTION_KEY] = {
            'global_instruction': config.global_instruction,
            'memory_enabled': config.memory_enabled,
            'memory_backend': config.memory_backend,
        }
        self._write_full(full)

    def _read_section(self) -> Dict[str, Any]:
        full = self._read_full()
        return full.get(SECTION_KEY, {})

    def _read_full(self) -> Dict[str, Any]:
        if not self._path.is_file():
            return {}
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_full(self, data: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.rename(self._path)
