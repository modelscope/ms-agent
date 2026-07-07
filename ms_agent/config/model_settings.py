# Copyright (c) ModelScope Contributors. All rights reserved.
"""Persistent model-provider settings (WebUI "Model settings" page / 原型图10).

Manages the ``providers`` / ``default_model`` sections of
``~/.ms_agent/settings.json`` so a UI can add/remove custom providers and
models and pick a default, on top of the read-only built-in registry
(``ms_agent/llm/spec.py``). Read-modify-write is atomic (tmp + rename) and
never clobbers the other settings.json sections (llm, personalization, ...).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class ModelSettingsManager:
    """CRUD for custom providers/models + default model in settings.json."""

    def __init__(self, global_dir: str | Path = '~/.ms_agent') -> None:
        self._dir = Path(global_dir).expanduser()
        self._path = self._dir / 'settings.json'

    # -- raw settings.json io --

    def _load_raw(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_raw(self, data: Dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix('.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)

    # -- providers --

    def list_custom_providers(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._load_raw().get('providers', {}) or {})

    def list_providers(self) -> List[Dict[str, Any]]:
        """Built-in (read-only, from the registry) + custom providers."""
        from ms_agent.llm.spec import get_registry
        out: List[Dict[str, Any]] = []
        for spec in get_registry().list_providers():
            out.append({
                'id': spec.name,
                'name': spec.name,
                'protocol': spec.transport,
                'builtin': True,
                'models': list(getattr(spec, 'keywords', []) or []),
            })
        builtin_ids = {p['id'] for p in out}
        for pid, p in self.list_custom_providers().items():
            entry = {'id': pid, 'builtin': False, **p}
            if pid in builtin_ids:  # custom override of a builtin id
                entry['overrides_builtin'] = True
            out.append(entry)
        return out

    def add_provider(
        self,
        provider_id: str,
        *,
        name: Optional[str] = None,
        protocol: str = 'openai',
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        models: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        data = self._load_raw()
        providers = data.setdefault('providers', {})
        entry = providers.get(provider_id, {})
        entry.update({
            'name': name or entry.get('name') or provider_id,
            'protocol': protocol,
        })
        if api_key is not None:
            entry['api_key'] = api_key
        if base_url is not None:
            entry['base_url'] = base_url
        entry['models'] = list(models if models is not None
                               else entry.get('models', []))
        providers[provider_id] = entry
        self._save_raw(data)
        return entry

    def remove_provider(self, provider_id: str) -> None:
        data = self._load_raw()
        if data.get('providers', {}).pop(provider_id, None) is not None:
            self._save_raw(data)

    def add_model(self, provider_id: str, model: str) -> None:
        data = self._load_raw()
        providers = data.setdefault('providers', {})
        entry = providers.setdefault(provider_id, {'name': provider_id,
                                                   'protocol': 'openai',
                                                   'models': []})
        models = entry.setdefault('models', [])
        if model not in models:
            models.append(model)
            self._save_raw(data)

    def remove_model(self, provider_id: str, model: str) -> None:
        data = self._load_raw()
        entry = data.get('providers', {}).get(provider_id)
        if entry and model in entry.get('models', []):
            entry['models'].remove(model)
            self._save_raw(data)

    # -- default model --

    def get_default_model(self) -> Optional[str]:
        """Returns ``provider/model`` (or bare ``model``), or None."""
        return self._load_raw().get('default_model')

    def set_default_model(self, model: str, provider: Optional[str] = None) -> None:
        data = self._load_raw()
        data['default_model'] = f'{provider}/{model}' if provider else model
        self._save_raw(data)
