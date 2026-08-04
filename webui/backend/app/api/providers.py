from fastapi import APIRouter, HTTPException

from app.core import store
from app.core.envelope import EnvelopeRoute
from app.core.settings import settings
from app.schemas.provider import Provider, ProviderCreate, ProviderUpdate

router = APIRouter(prefix="/api/providers", tags=["providers"],
                   route_class=EnvelopeRoute)


def _ms() -> bool:
    return settings.agent_backend == "ms_agent"


def _mask(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}****{api_key[-4:]}"


@router.get("")
def list_providers() -> list[Provider]:
    if _ms():
        from app.backends.ms_agent import providers

        return providers.list_providers()
    rows = sorted(
        store.providers.values(),
        key=lambda p: (p["kind"] != "builtin", p["created_at"]),
    )
    return [Provider.model_validate(p) for p in rows]


@router.post("", status_code=201)
def create_provider(body: ProviderCreate) -> Provider:
    if _ms():
        from app.backends.ms_agent import providers

        return providers.create_provider(body)
    if body.id in store.providers:
        raise HTTPException(409, "provider id already exists")
    row = {
        "id": body.id,
        "kind": "custom",
        "name": body.name,
        "base_url": body.base_url,
        "api_key_masked": "",
        "api_key": "",
        "protocol": body.protocol,
        "enabled": True,
        "default_generation_params": body.default_generation_params,
        "created_at": store.now(),
    }
    store.providers[body.id] = row
    return Provider.model_validate(row)


@router.get("/{provider_id}")
def get_provider(provider_id: str) -> Provider:
    if _ms():
        from app.backends.ms_agent import providers

        return providers.get_provider(provider_id)
    row = store.providers.get(provider_id)
    if not row:
        raise HTTPException(404, "provider not found")
    return Provider.model_validate(row)


@router.patch("/{provider_id}")
def update_provider(provider_id: str, body: ProviderUpdate) -> Provider:
    if _ms():
        from app.backends.ms_agent import providers

        return providers.update_provider(provider_id, body)
    row = store.providers.get(provider_id)
    if not row:
        raise HTTPException(404, "provider not found")
    if body.name is not None:
        row["name"] = body.name
    if body.base_url is not None:
        row["base_url"] = body.base_url
    if body.protocol is not None:
        row["protocol"] = body.protocol
    if body.enabled is not None:
        row["enabled"] = body.enabled
    if body.api_key is not None:
        row["api_key_masked"] = _mask(body.api_key)
        row["api_key"] = body.api_key
    if body.default_generation_params is not None:
        row["default_generation_params"] = body.default_generation_params
    return Provider.model_validate(row)


@router.delete("/{provider_id}", status_code=204)
def delete_provider(provider_id: str) -> None:
    if _ms():
        from app.backends.ms_agent import providers

        return providers.delete_provider(provider_id)
    row = store.providers.get(provider_id)
    if not row:
        raise HTTPException(404, "provider not found")
    if row["kind"] == "builtin":
        raise HTTPException(400, "cannot delete builtin provider")
    del store.providers[provider_id]
    # Cascade: drop models bound to this provider.
    for mid in [
            m["id"] for m in store.models.values()
            if m["provider_id"] == provider_id
    ]:
        del store.models[mid]


@router.get("/{provider_id}/available-models")
def available_models(provider_id: str) -> list[str]:
    """Best-effort model-id discovery via the provider's standard /models
    endpoint. Returns [] on any failure (missing key, network error, etc.)."""
    from app.core.model_discovery import fetch_model_ids

    if _ms():
        from app.backends.ms_agent import providers

        base_url, protocol, api_key = providers.get_provider_secret(
            provider_id)
    else:
        row = store.providers.get(provider_id)
        if not row:
            raise HTTPException(404, "provider not found")
        base_url = row.get("base_url", "")
        protocol = row.get("protocol", "openai")
        api_key = row.get("api_key", "")
    return fetch_model_ids(base_url, protocol, api_key)
