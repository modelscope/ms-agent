"""Keep the model link coherent.

Three things must agree for the UI to work:
  * chat's active credentials  -> settings.json `llm` block (what ConfigResolver reads)
  * the default model          -> settings.json `default_model` = "provider/model"
  * the model catalog          -> settings.json `providers[p].models` (what /api/models lists)

Selecting a model in the UI sends a base64 Model.id (provider+name); this module
decodes it, points the llm block + default_model at it, and makes sure it's in
the catalog. Credential precedence: provider override -> current llm block (same
provider) -> built-in registry default.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from app.backends.ms_agent.common import home
from app.backends.ms_agent.settings_store import settings_lock


def _path() -> Path:
    return Path(home()) / "settings.json"


def _load_unlocked() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _load() -> dict:
    with settings_lock():
        return _load_unlocked()


def _save_unlocked(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _save(data: dict) -> None:
    with settings_lock():
        _save_unlocked(data)


def _registry_base_url(provider: str) -> str:
    try:
        from ms_agent.llm.spec import get_registry

        for spec in get_registry().list_providers():
            if spec.name == provider:
                return spec.default_base_url or ""
    except Exception:
        pass
    return ""


def active_model(data: dict | None = None) -> tuple[str | None, str | None]:
    """(provider, model) of the currently-active model, best-effort."""
    data = data if data is not None else _load()
    dm = data.get("default_model")
    if dm and "/" in dm:
        provider, model = dm.split("/", 1)
        return provider, model
    llm = data.get("llm", {}) or {}
    if dm:  # bare model name — infer its provider from the catalog or the llm block
        for p, v in (data.get("providers", {}) or {}).items():
            if dm in ((v or {}).get("models") or []):
                return p, dm
        return llm.get("provider"), dm
    if llm.get("provider") and llm.get("model"):
        return llm.get("provider"), llm.get("model")
    return None, None


def set_active_model(provider: str, model: str) -> None:
    """Point the llm block + default_model at (provider, model) and ensure the
    model is in the provider's catalog. Preserves working credentials."""
    with settings_lock():
        data = _load_unlocked()
        llm = data.get("llm", {}) or {}
        prov_entry = (data.get("providers", {}) or {}).get(provider, {}) or {}
        same_provider = llm.get("provider") == provider

        if "api_key" in prov_entry:
            api_key = prov_entry.get("api_key") or ""
        else:
            api_key = (llm.get("api_key") if same_provider else "") or ""
        if "base_url" in prov_entry:
            base_url = prov_entry.get("base_url") or _registry_base_url(provider)
        else:
            base_url = (llm.get("base_url") if same_provider else "") or _registry_base_url(provider)

        new_llm = {"provider": provider, "model": model}
        if api_key:
            new_llm["api_key"] = api_key
        if base_url:
            new_llm["base_url"] = base_url
        data["llm"] = new_llm
        data["default_model"] = f"{provider}/{model}"

        prov = data.setdefault("providers", {}).setdefault(provider, {})
        prov.setdefault("protocol", "openai")
        if api_key and not prov.get("api_key"):
            prov["api_key"] = api_key
        if base_url and not prov.get("base_url"):
            prov["base_url"] = base_url
        models = prov.setdefault("models", [])
        if model and model not in models:
            models.append(model)

        _save_unlocked(data)


def ensure_link() -> None:
    """Normalize on boot: default_model -> 'provider/model' and the active model
    registered in the catalog, so the chat dropdown is never empty for a
    configured model."""
    provider, model = active_model()
    if provider and model:
        set_active_model(provider, model)
