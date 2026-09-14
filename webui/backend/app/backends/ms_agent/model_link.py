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

from pathlib import Path

from ms_agent.utils.atomic_file import atomic_write_json

from app.backends.ms_agent.common import home
from app.backends.ms_agent.settings_store import settings_lock


def _path() -> Path:
    return Path(home()) / "settings.json"


def _load_unlocked() -> dict:
    from app.backends.ms_agent.tool_settings import ensure_tool_settings

    return ensure_tool_settings(home())


def _load() -> dict:
    with settings_lock():
        return _load_unlocked()


def _save_unlocked(data: dict) -> None:
    atomic_write_json(_path(), data)


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


def preserve_legacy_credentials(data: dict) -> None:
    """Keep old llm-only credentials reachable when the default moves away."""
    llm = data.get("llm") or {}
    provider = llm.get("provider")
    if not provider:
        return
    entry = data.setdefault("providers", {}).setdefault(provider, {})
    for key in ("api_key", "base_url", "protocol"):
        if key in llm and key not in entry:
            entry[key] = llm[key]


def set_active_model(provider: str, model: str) -> None:
    from ms_agent.config.model_settings import resolve_model_settings

    with settings_lock():
        data = _load_unlocked()
        preserve_legacy_credentials(data)
        previous = data.get("llm") or {}
        entry = (data.get("providers") or {}).get(provider) or {}
        selected = resolve_model_settings(data, provider, model)
        if "protocol" not in entry and not (previous.get("provider") == provider and "protocol" in previous):
            selected.pop("protocol", None)
        if not selected.get("api_key"):
            selected.pop("api_key", None)
        data["llm"] = selected
        data["default_model"] = f"{provider}/{model}"
        prov = data.setdefault("providers", {}).setdefault(provider, {})
        for key in ("api_key", "base_url"):
            if key not in prov and data["llm"].get(key):
                prov[key] = data["llm"][key]
        models = prov.setdefault("models", [])
        if model and model not in models:
            models.append(model)
        _save_unlocked(data)


def ensure_link() -> None:
    """Normalize on boot: default_model -> 'provider/model' and the active model
    registered in the catalog, so the chat dropdown is never empty for a
    configured model."""
    with settings_lock():
        provider, model = active_model()
        if provider and model:
            set_active_model(provider, model)
