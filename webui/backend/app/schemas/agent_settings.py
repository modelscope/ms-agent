from typing import Literal

from pydantic import BaseModel


MemoryBackend = Literal["file", "vector"]


class AgentSettings(BaseModel):
    default_provider_id: str | None = None
    default_model_id: str | None = None

    # Inherited by newly-created projects.
    default_memory_enabled: bool = True
    default_memory_backend: MemoryBackend = "file"

    # Global auto-attach masters — projects can override per-scope.
    global_mcp_auto_attach: bool = True
    global_skill_auto_attach: bool = True
