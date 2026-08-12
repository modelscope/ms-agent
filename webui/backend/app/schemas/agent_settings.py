from typing import Literal

from pydantic import BaseModel


MemoryBackend = Literal["file", "vector"]

# Where vector-memory embeddings come from:
# - "provider": an OpenAI-compatible /embeddings endpoint. Which one is
#   resolved from memory_embed_provider_id, falling back to the conversation
#   provider when unset (and to the local model when THAT provider serves no
#   embeddings — about half of them don't).
# - "local": fastembed ONNX model on this machine, no network.
MemoryEmbedMode = Literal["provider", "local"]


class AgentSettings(BaseModel):
    default_provider_id: str | None = None
    default_model_id: str | None = None

    # Inherited by newly-created projects.
    default_memory_enabled: bool = True
    default_memory_backend: MemoryBackend = "file"

    # Vector-memory model configuration. All None = follow the conversation
    # model/provider — explicit values pin fact extraction / embeddings to a
    # model of the user's choosing, independent of what chat uses.
    memory_llm_provider_id: str | None = None
    memory_llm_model: str | None = None
    memory_embed_mode: MemoryEmbedMode = "provider"
    memory_embed_provider_id: str | None = None
    memory_embed_model: str | None = None
    memory_recall_top_k: int | None = None

    # Global auto-attach masters — projects can override per-scope.
    global_mcp_auto_attach: bool = True
    global_skill_auto_attach: bool = True
