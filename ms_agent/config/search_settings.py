# Copyright (c) ModelScope Contributors. All rights reserved.
"""CRUD for ``settings.json`` ``tools.web_search`` (same block WebUI writes).

Keys are per-engine (``tavily_api_key``, ``exa_api_key``, …) because that is
what ``WebSearchTool`` reads. Switching engine must not drop another engine's
key. Environment variables are ignored here: this object describes only what
the settings file owns, matching the WebUI search page.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROVIDER_META: Dict[str, tuple[str, Optional[str]]] = {
    'tavily': ('Tavily Search', 'tavily_api_key'),
    'exa': ('Exa Search', 'exa_api_key'),
    'serpapi': ('SerpAPI', 'serpapi_api_key'),
    'arxiv': ('arXiv', None),
}
_KEYLESS = frozenset({'tavily', 'arxiv'})
_LEGACY_EXA_FIELDS = ('exa_api_keys', 'api_key')
_FALLBACK_ORDER = ('tavily', 'exa', 'serpapi', 'arxiv')


def supported_engine_ids() -> List[str]:
    try:
        from ms_agent.tools.search.websearch_tool import WebSearchTool
        ids = [str(e).lower() for e in WebSearchTool.SUPPORTED_ENGINES]
    except Exception:
        ids = list(_FALLBACK_ORDER)
    known = [i for i in _FALLBACK_ORDER if i in ids]
    extra = sorted(i for i in ids if i not in _FALLBACK_ORDER)
    return known + extra


def default_engine() -> str:
    ids = supported_engine_ids()
    if 'tavily' in ids:
        return 'tavily'
    return ids[0] if ids else 'tavily'


def key_field_for(engine: str) -> Optional[str]:
    return _PROVIDER_META.get(engine, (engine, f'{engine}_api_key'))[1]


def key_fields_for(engine: str) -> tuple[str, ...]:
    field = key_field_for(engine)
    if field is None:
        return ()
    if engine == 'exa':
        return (field, *_LEGACY_EXA_FIELDS)
    return (field,)


def requires_key(engine: str) -> bool:
    return key_field_for(engine) is not None


def supports_keyless(engine: str) -> bool:
    return engine in _KEYLESS


@dataclass(frozen=True)
class SearchSettings:
    enabled: bool
    engine: str
    has_key: bool
    supports_keyless: bool


class SearchSettingsManager:
    """Read/write ``tools.web_search`` in settings.json."""

    def __init__(self, global_dir: str | Path | None = None) -> None:
        if global_dir is None:
            from ms_agent.project.paths import global_home
            self._dir = global_home()
        else:
            self._dir = Path(os.path.expanduser(str(global_dir)))
        self._path = self._dir / 'settings.json'

    def _load_raw(self) -> Dict[str, Any]:
        if not self._path.is_file():
            return {}
        try:
            with open(self._path, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_raw(self, data: Dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix('.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)

    def _block(self, data: Dict[str, Any]) -> Dict[str, Any]:
        tools = data.get('tools')
        if not isinstance(tools, dict):
            return {}
        block = tools.get('web_search')
        return dict(block) if isinstance(block, dict) else {}

    def get(self) -> SearchSettings:
        block = self._block(self._load_raw())
        engine = str(block.get('engine') or '').lower() or default_engine()
        if engine not in supported_engine_ids():
            engine = default_engine()
        return SearchSettings(
            enabled=bool(block.get('enabled', True)),
            engine=engine,
            has_key=self._has_key(block, engine),
            supports_keyless=supports_keyless(engine),
        )

    def list_engines(self) -> List[Dict[str, Any]]:
        block = self._block(self._load_raw())
        rows = []
        for engine in supported_engine_ids():
            label, _ = _PROVIDER_META.get(engine, (engine, None))
            rows.append({
                'id': engine,
                'label': label,
                'requires_key': requires_key(engine),
                'supports_keyless': supports_keyless(engine),
                'has_key': self._has_key(block, engine),
            })
        return rows

    def set_engine(self, engine: str) -> SearchSettings:
        engine = engine.strip().lower()
        if engine not in supported_engine_ids():
            raise ValueError(
                f'Unknown search engine: {engine}. '
                f'Supported: {", ".join(supported_engine_ids())}')
        data = self._load_raw()
        block = self._ensure_block(data)
        block['engine'] = engine
        self._save_raw(data)
        return self.get()

    def set_enabled(self, enabled: bool) -> SearchSettings:
        data = self._load_raw()
        block = self._ensure_block(data)
        block['enabled'] = bool(enabled)
        self._save_raw(data)
        return self.get()

    def set_api_key(self, key: str | None, engine: str | None = None) -> SearchSettings:
        current = self.get()
        engine = (engine or current.engine).strip().lower()
        field = key_field_for(engine)
        if field is None:
            raise ValueError(f'{engine} does not use an API key.')
        data = self._load_raw()
        block = self._ensure_block(data)
        value = (key or '').strip()
        if value:
            block[field] = value
        else:
            block.pop(field, None)
            if engine == 'exa':
                for alias in _LEGACY_EXA_FIELDS:
                    block.pop(alias, None)
        self._save_raw(data)
        return self.get()

    def raw_block(self) -> Dict[str, Any]:
        return self._block(self._load_raw())

    def _ensure_block(self, data: Dict[str, Any]) -> Dict[str, Any]:
        tools = data.get('tools')
        if not isinstance(tools, dict):
            tools = {}
            data['tools'] = tools
        block = tools.get('web_search')
        if not isinstance(block, dict):
            # Same discriminator WebUI bootstrap writes.
            block = {'mcp': False}
            tools['web_search'] = block
        else:
            tools['web_search'] = block
        if not block.get('engine'):
            block['engine'] = default_engine()
        if 'enabled' not in block:
            block['enabled'] = True
        return block

    @staticmethod
    def _has_key(block: Dict[str, Any], engine: str) -> bool:
        return any(
            str(block.get(field) or '').strip()
            for field in key_fields_for(engine))
