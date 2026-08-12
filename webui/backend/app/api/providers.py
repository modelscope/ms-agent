from fastapi import APIRouter, HTTPException

from app.core.envelope import EnvelopeRoute
from app.schemas.provider import Provider, ProviderCreate, ProviderUpdate

router = APIRouter(prefix="/api/providers", tags=["providers"],
                   route_class=EnvelopeRoute)


@router.get("")
def list_providers() -> list[Provider]:
    from app.backends.ms_agent import providers

    return providers.list_providers()


@router.post("", status_code=201)
def create_provider(body: ProviderCreate) -> Provider:
    from app.backends.ms_agent import providers

    return providers.create_provider(body)


@router.get("/{provider_id}")
def get_provider(provider_id: str) -> Provider:
    from app.backends.ms_agent import providers

    return providers.get_provider(provider_id)


@router.patch("/{provider_id}")
def update_provider(provider_id: str, body: ProviderUpdate) -> Provider:
    from app.backends.ms_agent import providers

    return providers.update_provider(provider_id, body)


@router.delete("/{provider_id}", status_code=204)
def delete_provider(provider_id: str) -> None:
    from app.backends.ms_agent import providers

    return providers.delete_provider(provider_id)


@router.get("/{provider_id}/available-models")
def available_models(provider_id: str) -> list[str]:
    """Best-effort model-id discovery via the provider's standard /models
    endpoint. Returns [] on any failure (missing key, network error, etc.)."""
    from app.core.model_discovery import fetch_model_ids

    from app.backends.ms_agent import providers

    base_url, protocol, api_key = providers.get_provider_secret(
        provider_id)
    # fetch_model_ids is itself best-effort (missing key, network error, non-2xx
    # and non-standard payloads all degrade to []), so its result is returned
    # as-is: the UI falls back to free-form manual entry on an empty list.
    return fetch_model_ids(base_url, protocol, api_key)
