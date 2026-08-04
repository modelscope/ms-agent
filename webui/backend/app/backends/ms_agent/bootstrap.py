"""ms_agent backend startup: home/env, default project, LLM settings seed.

Runs once at app boot (only when AGENT_BACKEND=ms_agent). Idempotent.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from app.core.settings import settings


def bootstrap() -> None:
    from app.backends.ms_agent.common import apply_home_env, home, pm

    from app.backends.ms_agent import model_link

    apply_home_env()
    _export_env()
    pm()  # ProjectManager.__init__ ensures ~/.ms_agent/projects + default project
    _seed_llm_settings(home())
    _seed_tools_settings(home())
    # Normalize the model link so the chat dropdown lists the active model and
    # default_model is a full "provider/model" (see model_link).
    model_link.ensure_link()


def _export_env() -> None:
    """Push backend credentials into the process env the SDK / MCP servers read."""
    for key, value in {
        "OPENAI_API_KEY": settings.openai_api_key,
        "OPENAI_BASE_URL": settings.openai_base_url,
        "EXA_API_KEY": settings.exa_api_key,
    }.items():
        if value and not os.environ.get(key):
            os.environ[key] = value


def _seed_llm_settings(home_dir: str) -> None:
    """Write settings.json `llm` from env when absent, so ConfigResolver yields a
    working model. Matches §3.1: llm.{provider,model,api_key,base_url}."""
    path = Path(home_dir) / "settings.json"
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    if "llm" in data:
        return  # never overwrite an existing config (e.g. a shared ~/.ms_agent)

    model = settings.ms_agent_llm_model
    if not model:
        return  # nothing to seed; rely on framework default + env credentials
    provider = settings.ms_agent_llm_provider or "openai"
    llm: dict = {"provider": provider, "model": model}
    if settings.openai_api_key:
        llm["api_key"] = settings.openai_api_key
    if settings.openai_base_url:
        llm["base_url"] = settings.openai_base_url
    data["llm"] = llm
    data.setdefault("default_model", f"{provider}/{model}")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# Builtin repo tools seeded into settings.json so they are default-enabled and
# toggleable through the standard multi-level config resolve (framework yaml ->
# settings.json -> project yaml -> session). Presence of a `tools.<id>` key
# enables it; add `enabled: false` to disable (honored by the SDK ToolManager).
_DEFAULT_TOOLS: dict = {
    "file_system": {
        "mcp": False,
        "include": ["read_file", "grep", "glob", "edit_file", "write_file"],
    },
    "todo_list": {"mcp": False},
    # Shell/terminal only. implementation must be the SDK's "python_env" (a
    # local Jupyter kernel, no Docker); "local"/"sandbox" route to the Docker
    # CodeExecutionTool (needs ms-enclave). `include: [shell_executor]` exposes
    # ONLY the terminal tool (not notebook/python/file_operation). Restricted
    # permission gates shell_executor (not whitelisted) so every command asks.
    "code_executor": {
        "mcp": False,
        "implementation": "python_env",
        "include": ["shell_executor"],
    },
    # web_search needs exa-py + EXA_API_KEY; present but off by default.
    "web_search": {"mcp": False, "engine": "exa", "enabled": False},
}

# task_control has no WebUI rendering component yet; strip it from any home that
# was seeded with the earlier default so it isn't loaded (idempotent migration).
_DROP_TOOLS = ("task_control",)


def _seed_tools_settings(home_dir: str) -> None:
    """Write the default builtin-tool config into settings.json when absent, so
    the tools are on out of the box and users can flip `enabled` per tool. Also
    prunes retired defaults (``_DROP_TOOLS``) from an existing config."""
    path = Path(home_dir) / "settings.json"
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    changed = False
    if "tools" not in data:
        data["tools"] = dict(_DEFAULT_TOOLS)
        changed = True
    else:
        tools = data["tools"]
        # Migration: drop retired default tools (only when present) so an
        # already-seeded home stops loading a component the UI can't render.
        for name in _DROP_TOOLS:
            if name in tools:
                del tools[name]
                changed = True
        # Add newly-introduced default tools that this home predates (e.g.
        # code_executor), without overwriting a user's existing tool configs.
        for name, cfg in _DEFAULT_TOOLS.items():
            if name not in tools:
                tools[name] = cfg
                changed = True
        # Enforce "terminal = shell only": a code_executor without an explicit
        # include/exclude (i.e. still the un-customized default) is narrowed to
        # shell_executor. A user's own include/exclude is left untouched.
        ce = tools.get("code_executor")
        if isinstance(ce, dict) and "include" not in ce and "exclude" not in ce:
            ce["include"] = ["shell_executor"]
            changed = True
    if not changed:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
