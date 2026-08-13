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
    from ms_agent.personalization import PersonalizationConfig

    with settings_lock():
        # default_model_id arrives as a base64 Model.id; decode and point the active
        # model (llm block + default_model + catalog) at it so chat actually uses it.
        if body.default_model_id:
            try:
                provider, model = decode_model_id(body.default_model_id)
                model_link.set_active_model(provider, model)
            except Exception:
                pass

        ps = _ps()
        cur = ps.load()
        ps.save(
            PersonalizationConfig(
                global_instruction=cur.global_instruction,  # preserve
                memory_enabled=body.default_memory_enabled,
                memory_backend=body.default_memory_backend,
            )
        )
    sidecar.put("agent_settings", "global_mcp_auto_attach", body.global_mcp_auto_attach)
    sidecar.put("agent_settings", "global_skill_auto_attach", body.global_skill_auto_attach)
    sidecar.put(
        "agent_settings",
        "memory_models",
        {
            "llm_provider_id": body.memory_llm_provider_id,
            "llm_model": body.memory_llm_model,
            "embed_mode": body.memory_embed_mode,
            "embed_provider_id": body.memory_embed_provider_id,
            "embed_model": body.memory_embed_model,
            "recall_top_k": body.memory_recall_top_k,
        },
    )
    return get_settings()
