"""Web-search defaults: keyless Tavily works out of the box, and says so.

The point of the feature is that a brand-new install can search before the user
configures anything. Two things have to hold for that to be true in the UI:
the seeded engine must be one that runs unconfigured, and the "not configured"
warnings must not fire for it — a warning about something that demonstrably
works is worse than no warning, because it sends the user to fix nothing.
"""
from __future__ import annotations

import json

import pytest

from app.backends.ms_agent import search as search_mod
from app.schemas.search import SearchSettingsUpdate


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(search_mod, "home", lambda: str(tmp_path))
    return tmp_path


def _write_block(home_dir, block: dict) -> None:
    (home_dir / "settings.json").write_text(
        json.dumps({"tools": {"web_search": block}}), encoding="utf-8")


def test_default_provider_is_keyless_capable():
    """Whatever the SDK offers, the default must be an engine that runs with no
    credentials — otherwise the first-run experience is a dead search tool."""
    default = search_mod._default_provider()
    assert default == "tavily"
    assert search_mod._supports_keyless(default)


def test_bootstrap_seeds_the_keyless_engine():
    from app.backends.ms_agent.bootstrap import _DEFAULT_TOOLS

    block = _DEFAULT_TOOLS["web_search"]
    assert block["enabled"] is True
    assert search_mod._supports_keyless(block["engine"]), (
        "a fresh home must be seeded with an engine that works unconfigured")


def test_provider_list_marks_keyless_support():
    by_id = {p.id: p for p in search_mod.list_providers()}
    tavily = by_id["tavily"]
    # Both flags true at once, and that is the point: a key is still ACCEPTED
    # (so the field stays visible) but is not REQUIRED to function.
    assert tavily.requires_key is True
    assert tavily.supports_keyless is True

    assert by_id["exa"].supports_keyless is False
    assert by_id["arxiv"].supports_keyless is True


def test_settings_report_keyless_for_unkeyed_tavily(home):
    _write_block(home, {"engine": "tavily", "enabled": True})
    s = search_mod.get_settings()
    assert s.provider == "tavily"
    assert s.has_key is False
    # has_key False + supports_keyless True is exactly the state the composer
    # must NOT warn about.
    assert s.supports_keyless is True


def test_settings_report_no_keyless_for_unkeyed_exa(home):
    _write_block(home, {"engine": "exa", "enabled": True})
    s = search_mod.get_settings()
    assert s.has_key is False
    assert s.supports_keyless is False  # this one really is unusable -> warn


def test_key_still_wins_when_configured(home):
    _write_block(home, {
        "engine": "tavily", "enabled": True, "tavily_api_key": "tvly-XYZ"})
    s = search_mod.get_settings()
    assert s.has_key is True
    assert s.supports_keyless is True  # capability, not current mode


def test_empty_home_falls_back_to_the_keyless_default(home):
    s = search_mod.get_settings()
    assert s.provider == "tavily"
    assert s.supports_keyless is True


def test_env_key_is_never_reported_as_configured(home, monkeypatch):
    """An env var is not this page's credential. The SDK may still fall back to
    one, but the page can neither show, edit nor clear it, so counting it as
    "configured" produced a tag nobody could act on — and a reset that looked
    broken. `has_key` therefore tracks the config block alone."""
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-FROM-ENV")
    monkeypatch.setenv("EXA_API_KEY", "exa-FROM-ENV")
    _write_block(home, {"engine": "tavily", "enabled": True})
    assert search_mod.get_settings().has_key is False

    _write_block(home, {"engine": "exa", "enabled": True})
    assert search_mod.get_settings().has_key is False


def test_reset_clears_the_stored_key(home):
    _write_block(home, {
        "engine": "tavily", "enabled": True, "tavily_api_key": "tvly-XYZ",
        "max_results": 7})

    s = search_mod.update_settings(SearchSettingsUpdate(
        enabled=True, provider="tavily", api_key=""))
    # Back to genuinely unconfigured, not just visually reset.
    assert s.has_key is False
    block = search_mod._block(json.loads(
        (home / "settings.json").read_text(encoding="utf-8")))
    assert "tavily_api_key" not in block
    # Clearing a credential must not take unrelated tuning with it.
    assert block["max_results"] == 7


def test_reset_leaves_other_providers_keys_alone(home):
    """Resetting the selected provider is scoped to it; keys parked for the
    others exist precisely so switching back does not mean re-entering them."""
    _write_block(home, {
        "engine": "tavily", "enabled": True,
        "tavily_api_key": "tvly-XYZ", "exa_api_key": "exa-XYZ"})

    search_mod.update_settings(SearchSettingsUpdate(
        enabled=True, provider="tavily", api_key=""))
    block = search_mod._block(json.loads(
        (home / "settings.json").read_text(encoding="utf-8")))
    assert "tavily_api_key" not in block
    from ms_agent.config.secrets import resolve_secret
    assert block["exa_api_key"].startswith("enc:v1:")
    assert resolve_secret(block["exa_api_key"], home=home) == "exa-XYZ"


def test_reset_lands_on_not_configured_even_with_an_env_key(home, monkeypatch):
    """The reset used to leave the tag on "configured" whenever the environment
    also carried a key, which read as a failed reset. Now what the page reports
    is exactly what the page stores, so a reset always shows through."""
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-FROM-ENV")
    _write_block(home, {
        "engine": "tavily", "enabled": True, "tavily_api_key": "tvly-XYZ"})

    s = search_mod.update_settings(SearchSettingsUpdate(
        enabled=True, provider="tavily", api_key=""))
    assert s.has_key is False
