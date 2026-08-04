from fastapi import APIRouter, HTTPException

from app.core import store
from app.core.envelope import EnvelopeRoute
from app.core.settings import settings
from app.schemas.instruction import Instruction, InstructionUpsert

router = APIRouter(prefix="/api/instructions", tags=["instructions"],
                   route_class=EnvelopeRoute)


def _ms() -> bool:
    return settings.agent_backend == "ms_agent"


def _validate_scope(scope: str) -> str:
    try:
        return store.scope_key(scope)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("")
def get_instruction(scope: str) -> Instruction:
    if _ms():
        from app.backends.ms_agent import instructions

        return instructions.get_instruction(scope)
    key = _validate_scope(scope)
    row = store.instructions.get(key)
    if row is None:
        row = {"scope": key, "content": "", "updated_at": store.now()}
    return Instruction.model_validate(row)


@router.put("")
def upsert_instruction(scope: str, body: InstructionUpsert) -> Instruction:
    if _ms():
        from app.backends.ms_agent import instructions

        return instructions.upsert_instruction(scope, body)
    key = _validate_scope(scope)
    row = {"scope": key, "content": body.content, "updated_at": store.now()}
    store.instructions[key] = row
    return Instruction.model_validate(row)
