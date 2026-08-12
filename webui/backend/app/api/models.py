from fastapi import APIRouter, HTTPException

from app.core.envelope import EnvelopeRoute
from app.schemas.model import Model, ModelCreate, ModelUpdate

router = APIRouter(prefix="/api/models", tags=["models"],
                   route_class=EnvelopeRoute)


@router.get("")
def list_models(provider_id: str | None = None) -> list[Model]:
    from app.backends.ms_agent import models

    return models.list_models(provider_id)


@router.post("", status_code=201)
def create_model(body: ModelCreate) -> Model:
    from app.backends.ms_agent import models

    return models.create_model(body)


@router.patch("/{model_id}")
def update_model(model_id: str, body: ModelUpdate) -> Model:
    from app.backends.ms_agent import models

    return models.update_model(model_id, body)


@router.delete("/{model_id}", status_code=204)
def delete_model(model_id: str) -> None:
    from app.backends.ms_agent import models

    return models.delete_model(model_id)
