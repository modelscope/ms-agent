"""ms_agent backend startup: home/env, default project, LLM settings seed.

Runs once at app boot. Idempotent.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ms_agent.utils.file_lock import locked
from ms_agent.utils.json_store import read_json
from ms_agent.utils.atomic_file import atomic_write_json

from app.core.settings import settings
from app.backends.ms_agent.defaults import DEFAULT_TOOLS as _DEFAULT_TOOLS


_PROVIDER_BRAND_NAME_MIGRATIONS = {
    "kimi": (("Moonshot Kimi",), "Kimi (Moonshot AI)"),
    "dashscope": (
        (
            "Alibaba DashScope",
            "Alibaba Cloud Model Studio (DashScope)",
        ),
        "Alibaba (DashScope)",
    ),
}


def bootstrap() -> None:
    from app.backends.ms_agent.common import apply_home_env, home, pm

    from app.backends.ms_agent import model_link

    apply_home_env()
    _export_env()
    manager = pm()
    manager.initialize()
    for project in manager.list():
        sessions = manager.session_manager(project, auto_initialize=False)
        sessions.initialize()
        from app.backends.ms_agent.session_models import migrate
        for session in sessions.list():
            migrate(project, session)
    _ensure_prompt_files(home())
    _seed_tools_settings(home())
    _seed_llm_settings(home())
    _migrate_provider_brand_names(home())
    # Normalize the model link so the chat dropdown lists the active model and
    # default_model is a full "provider/model" (see model_link).
    model_link.ensure_link()
    _export_fastembed_cache()


def _ensure_prompt_files(home_dir: str) -> None:
    """Materialize the editable global prompt files during WebUI startup.

    The SDK owns the lifecycle rules: an existing file is preserved, a
    pristine built-in may be upgraded, and a file deliberately deleted after
    being seeded stays deleted. Starting the WebUI eagerly invokes that same
    logic so users can discover and manage the files before opening
    Personalization or sending the first chat message.
    """
    from ms_agent.prompting.workspace_files import ensure_home_files

    ensure_home_files(Path(home_dir))


@locked(lambda home_dir: Path(home_dir) / "settings.json")
def _migrate_provider_brand_names(home_dir: str) -> None:
    """Upgrade historical built-in display names exactly once.

    Built-in provider entries also carry credentials, endpoints and model
    catalogs, so the WebUI merges them over the SDK registry. Older homes saved
    the then-default display names in those entries; without a migration they
    permanently mask later brand-copy corrections in the registry. Only the
    exact historical defaults are rewritten. Arbitrary user names and every
    sibling field remain untouched.
    """
    import logging

    from app.backends.ms_agent import sidecar

    log = logging.getLogger("app.ms_agent.bootstrap")
    migration_key = "provider_brand_names_v2"
    try:
        flags = sidecar.get("flags", migration_key) or {}
        if flags.get("migrated"):
            return

        path = Path(home_dir) / "settings.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            providers = data.get("providers")
            changed = False
            if isinstance(providers, dict):
                for provider_id, names in (
                    _PROVIDER_BRAND_NAME_MIGRATIONS.items()
                ):
                    legacy_names, canonical_name = names
                    entry = providers.get(provider_id)
                    if (
                        isinstance(entry, dict)
                        and entry.get("name") in legacy_names
                    ):
                        entry["name"] = canonical_name
                        changed = True
            if changed:
                atomic_write_json(path, data)

        sidecar.merge("flags", migration_key, {"migrated": True})
    except Exception:  # a migration must never block boot
        log.warning("provider brand-name migration skipped", exc_info=True)


def _export_fastembed_cache() -> None:
    """Pin FASTEMBED_CACHE_PATH before anything can construct a TextEmbedding.

    mem0 builds its embedder deep inside the agent process with no cache_dir
    argument; only this env var reaches it. Exporting at boot makes every
    consumer — our probes, mem0, fastembed's own fallback download — resolve
    one shared, persistent cache (instead of fastembed's default in a TEMP
    dir), which is also where the ModelScope warm-up lays files out.
    """
    try:
        from app.backends.ms_agent.embed_warmup import fastembed_cache_dir

        fastembed_cache_dir()
    except Exception:  # cache pinning must never block boot
        import logging

        logging.getLogger("app.ms_agent.bootstrap").debug(
            "fastembed cache pinning failed", exc_info=True)


def _export_env() -> None:
    """Push backend credentials into the process env the SDK / MCP servers read."""
    for key, value in {
        "OPENAI_API_KEY": settings.openai_api_key,
        "OPENAI_BASE_URL": settings.openai_base_url,
        "EXA_API_KEY": settings.exa_api_key,
    }.items():
        if value and not os.environ.get(key):
            os.environ[key] = value


@locked(lambda home_dir: Path(home_dir) / "settings.json")
def _seed_llm_settings(home_dir: str) -> None:
    """Write settings.json `llm` from env when absent, so ConfigResolver yields a
    working model. Matches §3.1: llm.{provider,model,api_key,base_url}."""
    path = Path(home_dir) / "settings.json"
    data = read_json(path)
    if "llm" in data:
        return  # never overwrite an existing config (e.g. a shared ~/.ms_agent)

    model = settings.ms_agent_llm_model
    if not model:
        return  # nothing to seed; rely on framework default + env credentials
    provider = settings.ms_agent_llm_provider or "openai"
    llm: dict = {"provider": provider, "model": model}
    # OPENAI_* are OpenAI's credentials, so only apply them when OpenAI is the
    # provider being seeded. Copying them onto e.g. dashscope pinned the wrong
    # base_url onto the llm block; leaving them out lets the SDK's
    # CredentialResolver pick up that provider's own env vars
    # (DASHSCOPE_API_KEY, DEEPSEEK_API_KEY, …).
    if provider == "openai":
        if settings.openai_api_key:
            llm["api_key"] = settings.openai_api_key
        if settings.openai_base_url:
            llm["base_url"] = settings.openai_base_url
    data["llm"] = llm
    data.setdefault("default_model", f"{provider}/{model}")

    atomic_write_json(path, data)



def _seed_tools_settings(home_dir: str) -> None:
    """Persist the same defaults used after an external settings replacement."""
    from app.backends.ms_agent.tool_settings import ensure_tool_settings

    ensure_tool_settings(home_dir)
