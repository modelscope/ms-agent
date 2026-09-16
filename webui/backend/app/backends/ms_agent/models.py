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
    if body.advanced_params:
        side["advanced_params"] = body.advanced_params
    if body.supports_vision is not None:
        side["supports_vision"] = bool(body.supports_vision)
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
    if body.advanced_params is not None:
        side["advanced_params"] = body.advanced_params
    if body.supports_vision is not None:
        side["supports_vision"] = bool(body.supports_vision)
    if side:
        sidecar.merge("models", model_id, side)
    if body.advanced_params is not None or body.supports_vision is not None:
        # An agent freezes its whole config at build time, so an open
        # conversation would keep sending the old thinking parameters — and
        # keep the old vision decision — until it is evicted. The user flips
        # the switch, sees no difference, and concludes the setting does
        # nothing. Flagging costs nothing and the swap happens on the next
        # idle turn.
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


def generation_defaults(provider_id: str, model: str = "") -> GenerationDefaults:
    """The read-only preview behind the advanced-params editor.

    Resolved by the SDK against the provider's real base_url, so what the dialog
    shows is literally what the next request will carry — the settings page and
    the runtime cannot drift apart because they call the same function.

    ``model`` is accepted for a per-model answer later (vendors do vary the
    default per model) but is not consulted today: the dialect, and therefore
    the wire shape, is decided by the endpoint.
    """
    from ms_agent.llm.thinking import offered_tiers

    from app.backends.ms_agent.config import _read_settings, thinking_plan

    entry = (_read_settings().get("providers") or {}).get(
        (provider_id or "").lower()
    ) or {}
    protocol = entry.get("protocol") or "openai"
    stored = (sidecar.get("providers", provider_id) or {}).get(
        "default_generation_params"
    ) or {}
    if model:
        stored = {
            **stored,
            **((sidecar.get("models", encode_model_id(provider_id, model)) or {}).get(
                "advanced_params"
            ) or {}),
        }
    effort = stored.get("reasoning_effort", "auto")
    resolved = thinking_plan(
        protocol,
        provider_id,
        effort,
        existing={k: v for k, v in stored.items() if k != "reasoning_effort"},
    )
    return GenerationDefaults(
        effort=resolved["requested"],
        # Only the rungs this endpoint really has: a switch-only
        # provider gets two, not the whole ladder.
        effort_options=list(offered_tiers(resolved["family"])),
        effective=resolved["effective"],
        wire_params=resolved["params"],
        family=resolved["family"],
        extra_hint=resolved["extra_hint"],
    )
