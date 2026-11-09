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


def _seed_providers(monkeypatch, **base_urls):
    monkeypatch.setattr(
        cfg, "_read_settings",
        lambda: {"providers": {pid: {"base_url": url}
                               for pid, url in base_urls.items()}})


def test_thinking_defaults_say_nothing_almost_everywhere(monkeypatch):
    """Sending ``enable_thinking: false`` is not the same as not mentioning
    thinking: probed 2026-08-17, glm-4.6 reasons for ~180 characters with no
    flag and ZERO with an explicit false, and ModelScope's Qwen3.5-397B for
    ~2000 vs ZERO. Defaulting "off" for every provider we had not listed is
    what silenced thinking on all of them."""
    _seed_providers(
        monkeypatch,
        modelscope="https://api-inference.modelscope.cn/v1",
        zhipu="https://open.bigmodel.cn/api/paas/v4",
        deepseek="https://api.deepseek.com",
        kimi="https://api.moonshot.cn/v1",
    )
    for provider in ("modelscope", "zhipu", "deepseek", "kimi"):
        assert cfg.thinking_plan("openai", provider)["params"] == {}


def test_thinking_defaults_speak_up_only_where_silence_means_off(monkeypatch):
    _seed_providers(
        monkeypatch,
        dashscope="https://dashscope.aliyuncs.com/compatible-mode/v1",
        deepseek="https://api.deepseek.com/anthropic",
    )
    # DashScope: qwen-plus/turbo/flash and qwen3-max default thinking OFF.
    assert cfg.thinking_plan("openai", "dashscope")["params"] == {
        "extra_body": {"enable_thinking": True}}
    # Unknown Anthropic deployments inherit their own defaults.
    assert cfg.thinking_plan("anthropic", "deepseek")["params"] == {}


def test_the_dialect_follows_the_endpoint_not_the_provider_id(monkeypatch):
    """A provider entry pointed at another vendor's endpoint (very common: the
    built-in "openai" provider aimed at DashScope) must be lowered for the
    endpoint it actually calls."""
    _seed_providers(
        monkeypatch,
        openai="https://dashscope.aliyuncs.com/compatible-mode/v1")
    # Both knobs, because on DashScope they do different jobs: the switch is
    # what turns thinking on for qwen-plus, the tier is what sets depth on
    # qwen3.8-max.
    assert cfg.thinking_plan("openai", "openai", "high")["params"] == {
        "extra_body": {"enable_thinking": True}, "reasoning_effort": "high"}
    assert cfg.thinking_plan("openai", "openai")["family"] == "dashscope"


def test_an_explicit_tier_is_clamped_to_what_the_endpoint_offers(monkeypatch):
    """Clamping only where the endpoint really is short of the ladder. GLM
    reports the full vocabulary, so `medium` reaches it untouched; DashScope
    rejects `max`, so that one caps at `xhigh`."""
    _seed_providers(
        monkeypatch,
        zhipu="https://open.bigmodel.cn/api/paas/v4",
        dashscope="https://dashscope.aliyuncs.com/compatible-mode/v1")

    got = cfg.thinking_plan("openai", "zhipu", "medium")
    assert got["effective"] == "medium"
    assert got["params"] == {"reasoning_effort": "medium"}

    capped = cfg.thinking_plan("openai", "dashscope", "max")
    assert capped["effective"] == "xhigh"
    assert capped["params"]["reasoning_effort"] == "xhigh"


def test_generation_defaults_shows_what_will_actually_be_sent(monkeypatch):
    from app.backends.ms_agent.mapping import _generation_defaults

    _seed_providers(
        monkeypatch,
        dashscope="https://dashscope.aliyuncs.com/compatible-mode/v1",
        deepseek="https://api.deepseek.com",
        modelscope="https://api-inference.modelscope.cn/v1")
    assert _generation_defaults("anthropic", "deepseek") == {}
    assert _generation_defaults("openai", "dashscope") == {
        "extra_body": {"enable_thinking": True}}
    # Nothing shipped -> nothing shown, rather than advertising a false we
    # never send.
    assert _generation_defaults("openai", "deepseek") == {}
    assert _generation_defaults("openai", "modelscope") == {}


def _shaped(provider, model, protocol="openai", webui_params=None, monkeypatch=None):
    """Run _apply_model_compatibility over a config seeded the way the real
    build is: the SDK's agent.yaml already carries
    generation_config.extra_body.enable_thinking = false."""
    from omegaconf import OmegaConf

    config = OmegaConf.create({
        "llm": {"service": provider, "model": model, "protocol": protocol},
        "generation_config": {"extra_body": {"enable_thinking": False}},
    })
    monkeypatch.setattr(cfg, "_webui_generation_params",
                        lambda p, m: dict(webui_params or {}))
    monkeypatch.setattr(cfg, "home", lambda: "/nonexistent-home")
    return cfg._apply_model_compatibility(config)


def test_silent_default_drops_the_key_seeded_by_agent_yaml(monkeypatch):
    """The regression. Returning None is not enough — the base agent.yaml ships
    enable_thinking: false, so "don't set it" leaves thinking switched off.
    _apply_model_compatibility has to delete it."""
    out = _shaped("modelscope", "Qwen/Qwen3.5-397B-A17B", monkeypatch=monkeypatch)
    assert "enable_thinking" not in out.generation_config.extra_body


def test_dashscope_still_ends_up_with_an_explicit_true(monkeypatch):
    """The decision moved into the SDK, so assert the composition rather than
    the intermediate config: the backend drops the seed, and the request path
    puts DashScope's explicit `true` back."""
    from ms_agent.llm.thinking import apply_effort

    out = _shaped("dashscope", "qwen-plus", monkeypatch=monkeypatch)
    assert "enable_thinking" not in out.generation_config.extra_body

    wire = apply_effort(
        {"extra_body": dict(out.generation_config.extra_body)},
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    assert wire == {"extra_body": {"enable_thinking": True}}


def test_user_configured_thinking_survives_the_silent_default(monkeypatch):
    """An explicit user setting beats every default, including the drop. The
    value is already in the config by now (_apply_webui_generation_params runs
    first); compatibility shaping must leave it alone."""
    from omegaconf import OmegaConf

    config = OmegaConf.create({
        "llm": {"service": "modelscope", "model": "Qwen/Qwen3.5-397B-A17B",
                "protocol": "openai"},
        "generation_config": {"extra_body": {"enable_thinking": True}},
    })
    monkeypatch.setattr(cfg, "_webui_generation_params",
                        lambda p, m: {"extra_body": {"enable_thinking": True}})
    monkeypatch.setattr(cfg, "home", lambda: "/nonexistent-home")
    out = cfg._apply_model_compatibility(config)
    assert out.generation_config.extra_body.enable_thinking is True


def test_sidecar_lookup_uses_the_ids_verbatim():
    """The provider and model ids must reach the sidecar exactly as stored.

    _apply_model_compatibility case-folds both ids for its vendor quirk matching
    ('deepseek-v4', 'kimi-k2') and used to hand the folded pair to the sidecar
    lookup as well. Those keys are the ids as created, so an ordinary mixed-case
    model id like `Qwen/Qwen3-32B` matched nothing — which reads as "the user
    configured no thinking preference" and deletes the value
    _apply_webui_generation_params had just merged in from that very setting.
    Provider ids accept letters of either case, so they hit this the same way.
    """
    from omegaconf import OmegaConf

    from app.backends.ms_agent import sidecar
    from app.backends.ms_agent.mapping import encode_model_id

    provider, model = "MyCompat_v2", "Qwen/Qwen3-32B"
    key = encode_model_id(provider, model)
    sidecar.merge(
        "models", key,
        {"advanced_params": {"extra_body": {"enable_thinking": True}}})
    try:
        config = OmegaConf.create({
            "llm": {"service": provider, "model": model, "protocol": "openai"},
            "generation_config": {"extra_body": {"enable_thinking": True}},
        })
        out = cfg._apply_model_compatibility(config)
        assert out.generation_config.extra_body.enable_thinking is True
    finally:
        sidecar.drop("models", key)


def test_editing_generation_params_invalidates_live_runtimes(monkeypatch):
    """An agent freezes its generation config at build time. Without this the
    thinking tier a user just set would only apply to conversations started
    afterwards — they change it, see no difference in the open chat, and
    conclude the setting does nothing."""
    from app.backends.ms_agent import models as models_backend
    from app.backends.ms_agent.runtime import registry
    from app.schemas.model import ModelUpdate

    class _Rt:
        def __init__(self):
            self.needs_rebuild = False

    live = _Rt()
    monkeypatch.setattr(registry, "_runtimes", {"s1": live})
    monkeypatch.setattr(models_backend, "_model_names", lambda pid: ["m1"])
    monkeypatch.setattr(models_backend, "_decode", lambda mid: ("p1", "m1"))
    monkeypatch.setattr(models_backend.sidecar, "merge",
                        lambda *a, **k: None)
    monkeypatch.setattr(models_backend, "model_to_schema",
                        lambda pid, name: None)

    models_backend.update_model("mid", ModelUpdate(advanced_params={
        "reasoning_effort": "max"}))
    assert live.needs_rebuild is True

    # A rename must not disturb anything — only params change what ships.
    live.needs_rebuild = False
    models_backend.update_model("mid", ModelUpdate(display_name="renamed"))
    assert live.needs_rebuild is False
