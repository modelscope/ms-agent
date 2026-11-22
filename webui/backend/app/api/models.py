from fastapi import APIRouter, HTTPException

from app.core.envelope import EnvelopeRoute
from app.schemas.model import GenerationDefaults, Model, ModelCreate, ModelUpdate, ReasoningEffort

router = APIRouter(prefix="/api/models", tags=["models"],
                   route_class=EnvelopeRoute)


@router.get("")
def list_models(provider_id: str | None = None) -> list[Model]:
    from app.backends.ms_agent import models

    return models.list_models(provider_id)


# Declared before "/{model_id}" routes so the literal path is not swallowed by
# the id parameter.
@router.get("/generation-defaults")
def generation_defaults(provider_id: str, model: str = "",
                        reasoning_effort: ReasoningEffort | None = None) -> GenerationDefaults:
    """What the runtime will send for this provider/model before any override —
    the values the advanced-params editor pre-fills and explains."""
    from app.backends.ms_agent import models

    return models.generation_defaults(provider_id, model, reasoning_effort=reasoning_effort)


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
