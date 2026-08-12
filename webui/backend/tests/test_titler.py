"""Titler parsing + config resolution (offline; no network)."""
from app.backends.ms_agent import titler


def test_parse_valid_json():
    out = titler._parse('{"title": "Plan a trip abroad", "category": "planning"}')
    assert out == ("Plan a trip abroad", "planning")


def test_parse_strips_code_fence_and_quotes():
    raw = '```json\n{"title": "\\"Fix login bug\\"", "category": "coding"}\n```'
    title, category = titler._parse(raw)
    assert title == "Fix login bug"
    assert category == "coding"


def test_parse_unknown_category_falls_back_to_general():
    out = titler._parse('{"title": "随便聊聊", "category": "banana"}')
    assert out == ("随便聊聊", "general")


def test_parse_empty_title_returns_none():
    assert titler._parse('{"title": "", "category": "coding"}') is None


def test_parse_non_json_returns_none():
    assert titler._parse("sorry, I cannot help") is None


async def test_generate_returns_none_without_credentials(monkeypatch):
    # No model/key/base_url resolved -> no network call, graceful None.
    monkeypatch.setattr(titler, "_llm_config", lambda: ("", "", ""))
    assert await titler.generate_title_and_category("hello") is None


async def test_generate_returns_none_for_blank_text():
    assert await titler.generate_title_and_category("   ") is None
