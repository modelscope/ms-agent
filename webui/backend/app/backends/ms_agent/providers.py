"""Providers adapter — ModelSettingsManager + registry + sidecar.

Built-ins come from the read-only registry; customs from settings.json
`providers`. A custom entry whose id equals a built-in id is a credential
override and is merged into that built-in row (kept as a single entry)."""
from __future__ import annotations

from pathlib import Path
from ms_agent.utils.file_lock import locked

from app.backends.errors import BadRequest, Conflict, NotFound
from app.backends.ms_agent import model_link, sidecar
from app.backends.ms_agent.common import home
from app.backends.ms_agent.mapping import (
    builtin_provider_to_schema,
    custom_provider_to_schema,
    encode_model_id,
)
from app.backends.ms_agent.settings_store import settings_lock
from app.schemas.provider import Provider, ProviderCreate, ProviderUpdate


def _protocol(transport: str) -> str:
    return "anthropic" if "anthropic" in (transport or "") else "openai"


def _msm():
    from ms_agent.config.model_settings import ModelSettingsManager

    return ModelSettingsManager(global_dir=home())


def _specs():
    from ms_agent.llm.spec import get_registry

    return get_registry().list_providers()


def _builtin_ids() -> set[str]:
    return {s.name for s in _specs()}


def _default_name(pid: str) -> str:
    """The label to show when the user gave no display name of their own — the
    same fallback the read mapping applies. Resolved and written explicitly
    because the SDK's ``add_provider`` reads a falsy name as "keep the stored
    one", which would make clearing the field look like it did nothing."""
    spec = next((s for s in _specs() if s.name == pid), None)
    return (spec.display_name or spec.name) if spec else pid


def list_providers() -> list[Provider]:
    with settings_lock():
        custom = _msm().list_custom_providers()
        builtin_ids = _builtin_ids()
    out = [builtin_provider_to_schema(s, custom.get(s.name)) for s in _specs()]
    out += [
        custom_provider_to_schema(pid, entry) for pid, entry in custom.items()
        if pid not in builtin_ids
    ]
    return out


def get_provider(pid: str) -> Provider:
    with settings_lock():
        custom = _msm().list_custom_providers()
        if pid in _builtin_ids():
            spec = next(s for s in _specs() if s.name == pid)
            return builtin_provider_to_schema(spec, custom.get(pid))
        if pid in custom:
            return custom_provider_to_schema(pid, custom[pid])
    raise NotFound("Provider not found.")


@locked(lambda *args, **kwargs: Path(home()) / "settings.json")
def create_provider(body: ProviderCreate) -> Provider:
    with settings_lock():
        msm = _msm()
        if body.id in _builtin_ids() or body.id in msm.list_custom_providers():
            raise Conflict("A provider with this ID already exists.")
        msm.add_provider(
            body.id,
            name=body.name or body.id,
            protocol=body.protocol,
            base_url=body.base_url or None,
            models=[],
        )
        custom = msm.list_custom_providers().get(body.id, {})
    if body.default_generation_params:
        sidecar.merge(
            "providers",
            body.id,
            {"default_generation_params": body.default_generation_params},
        )
    return custom_provider_to_schema(body.id, custom)


@locked(lambda *args, **kwargs: Path(home()) / "settings.json")
def update_provider(pid: str, body: ProviderUpdate) -> Provider:
    with settings_lock():
        msm = _msm()
        custom = msm.list_custom_providers()
        if pid not in _builtin_ids() and pid not in custom:
            raise NotFound("Provider not found.")

        cur = custom.get(pid, {})
        settings_changed = any(v is not None
                               for v in (body.name, body.protocol,
                                         body.base_url, body.api_key))
        if settings_changed:
            name = body.name if body.name is not None else cur.get("name")
            msm.add_provider(
                pid,
                name=name or _default_name(pid),
                # A partial edit retains the effective protocol, including
                # the registry default when no override has been saved yet.
                protocol=(body.protocol if body.protocol is not None else
                          get_provider(pid).protocol),
                api_key=body.api_key
                if body.api_key is not None else cur.get("api_key"),
                base_url=body.base_url
                if body.base_url is not None else cur.get("base_url"),
                models=cur.get("models", []),
            )
            active_provider, active_model = model_link.active_model()
            if active_provider == pid and active_model:
                model_link.set_active_model(pid, active_model)
    side = {}
    if body.enabled is not None:
        side["enabled"] = body.enabled
    if body.default_generation_params is not None:
        side["default_generation_params"] = body.default_generation_params
    if side:
        sidecar.merge("providers", pid, side)
    if body.default_generation_params is not None:
        # See models.update_model: a live agent holds the generation config it
        # was built with, so an edit has to invalidate it or it applies only to
        # conversations started afterwards.
        from app.backends.ms_agent.runtime import registry

        registry.mark_all_stale()
    return get_provider(pid)


@locked(lambda *args, **kwargs: Path(home()) / "settings.json")
def delete_provider(pid: str) -> None:
    with settings_lock():
        msm = _msm()
        custom = msm.list_custom_providers()
        if pid not in custom:
            if pid in _builtin_ids():
                raise BadRequest("Built-in providers cannot be deleted.")
            raise NotFound("Provider not found.")
        model_names = list(custom.get(pid, {}).get("models", []))
        msm.remove_provider(pid)
    for name in model_names:
        sidecar.drop("models", encode_model_id(pid, name))
    sidecar.drop("providers", pid)


def get_provider_secret(pid: str) -> tuple[str, str, str]:
    """Return (base_url, protocol, plaintext api_key) for model discovery.

    custom: read the plaintext api_key from settings.json; builtin: spec
    default base_url + protocol, with any credential override's api_key.
    Raises NotFound if the provider does not exist.
    """
    with settings_lock():
        custom = _msm().list_custom_providers()
        if pid in _builtin_ids():
            spec = next(s for s in _specs() if s.name == pid)
            override = custom.get(pid, {}) or {}
            base_url = override.get("base_url") or spec.default_base_url or ""
            protocol = _protocol(spec.transport)
            return base_url, protocol, override.get("api_key", "") or ""
        if pid in custom:
            entry = custom[pid] or {}
            protocol = entry.get("protocol")
            protocol = protocol if protocol in ("openai",
                                                "anthropic") else "openai"
            return entry.get("base_url", "") or "", protocol, entry.get(
                "api_key", "") or ""
    raise NotFound("Provider not found.")
