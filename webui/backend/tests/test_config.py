"""WebUI config shaping: generation-param merge (thinking-aware)."""
from app.backends.ms_agent import config as cfg


def test_deep_merge_refines_nested_dicts_without_replacing_siblings():
    base = {"extra_body": {"enable_thinking": True, "foo": 1}, "temperature": 0.3}
    override = {"extra_body": {"foo": 2, "bar": 3}, "top_p": 0.9}
    out = cfg._deep_merge(base, override)
    assert out == {
        "extra_body": {"enable_thinking": True, "foo": 2, "bar": 3},
        "temperature": 0.3,
        "top_p": 0.9,
    }
    assert base["extra_body"] == {"enable_thinking": True, "foo": 1}  # inputs untouched


def test_webui_generation_params_deep_merges_provider_then_model(monkeypatch):
    """A model's advanced_params.extra_body must refine, not replace, the
    provider's default_generation_params.extra_body — otherwise setting one
    model-level extra_body key drops the provider's enable_thinking."""
    def _fake_get(kind, key):
        if kind == "providers":
            return {"default_generation_params": {
                "extra_body": {"enable_thinking": True, "foo": 1}, "temperature": 0.7}}
        if kind == "models":
            return {"advanced_params": {"extra_body": {"foo": 2, "bar": 3}}}
        return None

    monkeypatch.setattr("app.backends.ms_agent.sidecar.get", _fake_get)
    params = cfg._webui_generation_params("deepseek", "deepseek-v4-pro")
    assert params == {
        "extra_body": {"enable_thinking": True, "foo": 2, "bar": 3},
        "temperature": 0.7,
    }


def test_thinking_default_by_protocol_provider_model():
    # On by default for anthropic protocol, qwen models, and dashscope/modelscope.
    assert cfg.thinking_default("anthropic", "deepseek", "deepseek-v4-pro") is True
    assert cfg.thinking_default("openai", "dashscope", "some-model") is True
    assert cfg.thinking_default("openai", "modelscope", "x") is True
    assert cfg.thinking_default("openai", "openai", "qwen-plus") is True
    # Off for other OpenAI-compatible providers.
    assert cfg.thinking_default("openai", "deepseek", "deepseek-v4-pro") is False
    assert cfg.thinking_default("openai", "kimi", "kimi-k2") is False


def test_generation_defaults_surfaces_thinking_flag():
    from app.backends.ms_agent.mapping import _generation_defaults

    assert _generation_defaults("anthropic", "deepseek") == {
        "extra_body": {"enable_thinking": True}}
    assert _generation_defaults("openai", "deepseek") == {
        "extra_body": {"enable_thinking": False}}
    assert _generation_defaults("openai", "dashscope") == {
        "extra_body": {"enable_thinking": True}}
