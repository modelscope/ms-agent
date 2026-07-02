# Copyright (c) ModelScope Contributors. All rights reserved.
"""Persistent CRUD for global and project MCP server definitions."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Literal, Optional

from ms_agent.config.env import Env
from ms_agent.config.mcp_schema import normalize_mcp_server_entry

MCPScope = Literal['global', 'project', 'merged']


class MCPConfigManager:
    """Global / project two-level MCP configuration persistence."""

    def __init__(
        self,
        global_root: Path | str,
        project_root: Path | str | None = None,
    ):
        self.global_root = Path(global_root).expanduser()
        self.project_root = (
            Path(project_root).expanduser() if project_root else None
        )
        self._lock = Lock()

    # ── paths ──────────────────────────────────────────────────────────

    @property
    def global_settings_path(self) -> Path:
        return self.global_root / 'settings.json'

    @property
    def global_mcp_path(self) -> Path:
        return self.global_root / 'mcp.json'

    @property
    def project_mcp_path(self) -> Path:
        if self.project_root is None:
            raise ValueError('project_root is required for project scope')
        return self.project_root / '.ms-agent' / 'mcp.json'

    def _ensure_dir(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    # ── IO ─────────────────────────────────────────────────────────────

    def _read_json(self, path: Path) -> Dict[str, Any]:
        if not path.is_file():
            return {}
        with open(path, encoding='utf-8') as f:
            return json.load(f)

    def _write_json(self, path: Path, data: Dict[str, Any]) -> None:
        self._ensure_dir(path)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_scope_raw(self, scope: Literal['global', 'project']) -> Dict[str, Dict[str, Any]]:
        if scope == 'global':
            servers: Dict[str, Dict[str, Any]] = {}
            settings = self._read_json(self.global_settings_path)
            if isinstance(settings.get('mcp_servers'), dict):
                servers.update(settings['mcp_servers'])
            mcp_file = self._read_json(self.global_mcp_path)
            file_servers = mcp_file.get('mcpServers', mcp_file)
            if isinstance(file_servers, dict):
                for name, entry in file_servers.items():
                    servers.setdefault(name, entry)
            return servers

        assert self.project_root is not None
        mcp_file = self._read_json(self.project_mcp_path)
        file_servers = mcp_file.get('mcpServers', mcp_file)
        return dict(file_servers) if isinstance(file_servers, dict) else {}

    def _save_scope_raw(
        self,
        scope: Literal['global', 'project'],
        servers: Dict[str, Dict[str, Any]],
    ) -> None:
        if scope == 'global':
            # Keep settings.json mcp_servers in sync for WebUI compatibility.
            settings = self._read_json(self.global_settings_path)
            if not settings:
                settings = {}
            settings['mcp_servers'] = copy.deepcopy(servers)
            self._write_json(self.global_settings_path, settings)
            self._write_json(self.global_mcp_path, {'mcpServers': servers})
            return

        self._write_json(self.project_mcp_path, {'mcpServers': servers})

    def _normalize_scope(
        self,
        servers: Dict[str, Dict[str, Any]],
        *,
        source: Literal['global', 'project'],
    ) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for name, entry in servers.items():
            normalized = normalize_mcp_server_entry(entry, source=source)
            if normalized is not None:
                result[name] = normalized
        return result

    # ── CRUD ───────────────────────────────────────────────────────────

    def list(self, scope: MCPScope = 'merged') -> Dict[str, Dict[str, Any]]:
        with self._lock:
            if scope == 'global':
                return self._normalize_scope(
                    self._load_scope_raw('global'), source='global')
            if scope == 'project':
                return self._normalize_scope(
                    self._load_scope_raw('project'), source='project')
            global_servers = self._normalize_scope(
                self._load_scope_raw('global'), source='global')
            project_servers = self._normalize_scope(
                self._load_scope_raw('project'), source='project')
            from ms_agent.config.mcp_schema import merge_mcp_layers
            return merge_mcp_layers(global_servers, project_servers)

    def get(self, name: str, scope: MCPScope = 'merged') -> Optional[Dict[str, Any]]:
        servers = self.list(scope)
        entry = servers.get(name)
        return copy.deepcopy(entry) if entry else None

    def add(
        self,
        name: str,
        server: Dict[str, Any],
        scope: Literal['global', 'project'] = 'project',
    ) -> None:
        with self._lock:
            raw = self._load_scope_raw(scope)
            entry = copy.deepcopy(server)
            entry.setdefault('enabled', True)
            entry.setdefault(
                'meta',
                {
                    'added_at': datetime.now(timezone.utc).isoformat(),
                },
            )
            raw[name] = entry
            self._save_scope_raw(scope, raw)

    def update(
        self,
        name: str,
        patch: Dict[str, Any],
        scope: Literal['global', 'project'] = 'project',
    ) -> None:
        with self._lock:
            raw = self._load_scope_raw(scope)
            if name not in raw:
                raise KeyError(f'MCP server not found in {scope} scope: {name}')
            merged = copy.deepcopy(raw[name])
            merged.update(copy.deepcopy(patch))
            raw[name] = merged
            self._save_scope_raw(scope, raw)

    def remove(self, name: str, scope: Literal['global', 'project'] = 'project') -> None:
        """Remove or mask a server.

        Project scope masks a global server (``enabled: false``) without
        deleting the global definition. Global scope deletes the entry.
        """
        with self._lock:
            raw = self._load_scope_raw(scope)
            if scope == 'project':
                raw[name] = {'enabled': False, '_removed': True}
            elif name in raw:
                del raw[name]
            else:
                raise KeyError(f'MCP server not found in global scope: {name}')
            self._save_scope_raw(scope, raw)

    def set_enabled(
        self,
        name: str,
        enabled: bool,
        scope: Literal['global', 'project'] = 'project',
    ) -> None:
        with self._lock:
            raw = self._load_scope_raw(scope)
            if name not in raw:
                if scope == 'project':
                    raw[name] = {'enabled': enabled}
                else:
                    raise KeyError(f'MCP server not found in {scope} scope: {name}')
            else:
                raw[name]['enabled'] = enabled
                raw[name].pop('_removed', None)
            self._save_scope_raw(scope, raw)

    # ── import / export ──────────────────────────────────────────────────

    def import_cursor_format(self, path: Path | str, merge: bool = True) -> int:
        path = Path(path).expanduser()
        data = self._read_json(path)
        incoming = data.get('mcpServers', data)
        if not isinstance(incoming, dict):
            return 0
        with self._lock:
            raw = self._load_scope_raw('global') if merge else {}
            count = 0
            for name, entry in incoming.items():
                if not isinstance(entry, dict):
                    continue
                raw[name] = copy.deepcopy(entry)
                raw[name].setdefault('enabled', True)
                count += 1
            self._save_scope_raw('global', raw)
            return count

    def export_mcp_json(
        self,
        path: Path | str,
        scope: MCPScope = 'merged',
        *,
        redact_secrets: bool = True,
    ) -> None:
        servers = self.list(scope)
        if redact_secrets:
            servers = self._redact_servers(servers)
        self._write_json(Path(path).expanduser(), {'mcpServers': servers})

    @staticmethod
    def _redact_servers(servers: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        redacted: Dict[str, Dict[str, Any]] = {}
        secret_keys = {'api_key', 'token', 'secret', 'password', 'authorization'}
        for name, entry in servers.items():
            item = copy.deepcopy(entry)
            env = item.get('env')
            if isinstance(env, dict):
                item['env'] = {
                    k: '***' if any(s in k.lower() for s in secret_keys) else v
                    for k, v in env.items()
                }
            headers = item.get('headers')
            if isinstance(headers, dict):
                item['headers'] = {
                    k: '***' if any(s in k.lower() for s in secret_keys) else v
                    for k, v in headers.items()
                }
            redacted[name] = item
        return redacted

    def resolve_env(self, server: Dict[str, Any]) -> Dict[str, str]:
        """Fill empty env values from ``Env.load_env()`` (same as MCPClient)."""
        envs = Env.load_env()
        env_dict = copy.deepcopy(server.get('env') or {})
        return {
            key: value if value else envs.get(key, '')
            for key, value in env_dict.items()
        }
