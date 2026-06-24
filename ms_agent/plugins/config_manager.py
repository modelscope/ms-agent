from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Literal

from ms_agent.plugins.types import PluginRecord

PluginScope = Literal['global', 'project', 'merged']
PLUGIN_FILE = 'plugins.json'
PROJECT_META_DIR = '.ms-agent'


class PluginConfigManager:
    """CRUD for global/project plugins.json with project override semantics."""

    def __init__(
        self,
        global_dir: str | Path = '~/.ms_agent',
        project_root: str | Path | None = None,
    ) -> None:
        self.global_root = Path(global_dir).expanduser()
        self.project_root = (
            Path(project_root).expanduser() if project_root else None
        )
        self._lock = Lock()

    @property
    def global_plugins_path(self) -> Path:
        return self.global_root / PLUGIN_FILE

    @property
    def project_plugins_path(self) -> Path:
        if self.project_root is None:
            raise ValueError('project_root is required for project scope')
        return self.project_root / PROJECT_META_DIR / PLUGIN_FILE

    @property
    def global_plugins_dir(self) -> Path:
        return self.global_root / 'plugins'

    @property
    def project_plugins_dir(self) -> Path:
        if self.project_root is None:
            raise ValueError('project_root is required for project scope')
        return self.project_root / PROJECT_META_DIR / 'plugins'

    @property
    def global_plugin_data_root(self) -> Path:
        return self.global_root / 'plugins' / 'data'

    def list(self, scope: PluginScope = 'merged') -> list[PluginRecord]:
        with self._lock:
            if scope == 'global':
                return self._load_scope('global')
            if scope == 'project':
                return self._load_scope('project')
            return merge_plugin_records(
                self._load_scope('global'),
                self._load_scope('project') if self.project_root else [],
            )

    def load_merged(self, project_path: str | None = None) -> list[PluginRecord]:
        if project_path and self.project_root is None:
            scoped = PluginConfigManager(self.global_root, project_path)
            return scoped.list('merged')
        return self.list('merged')

    def get(
        self,
        plugin_id: str,
        scope: PluginScope = 'merged',
    ) -> PluginRecord | None:
        for record in self.list(scope):
            if record.id == plugin_id:
                return record
        return None

    def upsert(
        self,
        record: PluginRecord,
        scope: Literal['global', 'project'] = 'global',
    ) -> None:
        with self._lock:
            records = self._load_scope(scope)
            replaced = False
            normalized = PluginRecord.from_dict(record.to_dict(), scope=scope)
            for idx, item in enumerate(records):
                if item.id == normalized.id:
                    records[idx] = normalized
                    replaced = True
                    break
            if not replaced:
                records.append(normalized)
            self._save_scope(scope, records)

    def set_enabled(
        self,
        plugin_id: str,
        enabled: bool,
        scope: Literal['global', 'project'] = 'global',
    ) -> None:
        with self._lock:
            records = self._load_scope(scope)
            for record in records:
                if record.id == plugin_id:
                    record.enabled = enabled
                    self._save_scope(scope, records)
                    return
            raise KeyError(f'Plugin not found in {scope} scope: {plugin_id}')

    def remove(
        self,
        plugin_id: str,
        scope: Literal['global', 'project'] = 'global',
    ) -> None:
        with self._lock:
            records = [r for r in self._load_scope(scope) if r.id != plugin_id]
            self._save_scope(scope, records)

    def _path_for_scope(self, scope: Literal['global', 'project']) -> Path:
        return self.global_plugins_path if scope == 'global' else self.project_plugins_path

    def _load_scope(self, scope: Literal['global', 'project']) -> list[PluginRecord]:
        path = self._path_for_scope(scope)
        data = self._read_json(path)
        raw_plugins = data.get('plugins', [])
        if not isinstance(raw_plugins, list):
            return []
        return [
            PluginRecord.from_dict(item, scope=scope)
            for item in raw_plugins
            if isinstance(item, dict) and item.get('id')
        ]

    def _save_scope(
        self,
        scope: Literal['global', 'project'],
        records: list[PluginRecord],
    ) -> None:
        path = self._path_for_scope(scope)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {'plugins': [record.to_dict() for record in records]}
        tmp = path.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        tmp.rename(path)

    @staticmethod
    def _read_json(path: Path) -> dict:
        if not path.is_file():
            return {}
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}


def merge_plugin_records(
    global_records: list[PluginRecord],
    project_records: list[PluginRecord],
) -> list[PluginRecord]:
    merged: dict[str, PluginRecord] = {}
    order: list[str] = []
    for record in global_records + project_records:
        if record.id not in order:
            order.append(record.id)
        merged[record.id] = record
    return [merged[plugin_id] for plugin_id in order]
