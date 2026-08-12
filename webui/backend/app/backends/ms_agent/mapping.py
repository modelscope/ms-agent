"""Converters between SDK dataclasses and the WebUI pydantic schemas.

UI-only fields (description, auto-attach, preview, ...) come from the sidecar.
pydantic coerces the SDK's ISO date strings into datetime on assignment.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone

from app.backends.ms_agent import sidecar
from app.schemas.model import Model as ModelSchema
from app.schemas.project import Project as ProjectSchema
from app.schemas.provider import Provider as ProviderSchema
from app.schemas.session import Session as SessionSchema


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _memory_backend(value) -> str:
    return value if value in ("file", "vector") else "file"


def _protocol(transport: str) -> str:
    return "anthropic" if "anthropic" in (transport or "") else "openai"


def _generation_defaults(protocol: str, provider: str) -> dict:
    """Effective default generation params the backend applies for a provider,
    surfaced read-only so the settings UI can show the thinking knob. Currently
    just the protocol-derived ``enable_thinking`` default (config.thinking_default
    is the single source of truth)."""
    from app.backends.ms_agent.config import thinking_default

    return {"extra_body": {"enable_thinking": thinking_default(protocol, provider)}}


def _mask(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}****{api_key[-4:]}"


def project_to_schema(project) -> ProjectSchema:
    from ms_agent.project.types import DEFAULT_PROJECT_ID

    meta = sidecar.get("projects", project.id, {}) or {}
    return ProjectSchema(
        id=project.id,
        name=project.name,
        description=meta.get("description", ""),
        local_path=project.path,
        is_default=(project.id == DEFAULT_PROJECT_ID),
        memory_enabled=bool(project.memory_enabled),
        memory_backend=_memory_backend(project.memory_backend),
        # Sticky flag written the first time memory is saved as enabled; an
        # already-enabled project created before the flag existed counts as
        # locked too (its storage is live regardless of the bookkeeping).
        memory_backend_locked=bool(
            meta.get("memory_backend_locked", False)
            or project.memory_enabled
        ),
        # Project-owned memory-model group (absent on legacy projects = the
        # follow-conversation defaults).
        memory_llm_provider_id=(meta.get("memory_models") or {}).get("llm_provider_id"),
        memory_llm_model=(meta.get("memory_models") or {}).get("llm_model"),
        memory_embed_mode=(
            (meta.get("memory_models") or {}).get("embed_mode")
            if (meta.get("memory_models") or {}).get("embed_mode") in ("provider", "local")
            else "provider"
        ),
        memory_embed_provider_id=(meta.get("memory_models") or {}).get("embed_provider_id"),
        memory_embed_model=(meta.get("memory_models") or {}).get("embed_model"),
        memory_recall_top_k=(meta.get("memory_models") or {}).get("recall_top_k"),
        mcp_auto_attach=meta.get("mcp_auto_attach", True),
        skill_auto_attach=meta.get("skill_auto_attach", True),
        permission_mode=meta.get("permission_mode", "restricted"),
        created_at=project.created_at,
    )


def session_to_schema(session) -> SessionSchema:
    meta = sidecar.get("sessions", session.id, {}) or {}
    return SessionSchema(
        id=session.id,
        title=session.name,
        project_id=session.project_id,
        updated_at=session.updated_at,
        preview=meta.get("preview", ""),
        category=meta.get("category", ""),
    )


# -- providers / models --------------------------------------------------------


def builtin_provider_to_schema(spec, override: dict | None = None) -> ProviderSchema:
    """A registry ProviderSpec, optionally merged with a settings.json custom
    entry of the same id (how a user sets creds for a built-in provider)."""
    override = override or {}
    meta = sidecar.get("providers", spec.name, {}) or {}
    # Honor a user's protocol override (e.g. pointing a built-in provider at
    # another vendor's Anthropic-compatible endpoint); fall back to the spec's
    # default transport. Mirrors base_url so the settings UI and any edit
    # round-trip reflect the stored value, not the default.
    protocol = (override.get("protocol")
                if override.get("protocol") in ("openai", "anthropic")
                else _protocol(spec.transport))
    return ProviderSchema(
        id=spec.name,
        kind="builtin",
        name=spec.display_name or spec.name,
        base_url=override.get("base_url") or spec.default_base_url,
        api_key_masked=_mask(override.get("api_key", "")),
        protocol=protocol,
        enabled=meta.get("enabled", True),
        default_generation_params=meta.get("default_generation_params", {}),
        generation_defaults=_generation_defaults(protocol, spec.name),
        created_at=_now(),
    )


def custom_provider_to_schema(pid: str, entry: dict) -> ProviderSchema:
    entry = entry or {}
    meta = sidecar.get("providers", pid, {}) or {}
    proto = entry.get("protocol")
    protocol = proto if proto in ("openai", "anthropic") else "openai"
    return ProviderSchema(
        id=pid,
        kind="custom",
        name=entry.get("name", pid),
        base_url=entry.get("base_url", ""),
        api_key_masked=_mask(entry.get("api_key", "")),
        protocol=protocol,
        enabled=meta.get("enabled", True),
        default_generation_params=meta.get("default_generation_params", {}),
        generation_defaults=_generation_defaults(protocol, pid),
        created_at=_now(),
    )


def encode_model_id(provider_id: str, name: str) -> str:
    raw = f"{provider_id}\x1f{name}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_model_id(model_id: str) -> tuple[str, str]:
    pad = "=" * (-len(model_id) % 4)
    raw = base64.urlsafe_b64decode(model_id + pad).decode()
    provider_id, name = raw.split("\x1f", 1)
    return provider_id, name


def model_to_schema(provider_id: str, name: str) -> ModelSchema:
    mid = encode_model_id(provider_id, name)
    meta = sidecar.get("models", mid, {}) or {}
    return ModelSchema(
        id=mid,
        provider_id=provider_id,
        name=name,
        display_name=meta.get("display_name") or name,
        is_builtin=False,
        advanced_params=meta.get("advanced_params", {}),
        created_at=_now(),
    )
