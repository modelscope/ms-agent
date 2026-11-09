"""Thin WebUI adapter for the SDK's shared catalog cache."""
from fastapi import APIRouter
from app.core.envelope import EnvelopeRoute

router = APIRouter(prefix='/api/model-catalog', tags=['models'],
                   route_class=EnvelopeRoute)


@router.get('')
def catalog_status() -> dict:
    from ms_agent.llm.catalog_update import status
    return status()


@router.post('/update')
async def update_catalog() -> dict:
    from ms_agent.llm.catalog_update import status, update
    result = await update(force=True)
    return dict(status(), result=result['result'])
