"""Recovery remains available while normal API operations are paused."""
import logging
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.envelope import EnvelopeRoute

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recovery", tags=["recovery"], route_class=EnvelopeRoute)


class RecoveryStatus(BaseModel):
    required: bool
    backup_path: str | None = None
    error: Literal["backup_failed", "repair_failed", "startup_failed"] | None = None


class RepairRequest(BaseModel):
    confirm: Literal[True]


@router.get("")
def status(request: Request) -> RecoveryStatus:
    return request.app.state.recovery


@router.post("/default-project")
def repair_default_project(body: RepairRequest, request: Request) -> RecoveryStatus:
    from app.backends.ms_agent.bootstrap import bootstrap
    from app.backends.ms_agent.common import pm

    state = request.app.state
    with state.recovery_lock:
        if not state.recovery.required:
            return state.recovery
        try:
            backup = pm().repair_default_project()
        except OSError:
            logger.exception("Default project backup failed")
            state.recovery = state.recovery.model_copy(update={"error": "backup_failed"})
            return state.recovery
        except (ValueError, RuntimeError):
            logger.exception("Default project repair failed")
            state.recovery = state.recovery.model_copy(update={"error": "repair_failed"})
            return state.recovery
        backup_path = str(backup) if backup else state.recovery.backup_path
        try:
            bootstrap()
        except Exception:
            logger.exception("Initialization after project recovery failed")
            state.recovery = RecoveryStatus(required=True, backup_path=backup_path, error="startup_failed")
        else:
            state.recovery = RecoveryStatus(required=False, backup_path=backup_path)
        return state.recovery
