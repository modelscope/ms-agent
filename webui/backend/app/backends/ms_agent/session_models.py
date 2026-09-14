"""Session selections and per-turn model configuration snapshots."""
from __future__ import annotations

import copy
from dataclasses import dataclass

from ms_agent.config.model_settings import resolve_model_settings

from app.backends.errors import BadRequest, NotFound
from app.backends.ms_agent import model_link, sidecar
from app.backends.ms_agent.common import sm_for
from app.backends.ms_agent.mapping import decode_model_id, encode_model_id
from app.backends.ms_agent.settings_store import settings_lock


@dataclass(frozen=True)
class ModelSnapshot:
    key: tuple[str, str]
    settings: dict
    metadata: dict


def selection(session, data: dict | None = None) -> tuple[str, str] | None:
    provider = getattr(session, "model_provider", None)
    model = getattr(session, "model", None)
    if provider and model:
        return provider, model
    legacy = sidecar.get("sessions", session.id, {}) or {}
    if legacy.get("model_id"):
        try:
            return decode_model_id(legacy["model_id"])
        except (ValueError, TypeError):
            return None
    if model:
        data = data if data is not None else model_link._load()
        candidates = [pid for pid, entry in (data.get("providers") or {}).items()
                      if model in (entry.get("models") or [])]
        if len(candidates) == 1:
            return candidates[0], model
    return None


def validate_selection(provider: str, model: str, data: dict | None = None,
                       metadata: dict | None = None) -> None:
    data = data if data is not None else model_link._load()
    metadata = metadata if metadata is not None else sidecar._load()
    entry = (data.get("providers") or {}).get(provider) or {}
    legacy_llm = data.get("llm") or {}
    legacy_only = "providers" not in data and (legacy_llm.get("provider"), legacy_llm.get("model")) == (provider, model)
    if not provider or not model or (model not in (entry.get("models") or []) and not legacy_only):
        raise BadRequest("This model is no longer available. Select a configured model.")
    if (metadata.get("providers", {}).get(provider) or {}).get("enabled") is False:
        raise BadRequest("This provider is disabled. Enable it or select another model.")


def create(project, *, name: str = "", model_id: str | None = None):
    manager = sm_for(project)
    with manager.transaction_lock(), settings_lock(), sidecar.transaction_lock():
        data = model_link._load()
        if model_id:
            try:
                key = decode_model_id(model_id)
            except (ValueError, TypeError):
                raise BadRequest("Invalid model selection.") from None
        else:
            key = model_link.active_model(data)
        if all(key):
            validate_selection(*key, data=data)
        return manager.create(name=name, model_provider=key[0], model=key[1])


def migrate(project, session):
    """Bind a known legacy identity; never invent an unrecorded historical model."""
    manager = sm_for(project)
    with manager.transaction_lock(), settings_lock(), sidecar.transaction_lock():
        current = manager.get(session.id)
        if current is None:
            raise NotFound("Conversation not found.")
        if current.model_provider and current.model:
            return current
        key = selection(current)
        if key:
            return manager.update(current.id, model_provider=key[0], model=key[1],
                                  preserve_updated_at=True)
        return current


def change(project, session_id: str, model_id: str):
    manager = sm_for(project)
    with manager.transaction_lock(), settings_lock(), sidecar.transaction_lock():
        current = manager.get(session_id)
        if current is None:
            raise NotFound("Conversation not found.")
        try:
            provider, model = decode_model_id(model_id)
        except (ValueError, TypeError):
            raise BadRequest("Invalid model selection.") from None
        validate_selection(provider, model)
        # Both writes must succeed before the API reports success. A process
        # crash between files is not a crash-atomic multi-file transaction.
        current = manager.update(session_id, model_provider=provider, model=model)
        model_link.set_active_model(provider, model)
        return current


def prepare(project, session) -> tuple[object, ModelSnapshot]:
    manager = sm_for(project)
    with manager.transaction_lock(), settings_lock(), sidecar.transaction_lock():
        current = migrate(project, session)
        data = model_link._load()
        metadata = sidecar._load()
        key = selection(current, data)
        if key is None:
            raise BadRequest("No model is recorded for this conversation. Select a model before sending.")
        validate_selection(*key, data=data, metadata=metadata)
        llm = resolve_model_settings(data, *key)
        if "api_key" in llm and not llm["api_key"]:
            raise BadRequest("The selected provider's API key is empty. Configure it before sending.")
        effective = copy.deepcopy(data)
        effective["llm"] = llm
        effective["default_model"] = f"{key[0]}/{key[1]}"
        return current, ModelSnapshot(key, effective, metadata)
