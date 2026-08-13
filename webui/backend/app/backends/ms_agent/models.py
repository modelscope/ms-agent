"""Models adapter — models live as string lists inside settings.json providers.

A synthetic id encodes (provider_id, name); display_name / advanced_params (not
modelled by the SDK) live in the sidecar keyed by that id."""
from __future__ import annotations

from app.backends.errors import BadRequest, NotFound
from app.backends.ms_agent import sidecar
from app.backends.ms_agent.common import home
from app.backends.ms_agent.mapping import (
    decode_model_id,
    encode_model_id,
    model_to_schema,
)
from app.backends.ms_agent.settings_store import settings_lock
from app.schemas.model import Model, ModelCreate, ModelUpdate


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


def create_model(body: ModelCreate) -> Model:
    with settings_lock():
        msm = _msm()
        if body.provider_id not in msm.list_custom_providers() and body.provider_id not in _builtin_ids():
            raise BadRequest("unknown provider")
        msm.add_model(body.provider_id, body.name)
    mid = encode_model_id(body.provider_id, body.name)
    side = {}
    if body.display_name:
        side["display_name"] = body.display_name
    if body.advanced_params:
        side["advanced_params"] = body.advanced_params
    if side:
        sidecar.merge("models", mid, side)
    return model_to_schema(body.provider_id, body.name)


def _decode(model_id: str) -> tuple[str, str]:
    try:
        return decode_model_id(model_id)
    except Exception:
        raise NotFound("model not found")


def update_model(model_id: str, body: ModelUpdate) -> Model:
    provider_id, name = _decode(model_id)
    if name not in _model_names(provider_id):
        raise NotFound("model not found")
    side = {}
    if body.display_name is not None:
        side["display_name"] = body.display_name
    if body.advanced_params is not None:
        side["advanced_params"] = body.advanced_params
    if side:
        sidecar.merge("models", model_id, side)
    return model_to_schema(provider_id, name)


def delete_model(model_id: str) -> None:
    provider_id, name = _decode(model_id)
    with settings_lock():
        if name not in _msm().list_custom_providers().get(provider_id, {}).get("models", []):
            raise NotFound("model not found")
        _msm().remove_model(provider_id, name)
    sidecar.drop("models", model_id)
