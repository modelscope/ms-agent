"""Web-search adapter — global `tools.web_search` block in settings.json.

The SDK's WebSearchTool reads its engine and credentials straight out of that
block, so writing there is what makes a configured provider actually take effect
in chat. Nothing is mirrored into a sidecar: one source of truth, and the SDK is
already the reader.

Keys are stored PER ENGINE (`exa_api_key`, `serpapi_api_key`, …) because that is
what the SDK reads: its generic `api_key` field is only a backward-compat
fallback for exa, so a Tavily/SerpAPI key written there would look configured in
the UI while the tool silently found nothing. Per-engine storage also means
switching providers to look around never destroys a key, and the "configured"
tag describes the selected provider rather than "some provider".

The config block is the ONLY credential source this adapter knows about. The SDK
also falls back to `EXA_API_KEY` / `TAVILY_API_KEY` / … when its config field is
empty (websearch_tool.py builds `self._api_keys` that way, config first), and
this adapter deliberately ignores that: reporting two sources through one
"configured" tag made the state unreadable — you could not tell which key a
search would use, and a key the page never stored cannot be edited or removed
from the page either. So the settings page describes exactly what it manages.
"""
from __future__ import annotations

from pathlib import Path

from ms_agent.utils.atomic_file import atomic_write_json

from app.backends.ms_agent.common import home
from app.backends.ms_agent.settings_store import settings_lock
from app.backends.errors import BadRequest
from app.schemas.search import SearchProvider, SearchSettings, SearchSettingsUpdate

# id -> (display label, config field for its key)
# Field names mirror WebSearchTool.__init__'s config lookup; `None` = the engine
# takes no credential.
_PROVIDER_META: dict[str, tuple[str, str | None]] = {
    "tavily": ("Tavily Search", "tavily_api_key"),
    "exa": ("Exa Search", "exa_api_key"),
    "serpapi": ("SerpAPI", "serpapi_api_key"),
    # Public arXiv API — the SDK builds ArxivSearch() with no arguments.
    "arxiv": ("arXiv", None),
}

# Engines that answer without credentials. Tavily serves a keyless tier (SDK:
# tavily/search.py KEYLESS_HEADER) on a small sliding hourly quota, which is
# what lets a fresh install search before anything is configured; arxiv needs no
# credential at all. Everything else genuinely cannot run unconfigured.
_KEYLESS_CAPABLE = frozenset({"tavily", "arxiv"})


def _supports_keyless(provider: str) -> bool:
    return provider in _KEYLESS_CAPABLE

# Exa's pre-per-engine field name, still honoured by the SDK for exa only.
_LEGACY_EXA_FIELDS = ("exa_api_keys", "api_key")

_FALLBACK_ORDER = ("tavily", "exa", "serpapi", "arxiv")


def _supported_ids() -> list[str]:
    """Engine ids the installed SDK accepts, in a stable display order."""
    try:
        from ms_agent.tools.search.websearch_tool import WebSearchTool

        ids = [str(e).lower() for e in WebSearchTool.SUPPORTED_ENGINES]
    except Exception:
        # Import failures must not take the settings page down; fall back to the
        # set this adapter was written against.
        ids = list(_FALLBACK_ORDER)
    known = [i for i in _FALLBACK_ORDER if i in ids]
    extra = sorted(i for i in ids if i not in _FALLBACK_ORDER)
    return known + extra


def list_providers() -> list[SearchProvider]:
    out: list[SearchProvider] = []
    for pid in _supported_ids():
        label, key_field = _PROVIDER_META.get(pid, (pid, f"{pid}_api_key"))
        out.append(
            SearchProvider(
                id=pid,
                label=label,
                requires_key=key_field is not None,
                supports_keyless=_supports_keyless(pid),
            )
        )
    return out


def _default_provider() -> str:
    """Tavily first: it is the one engine that both works with no credentials
    (keyless tier) and searches the general web, so a fresh install can answer
    questions before the user configures anything. Falls back to whatever the
    installed SDK does offer if Tavily is ever dropped."""
    ids = _supported_ids()
    if "tavily" in ids:
        return "tavily"
    return ids[0] if ids else "tavily"


def _settings_path() -> Path:
    return Path(home()) / "settings.json"


def _load() -> dict:
    from app.backends.ms_agent.tool_settings import ensure_tool_settings

    return ensure_tool_settings(home())


def _save(data: dict) -> None:
    atomic_write_json(_settings_path(), data)


def _block(data: dict) -> dict:
    tools = data.get("tools")
    if not isinstance(tools, dict):
        return {}
    block = tools.get("web_search")
    return block if isinstance(block, dict) else {}


def _meta(provider: str) -> tuple[str, str | None]:
    return _PROVIDER_META.get(provider, (provider, f"{provider}_api_key"))


def _key_fields(provider: str) -> tuple[str, ...]:
    """Config fields that count as "this provider has a key", most specific
    first. Exa keeps its legacy aliases so a home configured before per-engine
    storage still reports as configured instead of prompting again."""
    _, field = _meta(provider)
    if field is None:
        return ()
    if provider == "exa":
        return (field, *_LEGACY_EXA_FIELDS)
    return (field,)


def _has_key(block: dict, provider: str) -> bool:
    """Whether THIS page has a key on file for the provider. Environment
    variables are not consulted on purpose (see module docstring): the tag is a
    statement about the config the page owns and can edit or clear."""
    return any(
        str(block.get(field) or "").strip() for field in _key_fields(provider))


def get_settings() -> SearchSettings:
    with settings_lock():
        block = _block(_load())
    engine = str(block.get("engine") or "").lower() or _default_provider()
    if engine not in _supported_ids():
        # A hand-edited or retired engine id would otherwise leave the Select
        # with no matching option, rendering blank.
        engine = _default_provider()
    return SearchSettings(
        # Absent key reads as ON, matching the bootstrap default — a home whose
        # web_search block was hand-written without `enabled` would otherwise
        # report the opposite of what a freshly seeded one does.
        enabled=bool(block.get("enabled", True)),
        provider=engine,
        has_key=_has_key(block, engine),
        supports_keyless=_supports_keyless(engine),
    )


def update_settings(body: SearchSettingsUpdate) -> SearchSettings:
    provider = (body.provider or "").strip().lower()
    if provider not in _supported_ids():
        raise BadRequest("This search provider is not supported.")

    _, key_field = _meta(provider)

    with settings_lock():
        data = _load()
        tools = data.setdefault("tools", {})
        if not isinstance(tools, dict):
            tools = {}
            data["tools"] = tools
        block = tools.get("web_search")
        if not isinstance(block, dict):
            # Mirror the bootstrap default so an existing home that never had the
            # block still gets a well-formed one.
            block = {"mcp": False}
        # Merge rather than replace: the block may also carry fetcher /
        # max_results / chunking options the UI doesn't surface, and the OTHER
        # providers' keys, which switching provider must never disturb.
        block["engine"] = provider
        block["enabled"] = bool(body.enabled)
        if body.api_key is not None and key_field is not None:
            key = body.api_key.strip()
            if key:
                block[key_field] = key
            else:
                block.pop(key_field, None)
                if provider == "exa":
                    # Clearing must also drop the legacy aliases or the old key
                    # would keep winning through the SDK's fallback chain.
                    for alias in _LEGACY_EXA_FIELDS:
                        block.pop(alias, None)
        tools["web_search"] = block

        # No "must have a key to be enabled" guard here on purpose. It read as a
        # safety net but its only effect was blocking a legitimate action: with
        # search already on, SWITCHING to a provider whose key isn't set yet
        # carries enabled=true and got rejected, so the provider dropdown became
        # unusable. Enabled-without-a-key is a state the config can already be
        # in anyway; the settings page flags it in red and blocks the enable
        # toggle itself, which is where that intent actually lives.
        _save(data)

    return get_settings()
