from fastapi import APIRouter, HTTPException

from app.core import store
from app.core.envelope import EnvelopeRoute
from app.core.settings import settings
from app.schemas.model import Model, ModelCreate, ModelUpdate

router = APIRouter(prefix="/api/models", tags=["models"],
                   route_class=EnvelopeRoute)


def _ms() -> bool:
    return settings.agent_backend == "ms_agent"


@router.get("")
def list_models(provider_id: str | None = None) -> list[Model]:
    if _ms():
        from app.backends.ms_agent import models

        return models.list_models(provider_id)
    rows = list(store.models.values())
    if provider_id is not None:
        rows = [m for m in rows if m["provider_id"] == provider_id]
    rows.sort(key=lambda m: m["created_at"])
    return [Model.model_validate(m) for m in rows]


@router.post("", status_code=201)
def create_model(body: ModelCreate) -> Model:
    if _ms():
        from app.backends.ms_agent import models

        return models.create_model(body)
    if body.provider_id not in store.providers:
        raise HTTPException(400, "unknown provider")
    mid = store.new_id("md-")
    row = {
        "id": mid,
        "provider_id": body.provider_id,
        "name": body.name,
        "display_name": body.display_name or body.name,
        "is_builtin": False,
        "advanced_params": body.advanced_params,
        "created_at": store.now(),
    }
    store.models[mid] = row
    return Model.model_validate(row)


@router.patch("/{model_id}")
def update_model(model_id: str, body: ModelUpdate) -> Model:
    if _ms():
        from app.backends.ms_agent import models

        return models.update_model(model_id, body)
    row = store.models.get(model_id)
    if not row:
        raise HTTPException(404, "model not found")
    if body.display_name is not None:
        row["display_name"] = body.display_name
    if body.advanced_params is not None:
        row["advanced_params"] = body.advanced_params
    return Model.model_validate(row)


@router.delete("/{model_id}", status_code=204)
def delete_model(model_id: str) -> None:
    if _ms():
        from app.backends.ms_agent import models

        return models.delete_model(model_id)
    row = store.models.get(model_id)
    if not row:
        raise HTTPException(404, "model not found")
    if row["is_builtin"]:
        raise HTTPException(400, "cannot delete builtin model")
    del store.models[model_id]
