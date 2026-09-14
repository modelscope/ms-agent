"""Agent-settings adapter — default model (ModelSettingsManager) + memory
defaults (PersonalizationSettings) + auto-attach masters (sidecar)."""
from __future__ import annotations

from app.backends.ms_agent import model_link, sidecar
from app.backends.ms_agent.common import home
from app.backends.ms_agent.mapping import decode_model_id, encode_model_id
from app.backends.ms_agent.settings_store import settings_lock
from app.schemas.agent_settings import AgentSettings


def _ps():
    from ms_agent.personalization import PersonalizationSettings

    return PersonalizationSettings(global_dir=home())


def get_settings() -> AgentSettings:
    # default_model_id is a base64 Model.id (provider+name), matching /api/models
    # so the frontend can highlight the selected model.
    with settings_lock():
        provider, model = model_link.active_model()
        default_model_id = encode_model_id(provider, model) if (provider and model) else None
        cfg = _ps().load()
    backend = cfg.memory_backend if cfg.memory_backend in ("file", "vector") else "file"
    mem_cfg = sidecar.get("agent_settings", "memory_models", {}) or {}
    embed_mode = mem_cfg.get("embed_mode")
    return AgentSettings(
        default_provider_id=provider,
        default_model_id=default_model_id,
        default_memory_enabled=bool(cfg.memory_enabled),
        default_memory_backend=backend,
        memory_llm_provider_id=mem_cfg.get("llm_provider_id"),
        memory_llm_model=mem_cfg.get("llm_model"),
        memory_embed_mode=embed_mode if embed_mode in ("provider", "local") else "provider",
        memory_embed_provider_id=mem_cfg.get("embed_provider_id"),
        memory_embed_model=mem_cfg.get("embed_model"),
        memory_recall_top_k=mem_cfg.get("recall_top_k"),
        global_mcp_auto_attach=sidecar.get("agent_settings", "global_mcp_auto_attach", True),
        global_skill_auto_attach=sidecar.get("agent_settings", "global_skill_auto_attach", True),
    )


def update_settings(body: AgentSettings) -> AgentSettings:
    from app.backends.errors import BadRequest
    from ms_agent.utils.json_store import json_transaction
    from pathlib import Path

    patch = body.model_dump(exclude_unset=True)
    with settings_lock():
        if "default_model_id" in patch:
            if body.default_model_id:
                try:
                    provider, model = decode_model_id(body.default_model_id)
                except (ValueError, TypeError):
                    raise BadRequest("Invalid model selection.") from None
                from app.backends.ms_agent.session_models import validate_selection
                if "default_provider_id" in patch and body.default_provider_id not in (None, provider):
                    raise BadRequest("The selected model belongs to a different provider.")
                validate_selection(provider, model)
                model_link.set_active_model(provider, model)
            else:
                with json_transaction(Path(home()) / "settings.json") as data:
                    model_link.preserve_legacy_credentials(data)
                    data.pop("default_model", None)
                    data["llm"] = {}
        elif "default_provider_id" in patch:
            provider, _ = model_link.active_model()
            if body.default_provider_id != provider:
                raise BadRequest("Select a model together with its provider.")

        personalization = {
            key.removeprefix("default_"): value
            for key, value in patch.items()
            if key in ("default_memory_enabled", "default_memory_backend")
        }
        if personalization:
            _ps().update(**personalization)
        for key in ("global_mcp_auto_attach", "global_skill_auto_attach"):
            if key in patch:
                sidecar.put("agent_settings", key, patch[key])
        memory = {key.removeprefix("memory_"): value for key, value in patch.items()
                  if key.startswith("memory_")}
        if memory:
            sidecar.merge("agent_settings", "memory_models", memory)
        return get_settings()
