"""Models adapter — models live as string lists inside settings.json providers.

A synthetic id encodes (provider_id, name); display_name / advanced_params (not
modelled by the SDK) live in the sidecar keyed by that id."""
from __future__ import annotations

from pathlib import Path
from ms_agent.utils.file_lock import locked

import logging

from app.backends.errors import BadRequest, NotFound
from app.backends.ms_agent import sidecar
from app.backends.ms_agent.common import home
from app.backends.ms_agent.mapping import (
    decode_model_id,
    encode_model_id,
    model_to_schema,
)
from app.backends.ms_agent.settings_store import settings_lock
from app.schemas.model import (
    GenerationDefaults,
    Model,
    ModelCreate,
    ModelUpdate,
)

logger = logging.getLogger("app.ms_agent.models")


def _msm():
    from ms_agent.config.model_settings import ModelSettingsManager

    return ModelSettingsManager(global_dir=home())


def _builtin_ids() -> set[str]:
    from ms_agent.llm.spec import get_registry

    return {s.name for s in get_registry().list_providers()}


def _model_names(provider_id: str) -> list[str]:
    with settings_lock():
        return _msm().list_custom_providers().get(provider_id, {}).get("models", [])


def list_models(provider_id: str | None = None) -> list[Model]:
    with settings_lock():
        custom = _msm().list_custom_providers()
    out: list[Model] = []
    for pid, entry in custom.items():
        if provider_id and pid != provider_id:
            continue
        for name in entry.get("models", []):
            out.append(model_to_schema(pid, name))
    return out


@locked(lambda *args, **kwargs: Path(home()) / "settings.json")
def create_model(body: ModelCreate) -> Model:
    with settings_lock():
        msm = _msm()
        if body.provider_id not in msm.list_custom_providers() and body.provider_id not in _builtin_ids():
            raise BadRequest("Provider not found.")
        msm.add_model(body.provider_id, body.name)
    mid = encode_model_id(body.provider_id, body.name)
    side = {}
    if body.display_name:
        side["display_name"] = body.display_name
    advanced = dict(body.advanced_params)
    if body.reasoning_effort is not None:
        advanced["reasoning_effort"] = body.reasoning_effort
    if advanced:
        side["advanced_params"] = advanced
    if body.supports_vision is not None:
        side["supports_vision"] = body.supports_vision
    if body.context_limit is not None:
        side["context_limit"] = body.context_limit
    if side:
        sidecar.merge("models", mid, side)
    return model_to_schema(body.provider_id, body.name)


def _decode(model_id: str) -> tuple[str, str]:
    try:
        return decode_model_id(model_id)
    except Exception:
        raise NotFound("Model not found.")


@locked(lambda *args, **kwargs: Path(home()) / "settings.json")
def update_model(model_id: str, body: ModelUpdate) -> Model:
    provider_id, name = _decode(model_id)
    if name not in _model_names(provider_id):
        raise NotFound("Model not found.")
    side = {}
    if body.display_name is not None:
        side["display_name"] = body.display_name
    with sidecar.transaction_lock():
        if body.advanced_params is not None:
            side["advanced_params"] = dict(body.advanced_params)
        if body.reasoning_effort is not None:
            advanced = side.setdefault("advanced_params", dict(
                (sidecar.get("models", model_id) or {}).get("advanced_params") or {}))
            advanced["reasoning_effort"] = body.reasoning_effort
        for key in ("supports_vision", "context_limit"):
            if key in body.model_fields_set:
                side[key] = getattr(body, key)
        if side:
            sidecar.merge("models", model_id, side)
    if body.model_fields_set & {"advanced_params", "reasoning_effort", "supports_vision", "context_limit"}:
        from app.backends.ms_agent.runtime import registry

        registry.mark_all_stale()
    return model_to_schema(provider_id, name)


@locked(lambda *args, **kwargs: Path(home()) / "settings.json")
def delete_model(model_id: str) -> None:
    provider_id, name = _decode(model_id)
    with settings_lock():
        if name not in _msm().list_custom_providers().get(provider_id, {}).get("models", []):
            raise NotFound("Model not found.")
        _msm().remove_model(provider_id, name)
    sidecar.drop("models", model_id)


def generation_defaults(provider_id: str, model: str = "", *,
                        reasoning_effort: str | None = None) -> GenerationDefaults:
    from omegaconf import OmegaConf

    from ms_agent.config.model_settings import resolve_model_settings
    from ms_agent.llm.context_budget import resolve_context_budget
    from ms_agent.llm.model_catalog import get_model
    from ms_agent.llm.spec import get_registry
    from ms_agent.llm.vision import resolve_supports_vision

    from app.backends.ms_agent.config import (
        _deep_merge, _read_settings, _webui_generation_params,
        provider_base_url, thinking_plan,
    )
    from app.schemas.model import CatalogMetadata

    settings = _read_settings()
    llm = resolve_model_settings(settings, provider_id, model)
    spec = get_registry().get(provider_id)
    protocol = llm.get("protocol") or "openai"
    base_url = provider_base_url(provider_id)
    stored = _deep_merge(settings.get("generation_config") or {},
                         _webui_generation_params(provider_id, model))
    if reasoning_effort is not None:
        stored["reasoning_effort"] = reasoning_effort
    if llm.get("max_tokens") is not None:
        stored.setdefault("max_tokens", llm["max_tokens"])
    if not model:
        stored = _deep_merge(stored, (sidecar.get("providers", provider_id) or {}).get(
            "default_generation_params") or {})
    side = sidecar.get("models", encode_model_id(provider_id, model)) or {}
    metadata = get_model(provider_id, model, base_url=base_url)
    cfg = OmegaConf.create({
        "llm": {"service": provider_id, "model": model, "base_url": base_url,
                "protocol": protocol, "supports_vision": side.get("supports_vision"),
                "context_limit": side.get("context_limit")},
        "generation_config": stored,
        "compaction": settings.get("compaction") or {},
        "session_log": settings.get("session_log") or {},
    })
    effort = stored.get("reasoning_effort", "auto")
    errors = []
    try:
        resolved = thinking_plan(protocol, provider_id, effort, model=model,
                                 existing={k: v for k, v in stored.items() if k != "reasoning_effort"})
    except (ValueError, TypeError) as exc:
        errors.append(str(exc))
        resolved = thinking_plan(protocol, provider_id, "auto", model=model)
        resolved["params"] = {}
    try:
        budget = resolve_context_budget(cfg, metadata=metadata)
    except ValueError as exc:
        errors.append(str(exc))
        budget = None
    catalog = None
    if metadata:
        limits = metadata.get("limit") or {}
        modalities = metadata.get("modalities") or {}
        catalog = CatalogMetadata(
            revision=metadata["catalog_revision"], provider_id=metadata["catalog_provider"],
            context_limit=limits.get("context"), input_limit=limits.get("input"),
            output_limit=limits.get("output"), input_modalities=modalities.get("input") or [],
            output_modalities=modalities.get("output") or [],
            reasoning=metadata.get("reasoning"), tool_call=metadata.get("tool_call"),
        )
    extra = stored.get("extra_body")
    from ms_agent.llm.thinking import THINKING_PARAM_KEYS
    raw_keys = set(THINKING_PARAM_KEYS) - {'reasoning_effort'}
    raw_override = bool(raw_keys & set(stored) or
                        isinstance(extra, dict) and set(THINKING_PARAM_KEYS) & set(extra))
    options = list(resolved["effort_options"])
    requested = resolved["requested"]
    if "on" in options and requested not in ("auto", "off"):
        requested = "on"
    return GenerationDefaults(
        effort=requested, effort_options=options, effective=resolved["effective"],
        wire_params=resolved["params"], family=resolved["family"],
        extra_hint=resolved["extra_hint"], reasoning=resolved.get("reasoning"),
        reasoning_control=resolved.get("reasoning_control", "unknown"),
        raw_override=raw_override, configuration_error="; ".join(errors), catalog=catalog,
        context_budget=budget,
        effective_supports_vision=resolve_supports_vision(cfg, spec=spec, model=model, base_url=base_url),
    )
