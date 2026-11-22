"""Read-only preflight for memory model selection; no stores are created."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ms_agent.llm.credentials import CredentialResolver

from app.backends.ms_agent import config as C
from app.schemas.memory import (MemoryEmbedderInfo, MemoryErrorInfo,
                                MemoryModelCheck, MemoryModelCheckResult,
                                MemoryProviderOption)


def provider_options() -> list[MemoryProviderOption]:
    from app.backends.ms_agent.models import list_models
    from app.backends.ms_agent.providers import list_providers

    settings = C._read_settings()
    models = list_models()
    options = []
    for provider in list_providers():
        entry = (settings.get("providers") or {}).get(provider.id) or {}
        key, url = CredentialResolver.resolve_fields(provider.id, entry)
        suggested = [m.name for m in models
                     if m.provider_id == provider.id and m.purpose == "embedding"]
        default = C._KNOWN_EMBED_MODELS.get(provider.id)
        explicitly_chat = any(m.provider_id == provider.id and m.name == default
                              and m.purpose == "chat" for m in models)
        if default and default not in suggested and not explicitly_chat:
            suggested.append(default)
        options.append(MemoryProviderOption(
            id=provider.id, credentials_available=bool(key),
            endpoint_available=bool(url), embedding_models=suggested))
    return options


def check_models(body: MemoryModelCheck) -> MemoryModelCheckResult:
    from app.backends.ms_agent.models import list_models

    settings = C._read_settings()
    cfg = {key.removeprefix("memory_"): value for key, value in
           body.model_dump(exclude={"probe"}).items()}
    errors = []
    info = None
    try:
        C._mem0_llm(settings, cfg)
        llm = settings.get("llm") or {}
        pid = cfg.get("llm_provider_id") or llm.get("provider")
        model = cfg.get("llm_model") or llm.get("model")
        if any(m.name == model and m.purpose == "embedding" for m in list_models(pid)):
            raise C.MemoryConfigError("llm_model_type",
                "Embedding models cannot extract facts. Choose a chat model.")
    except C.MemoryConfigError as exc:
        errors.append(MemoryErrorInfo(code=exc.code, message=str(exc)))
    try:
        desc = C._resolve_embedder(settings, cfg)
        if desc["mode"] == "provider":
            known = next((m for m in list_models(desc["provider"])
                          if m.name == desc["model"]), None)
            if known and known.purpose == "chat":
                raise C.MemoryConfigError("embed_model_type",
                    "This model is configured for chat. Choose an embedding model.")
        dims = None
        if body.probe and not errors:
            dims, _ = C._probe_embed_dimension(desc)
        info = MemoryEmbedderInfo(mode=desc["mode"], provider=desc.get("provider"),
                                 model=desc["model"], dimension=dims)
    except C.MemoryConfigError as exc:
        errors.append(MemoryErrorInfo(code=exc.code, message=str(exc)))
    return MemoryModelCheckResult(valid=not errors, verified=body.probe and not errors,
                                  embedder=info, errors=errors)


def config_key(project) -> str:
    """Invalidate a build failure after settings, env or model choices change.

    Only the digest is persisted. Never expose resolved credentials to the UI.
    """
    from ms_agent.utils.json_store import read_json
    from app.backends.ms_agent.common import home

    # Runtime model snapshots enrich `llm` with credentials and capabilities.
    # Status requests have no such snapshot. Hash the same persisted settings
    # in both contexts so an actual build error remains visible after the turn.
    settings = read_json(Path(home()) / "settings.json")
    cfg = C._project_memory_models(project)
    llm = settings.get("llm") or {}
    pids = {cfg.get("embed_provider_id"), cfg.get("llm_provider_id"), llm.get("provider")}
    resolved = {pid: CredentialResolver.resolve_fields(pid,
        (settings.get("providers") or {}).get(pid) or {}) for pid in pids if pid}
    protocols = {pid: ((settings.get("providers") or {}).get(pid) or {}).get("protocol")
                 for pid in pids if pid}
    payload = [cfg, llm, resolved, protocols]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def record_build_error(project, error: C.MemoryConfigError | None) -> None:
    from app.backends.ms_agent import sidecar

    sidecar.merge("memory", project.id, {"build_error": None if error is None else {
        "config_key": config_key(project), "code": error.code, "message": str(error)}})


def current_build_error(project) -> MemoryErrorInfo | None:
    from app.backends.ms_agent import sidecar

    error = (sidecar.get("memory", project.id, {}) or {}).get("build_error")
    if error and error.get("config_key") == config_key(project):
        return MemoryErrorInfo(code=error["code"], message=error["message"])
    return None
