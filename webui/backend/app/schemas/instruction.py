from datetime import datetime

from pydantic import BaseModel


class Instruction(BaseModel):
    scope: str
    content: str = ""
    updated_at: datetime


class InstructionUpsert(BaseModel):
    content: str = ""
