from fastapi import APIRouter, HTTPException

from app.core.envelope import EnvelopeRoute
from app.schemas.instruction import Instruction, InstructionUpsert

router = APIRouter(prefix="/api/instructions", tags=["instructions"],
                   route_class=EnvelopeRoute)


@router.get("")
def get_instruction(scope: str) -> Instruction:
    from app.backends.ms_agent import instructions

    return instructions.get_instruction(scope)


@router.put("")
def upsert_instruction(scope: str, body: InstructionUpsert) -> Instruction:
    from app.backends.ms_agent import instructions

    return instructions.upsert_instruction(scope, body)
