"""Built-in provider catalog: the SDK registry is the 'fill an API key' source.

Item I (webui-remain01 §5): a user should be able to pick a built-in provider
and just enter a key. That works because every ProviderSpec already ships a
default base_url + transport, so only the key is user-supplied. This locks in
that the full catalog is present and self-describing.
"""
import json
import pytest
from ms_agent.llm.spec import get_registry
from pydantic import ValidationError

_EXPECTED_BUILTINS = {
    "openai", "anthropic", "google", "modelscope", "zhipu",
    "kimi", "deepseek", "dashscope", "minimax", "openrouter",
}


def test_registry_ships_full_builtin_catalog():
    names = {p.name for p in get_registry().list_providers()}
    assert _EXPECTED_BUILTINS <= names


def test_registry_puts_modelscope_first():
    providers = get_registry().list_providers()
    assert providers and providers[0].name == "modelscope"


def test_provider_api_uses_canonical_builtin_display_names():
    from app.backends.ms_agent import providers as P

    display_names = {provider.id: provider.name for provider in P.list_providers()}
    assert display_names["kimi"] == "Kimi (Moonshot AI)"
    assert display_names["dashscope"] == "Alibaba (DashScope)"


def test_bootstrap_migrates_only_legacy_builtin_display_names(
    tmp_path,
    monkeypatch,
):
    from app.backends.ms_agent import bootstrap

    monkeypatch.setenv("MS_AGENT_HOME", str(tmp_path))
    settings_path = tmp_path / "settings.json"
    original = {
        "providers": {
            "kimi": {
                "name": "Moonshot Kimi",
                "api_key": "kimi-secret",
                "base_url": "https://api.moonshot.cn/v1",
                "protocol": "openai",
                "models": ["kimi-k3"],
            },
            "dashscope": {
                "name": "Alibaba DashScope",
                "api_key": "dashscope-secret",
                "models": ["qwen3.8-max"],
            },
            "openai": {"name": "My OpenAI Gateway", "api_key": "openai-secret"},
        }
    }
    settings_path.write_text(json.dumps(original), encoding="utf-8")

    bootstrap._migrate_provider_brand_names(str(tmp_path))

    migrated = json.loads(settings_path.read_text(encoding="utf-8"))
    providers = migrated["providers"]
    assert providers["kimi"] == {
        **original["providers"]["kimi"],
        "name": "Kimi (Moonshot AI)",
    }
    assert providers["dashscope"] == {
        **original["providers"]["dashscope"],
        "name": "Alibaba (DashScope)",
    }
    assert providers["openai"] == original["providers"]["openai"]


def test_provider_brand_migration_runs_only_once(tmp_path, monkeypatch):
    from app.backends.ms_agent import bootstrap

    monkeypatch.setenv("MS_AGENT_HOME", str(tmp_path))
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({
            "providers": {
                "dashscope": {
                    "name": "Alibaba Cloud Model Studio (DashScope)"
                }
            }
        }),
        encoding="utf-8",
    )
    bootstrap._migrate_provider_brand_names(str(tmp_path))

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["providers"]["dashscope"]["name"] == "Alibaba (DashScope)"
    data["providers"]["dashscope"]["name"] = (
        "Alibaba Cloud Model Studio (DashScope)"
    )
    settings_path.write_text(json.dumps(data), encoding="utf-8")
    bootstrap._migrate_provider_brand_names(str(tmp_path))

    after_second_boot = json.loads(settings_path.read_text(encoding="utf-8"))
    assert after_second_boot["providers"]["dashscope"]["name"] == (
        "Alibaba Cloud Model Studio (DashScope)"
    )


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


def test_builtin_provider_display_name_can_be_overridden():
    """Editing a built-in provider's display name must round-trip.

    Regression: `builtin_provider_to_schema` used to read `spec.display_name`
    unconditionally, so saving a custom `name` (settings.json override) landed
    on disk but the API kept reporting the spec's default — the settings modal
    looked broken for that one field while base_url and protocol worked. The
    fix is that the override wins here too, matching those siblings.
    """
    from app.backends.ms_agent import providers as P
    from app.schemas.provider import ProviderUpdate

    before = P.get_provider("openai")
    try:
        P.update_provider("openai", ProviderUpdate(name="OpenAI (renamed)"))
        assert P.get_provider("openai").name == "OpenAI (renamed)"
    finally:
        P.update_provider("openai", ProviderUpdate(name=before.name))


def test_empty_api_key_clears_the_stored_credential():
    """'' is the update schema's "clear it" signal, not "leave it alone".

    The settings UI can never echo a stored key, so "configured" is read purely
    off `api_key_masked`. The provider modal's reset button stages a removal and
    its Save then PATCHes api_key='' to bring that back to empty; if '' were
    treated as "unchanged" (as that same Save deliberately does for a field the
    user simply left blank) a key pasted into the wrong provider could never be
    taken back out.
    """
    from app.backends.ms_agent import providers as P
    from app.schemas.provider import ProviderUpdate

    before = P.get_provider("openai")
    try:
        P.update_provider("openai", ProviderUpdate(api_key="sk-secret-value"))
        # Masked, never echoed in full.
        masked = P.get_provider("openai").api_key_masked
        assert masked and "secret" not in masked

        P.update_provider("openai", ProviderUpdate(api_key=""))
        assert P.get_provider("openai").api_key_masked == ""
    finally:
        P.update_provider(
            "openai", ProviderUpdate(api_key="", name=before.name))


def test_display_name_is_optional_and_falls_back_to_the_id():
    """A custom provider can be created without a display name.

    The id already reads as a label ('openai-compat'), so requiring a second
    one was busywork — and both the SDK's add_provider and the read mapping
    already fall back to the id for entries that carry no name.
    """
    from app.backends.ms_agent import providers as P
    from app.schemas.provider import ProviderCreate

    created = P.create_provider(
        ProviderCreate(id="nameless-compat", base_url="https://api.example.com"))
    try:
        assert created.name == "nameless-compat"
        assert P.get_provider("nameless-compat").name == "nameless-compat"
    finally:
        P.delete_provider("nameless-compat")


def test_clearing_a_builtin_display_name_restores_the_spec_default():
    """'' means "I have no name of my own", so the registry's label comes back.

    Needs resolving on write: the SDK's add_provider reads a falsy name as "keep
    the stored one", so passing '' straight through would leave the old name in
    place and make the cleared field look ignored. Same code path also protects
    an untouched name — a PATCH that only sets api_key used to fall through to
    add_provider's own `or provider_id` default and quietly relabel builtin
    'OpenAI' to 'openai'.
    """
    from app.backends.ms_agent import providers as P
    from app.schemas.provider import ProviderUpdate

    spec_default = P._default_name("openai")
    try:
        P.update_provider("openai", ProviderUpdate(name="Renamed"))
        assert P.get_provider("openai").name == "Renamed"
        P.update_provider("openai", ProviderUpdate(name=""))
        assert P.get_provider("openai").name == spec_default

        # The api_key-only PATCH must not disturb the label either.
        P.update_provider("openai", ProviderUpdate(api_key="sk-x"))
        assert P.get_provider("openai").name == spec_default
    finally:
        P.update_provider("openai", ProviderUpdate(api_key="", name=""))


def test_adding_a_model_does_not_relabel_a_builtin_provider():
    """Adding a model must not double as an edit of the provider itself.

    A built-in provider has no settings.json entry until something writes one,
    and `add_model` writes the first one. That entry is merged over the registry
    on read, so the SDK seeding it with `name: <provider_id>` and
    `protocol: "openai"` reached the UI as the user's own overrides: the first
    model added to `google` renamed it to "google" for good (deleting the model
    leaves the entry, and the label, behind) and `anthropic` was reported — and
    configured — as an OpenAI-protocol endpoint.
    """
    from app.backends.ms_agent import models as M
    from app.backends.ms_agent import providers as P
    from app.schemas.model import ModelCreate

    before = P.get_provider("anthropic")
    assert before.name == "Anthropic" and before.protocol == "anthropic"

    created = M.create_model(
        ModelCreate(provider_id="anthropic", name="claude-4-opus"))
    try:
        after = P.get_provider("anthropic")
        assert after.name == before.name
        assert after.protocol == before.protocol
        assert after.base_url == before.base_url
    finally:
        M.delete_model(created.id)
        # The materialized entry outlives the model it was created for; drop it
        # so the built-in is back to "never configured" for later tests.
        P.delete_provider("anthropic")


def test_provider_id_accepts_letters_of_either_case():
    """The id only has to be an identifier, not a lowercase slug."""
    from app.schemas.provider import ProviderCreate

    assert ProviderCreate(id="MyCompat_v2").id == "MyCompat_v2"
    for bad in ("has space", "-leading", "dots.not.allowed", ""):
        with pytest.raises(ValidationError):
            ProviderCreate(id=bad)


def test_ids_differing_only_in_case_are_separate_providers():
    """Uniqueness is exact — `OpenAI` beside builtin `openai` is just one more
    provider, not a duplicate to reject. Pinned because the alternative was
    considered and turned down: an extra row is normal, and folding case here
    would refuse legitimate ids.
    """
    from app.backends.errors import Conflict
    from app.backends.ms_agent import providers as P
    from app.schemas.provider import ProviderCreate

    created = P.create_provider(ProviderCreate(id="OpenAI"))
    try:
        assert created.id == "OpenAI" and created.kind == "custom"
        # Both resolvable, independently, under their own exact ids.
        assert P.get_provider("OpenAI").kind == "custom"
        assert P.get_provider("openai").kind == "builtin"
        # The exact id is still taken, though.
        with pytest.raises(Conflict):
            P.create_provider(ProviderCreate(id="OpenAI"))
    finally:
        P.delete_provider("OpenAI")
