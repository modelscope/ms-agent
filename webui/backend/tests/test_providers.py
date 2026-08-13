"""Built-in provider catalog: the SDK registry is the 'fill an API key' source.

Item I (webui-remain01 §5): a user should be able to pick a built-in provider
and just enter a key. That works because every ProviderSpec already ships a
default base_url + transport, so only the key is user-supplied. This locks in
that the full catalog is present and self-describing.
"""
from ms_agent.llm.spec import get_registry

_EXPECTED_BUILTINS = {
    "openai", "anthropic", "google", "modelscope", "zhipu",
    "kimi", "deepseek", "dashscope", "minimax", "openrouter",
}


def test_registry_ships_full_builtin_catalog():
    names = {p.name for p in get_registry().list_providers()}
    assert _EXPECTED_BUILTINS <= names


def test_every_builtin_spec_is_key_only_ready():
    # default_base_url + transport present => only the API key is user-supplied.
    for spec in get_registry().list_providers():
        assert spec.default_base_url, f"{spec.name} missing default_base_url"
        assert spec.transport, f"{spec.name} missing transport"


def test_available_models_returns_the_discovered_ids(monkeypatch):
    """Regression: the endpoint fell off its own end without returning, so
    FastAPI validated None against its declared list[str] and answered 500 — the
    "add model" dialog's id autocomplete was silently always empty.
    """
    from app.api.providers import available_models
    from app.core import model_discovery

    seen: dict = {}

    def _fake(base_url: str, protocol: str, api_key: str) -> list[str]:
        seen.update(base_url=base_url, protocol=protocol)
        return ["gpt-4o", "gpt-4o-mini"]

    monkeypatch.setattr(model_discovery, "fetch_model_ids", _fake)
    assert available_models("openai") == ["gpt-4o", "gpt-4o-mini"]
    # Called with the provider's own resolved endpoint + protocol, not defaults.
    assert seen["base_url"] and seen["protocol"] == "openai"


def test_available_models_passes_through_the_empty_degraded_case(monkeypatch):
    """Discovery is best-effort: fetch_model_ids answers [] for a missing key /
    network error / non-standard endpoint, and that [] must reach the client as a
    valid empty response (the UI then offers free-form entry)."""
    from app.api.providers import available_models
    from app.core import model_discovery

    monkeypatch.setattr(model_discovery, "fetch_model_ids",
                        lambda *_a, **_k: [])
    assert available_models("modelscope") == []
