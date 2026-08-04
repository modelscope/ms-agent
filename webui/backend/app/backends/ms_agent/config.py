"""Assemble the per-session run config and construct the LLMAgent (Route A).

Mirrors ms_agent/tui/app.py: ConfigResolver.resolve() for the layered config
(framework defaults -> settings.json -> project patch -> session overrides),
then route-A shaping (interactive lifecycle, streaming, session-log dir), then
the managed MCP/skills bridge, then LLMAgent with the UI seams injected.
"""
from __future__ import annotations

import logging
import os

from app.backends.ms_agent.common import home

logger = logging.getLogger("app.ms_agent.config")


def _apply_webui_defaults(config):
    """Make a newly-created WebUI session useful without requiring a hand-written
    agent.yaml. Project/global config can still override these keys."""
    from omegaconf import OmegaConf

    if OmegaConf.select(config, "skills", default=None) is None:
        OmegaConf.update(config, "skills", {}, merge=True)
    for key, value in {
        "skills.prompt_injection": "all",
        "skills.auto_discover": True,
        "skills.enable_manage": False,
        "skills.disabled": [],
        # Skill changes are announced as in-conversation <system-reminder>
        # notices (chat._maybe_skill_notice); the SDK then keeps the system
        # prompt byte-stable per session (head_refresh_enabled=False) so the
        # provider prefix cache never breaks on a skill change.
        "skills.update_notice": True,
    }.items():
        if OmegaConf.select(config, key, default=None) is None:
            OmegaConf.update(config, key, value, merge=True)
    # Builtin repo tools live in settings.json's `tools` block and are merged by
    # the SDK ConfigResolver (multi-level resolve); nothing to inject here.
    return config


def _vector_memory_available() -> bool:
    """The 'vector' project backend maps to the SDK's mem0 adapter (`mem0ai`
    is a backend dependency; the guard keeps a broken install non-fatal)."""
    try:
        import mem0  # noqa: F401

        return True
    except Exception:
        return False


# DashScope OpenAI-compatible embeddings (probed: 1024 dims). The embedder must
# come from a provider that actually serves /embeddings — the active chat model
# (e.g. DeepSeek) usually does not.
_EMBEDDER_MODEL = "text-embedding-v4"
_EMBEDDER_DIMS = 1024


def _read_settings() -> dict:
    import json

    try:
        with open(os.path.join(home(), "settings.json"), encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _mem0_options(project) -> dict | None:
    """mem0 backend options for a 'vector' project.

    - embedder: the DashScope-compatible provider from settings.json
      (dashscope/openai entries), falling back to OPENAI_* env.
    - llm (fact extraction): the active chat model from settings.json.llm.
    - vector_store: local on-disk qdrant under the project memory dir
      (embedded mode — no server).
    Returns None when no embeddings-capable credentials exist."""
    from ms_agent.project.paths import memory_dir

    s = _read_settings()
    emb_creds = None
    for pid in ("dashscope", "openai"):
        p = (s.get("providers") or {}).get(pid) or {}
        if p.get("api_key") and p.get("base_url"):
            emb_creds = {"api_key": p["api_key"], "openai_base_url": p["base_url"]}
            break
    if emb_creds is None and os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_BASE_URL"):
        emb_creds = {
            "api_key": os.environ["OPENAI_API_KEY"],
            "openai_base_url": os.environ["OPENAI_BASE_URL"],
        }
    if emb_creds is None:
        return None

    options: dict = {
        "embedder": {
            "provider": "openai",
            "config": {
                **emb_creds,
                "model": _EMBEDDER_MODEL,
                "embedding_dims": _EMBEDDER_DIMS,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "path": str(memory_dir(project.path) / "qdrant"),
                "on_disk": True,
                "collection_name": "webui_memory",
                "embedding_model_dims": _EMBEDDER_DIMS,
            },
        },
    }
    llm = s.get("llm") or {}
    if llm.get("api_key") and llm.get("base_url") and llm.get("model"):
        options["llm"] = {
            "provider": "openai",
            "config": {
                "model": llm["model"],
                "api_key": llm["api_key"],
                "openai_base_url": llm["base_url"],
            },
        }
    return options


def _apply_webui_memory(config, project):
    """Wire the project's memory toggle to the SDK's unified memory.

    Enabled -> `memory.unified_memory`, namespaced per project and rooted
    under `<project.path>/.ms_agent/memory/` (via output_dir):
    - memory_backend "file"   -> FileBasedBackend (MEMORY.md, default);
      writes happen through the model's `memory` tool.
    - memory_backend "vector" -> Mem0Backend (mem0 + local qdrant); writes
      happen through mem0's per-round fact extraction, so the node also
      activates the agent's `add_after_step` ingestion hook.
    Falls back to file (with a warning) when mem0/embeddings are unavailable.
    Disabled -> drop any lower-layer memory block so the WebUI toggle is
    authoritative (no memory tools, no injection)."""
    from omegaconf import OmegaConf

    if getattr(project, "memory_enabled", False):
        pid = project.id or "default"
        backend = getattr(project, "memory_backend", None) or "file"
        node: dict = {
            "storage": {"backend": "file"},
            "namespace": {"user_id": pid},
            # Legacy-shaped fields some agent paths read directly:
            # SharedMemoryManager keying + add_memory()'s per-step ingestion
            # (get_memory_meta_safe requires an explicit add_after_step block).
            "user_id": pid,
            "add_after_step": {"user_id": pid},
        }
        if backend == "vector":
            options = _mem0_options(project) if _vector_memory_available() else None
            if options is not None:
                node["storage"]["backend"] = "mem0"
                node["mem0"] = options
            else:
                logger.warning(
                    "memory_backend 'vector' unavailable (mem0ai missing or no "
                    "embeddings provider); falling back to file for project %s",
                    pid,
                )
        elif backend != "file":
            logger.warning("unknown memory_backend %r; using file", backend)
        OmegaConf.update(config, "memory.unified_memory", node, merge=True)
        # The WebUI drives unified_memory only. Legacy memory types leaking in
        # from project/global config (notably `default_memory`, whose mem0 v1
        # calls break against the mem0 2.x we ship) are dropped, not merged.
        mem_node = OmegaConf.select(config, "memory", default=None)
        for key in [k for k in (mem_node or {}) if k != "unified_memory"]:
            logger.warning("dropping legacy memory type %r (webui uses unified_memory)", key)
            del mem_node[key]
    elif OmegaConf.select(config, "memory", default=None) is not None:
        del config["memory"]
    return config


# Read-only / plan-machinery tools that restricted mode lets through without a
# confirmation card. Writes (write_file/edit_file), shell (code_executor) and
# MCP tools are NOT whitelisted, so each surfaces an authorization card.
_PERMISSION_WHITELIST = [
    "file_system---read_file",
    "file_system---grep",
    "file_system---glob",
    "todo_list---*",
    "unified_memory---*",
    "skills---*",
]


def _apply_webui_permission(config, project_mode: str | None = None):
    """Default this phase to the SDK's restricted (ask) mode.

    Non-whitelisted tools suspend on the session's WebPermissionHandler, which
    surfaces an authorization card over SSE and times out to deny. Explicit
    `permission.*` from settings.json / project config still wins — we only
    fill blanks. ``project_mode`` is the UI's per-project override (the
    composer's restricted/full-access selector, stored in the project sidecar):
    an explicit user choice, so it beats the fill-blanks default."""
    from omegaconf import OmegaConf

    if project_mode in ("restricted", "auto"):
        OmegaConf.update(config, "permission.mode", project_mode, merge=True)
    elif OmegaConf.select(config, "permission.mode", default=None) is None:
        OmegaConf.update(config, "permission.mode", "restricted", merge=True)
    if OmegaConf.select(config, "permission.whitelist", default=None) is None:
        OmegaConf.update(
            config, "permission.whitelist", list(_PERMISSION_WHITELIST), merge=True
        )
    return config


def thinking_default(protocol: str, provider: str, model: str = "") -> bool:
    """Whether ``extra_body.enable_thinking`` is ON by DEFAULT for this
    provider/model/protocol, before any user override. Single source of truth:
    used by build shaping (``_apply_model_compatibility``) and surfaced to the
    model-settings UI (``mapping.builtin_provider_to_schema``) so the effective
    default is visible in the generation-params JSON.

    Thinking defaults on for the Anthropic protocol (where the flag maps to the
    Messages API ``thinking`` param), for Qwen models, and for DashScope /
    ModelScope; other OpenAI-compatible providers default it off (they stream
    ``reasoning_content`` natively or reject the flag)."""
    protocol = (protocol or "").lower()
    provider = (provider or "").lower()
    model = (model or "").lower()
    return (
        protocol == "anthropic"
        or "qwen" in model
        or provider in {"dashscope", "modelscope"}
    )


def _apply_model_compatibility(config):
    """Normalize provider/model quirks that break the WebUI's shared defaults."""
    import json

    from omegaconf import OmegaConf

    provider = str(OmegaConf.select(config, "llm.service", default="") or "").lower()
    model = str(OmegaConf.select(config, "llm.model", default="") or "").lower()
    temperature_enabled = False
    webui_params = _webui_generation_params(provider, model)
    try:
        with open(os.path.join(home(), "settings.json"), encoding="utf-8") as fh:
            temperature_enabled = bool(
                ((json.load(fh).get("llm") or {}).get("temperature_enabled"))
            )
    except (OSError, json.JSONDecodeError):
        temperature_enabled = False

    # The SDK's base agent.yaml sets temperature=0.3 as a generic default. Many
    # OpenAI-compatible models (including deepseek-v4-pro and kimi-k2.5 here)
    # reject that value. In the WebUI, temperature should only be sent when the
    # user explicitly enables/configures it.
    temperature_explicit = temperature_enabled or "temperature" in webui_params
    if not temperature_explicit:
        generation_config = OmegaConf.select(config, "generation_config", default=None)
        if generation_config is not None and "temperature" in generation_config:
            del generation_config["temperature"]

    # Some current OpenAI-compatible reasoning/code models reject arbitrary
    # temperature values and require temperature=1 when the field is present.
    if temperature_explicit and (
        model.startswith("deepseek-v4")
        or (provider == "deepseek" and "deepseek-v4" in model)
        or model.startswith("kimi-k2")
        or (provider == "kimi" and "kimi-k2" in model)
    ):
        OmegaConf.update(config, "generation_config.temperature", 1.0, merge=True)

    # enable_thinking is a Qwen/DashScope-style extra_body flag. DeepSeek and
    # other OpenAI-compatible providers either stream reasoning_content directly
    # or do not support the flag; default it off for them so we don't send an
    # unsupported extra — UNLESS the user explicitly configured thinking params
    # for this provider/model (per-provider thinking control via the WebUI model
    # settings: provider default_generation_params / model advanced_params, which
    # flow into generation_config via _apply_webui_generation_params).
    # On the Anthropic protocol, enable_thinking IS the switch that turns on the
    # provider's thinking mode (mapped to the Messages API `thinking` param), so
    # keep it — the transport now replays thinking blocks through tool calls.
    protocol = str(
        OmegaConf.select(config, "llm.protocol", default="") or "").lower()
    extra_body = webui_params.get("extra_body")
    thinking_user_set = isinstance(extra_body, dict) and (
        "enable_thinking" in extra_body or "thinking_budget" in extra_body
    )
    if not thinking_user_set and not thinking_default(protocol, provider, model):
        OmegaConf.update(
            config,
            "generation_config.extra_body.enable_thinking",
            False,
            merge=True,
        )
    return config


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` (nested dicts merged, not
    replaced), returning a new dict. Non-dict values (and dict-vs-scalar
    mismatches) are overwritten by ``override``."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _webui_generation_params(provider: str, model: str) -> dict:
    """Provider defaults + model overrides stored in WebUI sidecar metadata.

    Merged deeply so a model-level nested dict (e.g. ``extra_body``) refines the
    provider-level one rather than replacing it — otherwise a model that sets a
    single ``extra_body`` key would drop the provider's other ``extra_body``
    entries (e.g. ``enable_thinking``)."""
    if not provider or not model:
        return {}
    from app.backends.ms_agent import sidecar
    from app.backends.ms_agent.mapping import encode_model_id

    provider_params = (
        sidecar.get("providers", provider) or {}
    ).get("default_generation_params") or {}
    model_params = (
        sidecar.get("models", encode_model_id(provider, model)) or {}
    ).get("advanced_params") or {}
    params: dict = {}
    if isinstance(provider_params, dict):
        params = _deep_merge(params, provider_params)
    if isinstance(model_params, dict):
        params = _deep_merge(params, model_params)
    return params


def _apply_webui_generation_params(config):
    """Apply generation params configured from the WebUI model settings page."""
    from omegaconf import OmegaConf

    provider = str(OmegaConf.select(config, "llm.service", default="") or "")
    model = str(OmegaConf.select(config, "llm.model", default="") or "")
    for key, value in _webui_generation_params(provider, model).items():
        OmegaConf.update(config, f"generation_config.{key}", value, merge=True)
    return config


def session_dir(project, session) -> str:
    from ms_agent.project.paths import global_projects_root

    return str(global_projects_root() / project.id / "sessions" / session.id)


def session_has_history(project, session) -> bool:
    from ms_agent.project import SessionManager

    try:
        log = SessionManager(project).get_session_log(session)
        return bool(log.get_all_messages())
    except Exception:
        return False


# UI/meta fields on a managed MCP entry that must not reach the runtime server
# config (mirrors ms_agent.tui.managed_config._MCP_META).
_MCP_META = frozenset({
    "source", "meta", "_scope", "mcp", "implementation", "trust_remote_code", "_removed",
})


def _mcp_reachable(server: dict, timeout: float = 2.0) -> bool:
    """Cheap pre-flight so an unreachable MCP can't break the chat turn.

    Remote servers: TCP-connect to host:port. stdio servers: the command must
    resolve on PATH (or be an existing file). Reachable-but-broken servers still
    pass (rare); the common 'wrong/dead URL or missing command' case is dropped.
    """
    import shutil
    import socket
    from urllib.parse import urlparse

    url = server.get("url")
    if url:
        try:
            u = urlparse(url)
            if not u.hostname:
                return False
            port = u.port or (443 if u.scheme in ("https", "wss") else 80)
            with socket.create_connection((u.hostname, port), timeout=timeout):
                return True
        except Exception:
            return False
    command = server.get("command")
    if command:
        return bool(shutil.which(command)) or os.path.isfile(command)
    return True  # unknown shape — don't drop


def _healthy_mcp_config(mcp_config: dict | None) -> dict:
    servers = (mcp_config or {}).get("mcpServers") or {}
    healthy = {name: s for name, s in servers.items() if _mcp_reachable(s)}
    dropped = set(servers) - set(healthy)
    if dropped:
        logger.warning("skipping unreachable MCP server(s): %s", ", ".join(sorted(dropped)))
    return {"mcpServers": healthy} if healthy else {}


def build_agent(project, session, *, event_sink, input_source, mcp_config=None,
                permission_handler=None):
    from ms_agent.agent.llm_agent import LLMAgent
    from ms_agent.config import ConfigResolver
    from ms_agent.permission.handler import AutoPermissionHandler
    from ms_agent.tui.managed_config import (
        merge_skills_into_config,
        resolve_mcp_config,
    )
    from omegaconf import OmegaConf

    h = home()
    resolver = ConfigResolver(global_dir=h, project_root=project.path)
    sdir = session_dir(project, session)
    session_overrides = {
        # ① align the runtime SessionLog with the SessionManager session dir
        "session_log": {
            "dir": sdir,
            "session_key": session.session_key,
        },
        # ② project-level personalization instruction
        "personalization": {"project_instruction": project.instruction or ""},
        # ③ per-session todo plan: the todo_list tool joins these onto
        # output_dir, and an absolute path wins the join — so each session's
        # plan lives beside its session log instead of a project-shared
        # <workspace>/plan.json (which made concurrent sessions clobber each
        # other's plans). read_plan() resolves the same path.
        "tools": {
            "todo_list": {
                "plan_filename": os.path.join(sdir, "plan.json"),
                "plan_md_filename": os.path.join(sdir, "plan.md"),
            },
        },
    }
    cfg = resolver.resolve(
        agent_config=None,
        project_path=project.path,
        session_overrides=session_overrides,
    )
    cfg = _apply_webui_defaults(cfg)
    cfg = _apply_webui_memory(cfg, project)
    # Restricted-by-default permission; the project sidecar's explicit
    # restricted/full-access choice (composer selector) overrides.
    from app.backends.ms_agent import sidecar

    meta = sidecar.get("projects", project.id, {}) or {}
    cfg = _apply_webui_permission(cfg, meta.get("permission_mode"))

    # Route-A shaping (see tui/app.py::_prepare_config).
    shaping = {
        "interactive": True,  # non-TTY backend: enable interactive lifecycle
        # Route chat through the data-driven provider layer (ms_agent/llm/
        # router.py) rather than the legacy hard-coded LLM classes. The new
        # layer supports mid-stream interrupt() — abandoning a turn closes the
        # upstream streaming response so the server stops generating instead of
        # running to completion into a dropped connection. The legacy path is
        # being deprecated.
        "llm.use_provider_router": True,
        "generation_config.stream": True,
        "generation_config.stream_output": True,
        "generation_config.show_reasoning": True,
        "generation_config.extra_body.enable_thinking": True,
        "session_log.enabled": True,
        "output_dir": project.path,
        "max_chat_round": 1000,
    }
    for key, value in shaping.items():
        OmegaConf.update(cfg, key, value, merge=True)
    # Propagate the active provider's wire protocol (openai | anthropic) so the
    # provider layer picks the matching transport. A provider may point at
    # another vendor's compatible endpoint (e.g. DeepSeek's /anthropic gateway),
    # where the endpoint's protocol differs from the service's default transport.
    _service = str(OmegaConf.select(cfg, "llm.service", default="") or "")
    _protocol = (
        (_read_settings().get("providers") or {}).get(_service) or {}
    ).get("protocol")
    if _protocol:
        OmegaConf.update(cfg, "llm.protocol", _protocol)
    cfg = _apply_webui_generation_params(cfg)
    cfg = _apply_model_compatibility(cfg)
    # Drop any listed InputCallback so restarts never double-register it.
    cbs = [c for c in list(getattr(cfg, "callbacks", []) or []) if c != "input_callback"]
    OmegaConf.update(cfg, "callbacks", cbs, merge=False)

    # Bridge managed skill sources into the runtime (reused SDK/TUI helper).
    cfg = merge_skills_into_config(cfg, h, project.path)

    # MCP: use the SDK's standard mcp_config path (enabled servers only) — far
    # more robust to invalid servers than injecting an MCPRuntime (whose remote
    # client teardown throws cross-task anyio errors). The registry pre-probes
    # servers (connect+initialize) and passes only healthy ones as `mcp_config`;
    # fall back to a cheap TCP check for direct callers (tests). Live
    # enable/disable is sacrificed — a toggle applies on the next session build.
    if mcp_config is None:
        mcp_config = _healthy_mcp_config(resolve_mcp_config(h, project.path, None))

    resume = session_has_history(project, session)
    agent = LLMAgent(
        cfg,
        event_sink=event_sink,
        input_source=input_source,
        mcp_config=mcp_config or {},
        load_cache=resume,
    )
    # The runtime passes a WebPermissionHandler (ask -> SSE authorization card
    # -> POST /api/chat/permission resolve, deny on timeout). Direct callers
    # (tests/scripts) get auto-allow so restricted mode can't hang them on a
    # CLI prompt.
    agent.set_permission_handler(permission_handler or AutoPermissionHandler())
    return agent
