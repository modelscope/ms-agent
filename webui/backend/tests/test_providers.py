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
