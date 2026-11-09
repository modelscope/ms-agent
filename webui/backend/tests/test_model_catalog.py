import pytest
from omegaconf import OmegaConf
from pydantic import ValidationError

from app.backends.ms_agent import common, models, sidecar
from app.backends.ms_agent.config import _apply_webui_generation_params
from app.schemas.model import ModelCreate, ModelUpdate
from ms_agent.config.model_settings import ModelSettingsManager


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("MS_AGENT_HOME", str(tmp_path))
    common.pm().initialize()
    return tmp_path


def test_new_model_uses_catalog_without_persisting_capabilities(state):
    model = models.create_model(ModelCreate(provider_id="openai", name="gpt-4.1"))
    assert model.supports_vision is None
    assert model.effective_supports_vision is True
    assert model.catalog.context_limit > 100_000
    assert model.generation_defaults.reasoning is False
    assert model.generation_defaults.effort_options == ["auto"]
    assert not (sidecar.get("models", model.id) or {}).get("supports_vision")
    assert models.list_models("openai")[0].catalog == model.catalog


def test_vision_override_can_return_to_auto_without_affecting_other_fields(state):
    model = models.create_model(ModelCreate(provider_id="openai", name="gpt-4.1"))
    changed = models.update_model(model.id, ModelUpdate(supports_vision=False))
    assert changed.supports_vision is False and not changed.effective_supports_vision
    renamed = models.update_model(model.id, ModelUpdate(display_name="My model"))
    assert renamed.supports_vision is False
    restored = models.update_model(model.id, ModelUpdate(supports_vision=None))
    assert restored.supports_vision is None and restored.effective_supports_vision
    assert restored.display_name == "My model"


def test_unknown_model_still_supports_manual_configuration(state):
    ModelSettingsManager(state).add_provider("private", protocol="openai", base_url="https://private.invalid/v1")
    model = models.create_model(ModelCreate(provider_id="private", name="private-deployment"))
    assert model.catalog is None
    assert model.context_budget.context_limit == 128_000
    assert not model.effective_supports_vision
    updated = models.update_model(model.id, ModelUpdate(supports_vision=True, context_limit=32_000))
    assert updated.effective_supports_vision and updated.context_budget.context_limit == 32_000
    restored = models.update_model(model.id, ModelUpdate(context_limit=None))
    assert restored.context_budget.context_limit == 128_000


def test_effort_patch_preserves_advanced_parameters_and_nested_defaults(state):
    sidecar.merge("providers", "deepseek", {"default_generation_params": {"extra_body": {"keep": True}}})
    model = models.create_model(ModelCreate(
        provider_id="deepseek", name="deepseek-v4-pro",
        advanced_params={"max_tokens": 4096, "extra_body": {"other": True}},
    ))
    updated = models.update_model(model.id, ModelUpdate(reasoning_effort="low"))
    assert updated.advanced_params == {
        "max_tokens": 4096, "extra_body": {"other": True}, "reasoning_effort": "low",
    }
    assert updated.generation_defaults.effort == "low"
    assert "off" in updated.generation_defaults.effort_options
    cfg = OmegaConf.create({"llm": {"service": "deepseek", "model": model.name}})
    _apply_webui_generation_params(cfg)
    assert cfg.generation_config.extra_body.keep is True
    assert cfg.generation_config.extra_body.other is True
    assert cfg.generation_config.reasoning_effort == "low"


def test_runtime_receives_context_and_vision_overrides(state):
    model = models.create_model(ModelCreate(
        provider_id="openai", name="gpt-4.1", supports_vision=False, context_limit=40_000,
    ))
    cfg = OmegaConf.create({"llm": {"service": "openai", "model": model.name}})
    _apply_webui_generation_params(cfg)
    assert cfg.llm.context_limit == 40_000
    assert cfg.llm.supports_vision is False
    assert model.context_budget.context_limit == 40_000
    assert model.context_budget.compression_threshold <= 34_000


def test_raw_thinking_parameters_remain_authoritative(state):
    model = models.create_model(ModelCreate(
        provider_id="dashscope", name="qwen3.7-max",
        advanced_params={"extra_body": {"enable_thinking": False}},
    ))
    defaults = model.generation_defaults
    assert defaults.raw_override
    assert "reasoning_effort" not in defaults.wire_params
    models.update_model(model.id, ModelUpdate(reasoning_effort="on"))
    assert sidecar.get("models", model.id)["advanced_params"]["extra_body"]["enable_thinking"] is False


def test_native_anthropic_preview_uses_spec_protocol(state):
    defaults = models.generation_defaults("anthropic", "claude-sonnet-4-6")
    assert defaults.family == "anthropic"
    assert defaults.catalog.provider_id == "anthropic"
    assert "low" in defaults.effort_options


def test_regional_catalog_uses_configured_endpoint(state):
    manager = ModelSettingsManager(state)
    manager.add_provider("dashscope", base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    defaults = models.generation_defaults("dashscope", "qwen3.7-max")
    assert defaults.catalog is not None
    assert defaults.catalog.provider_id == "alibaba"


def test_model_discovery_falls_back_to_offline_catalog(state, monkeypatch):
    from app.api.providers import available_models
    monkeypatch.setattr("app.core.model_discovery.fetch_model_ids", lambda *args: [])
    assert "gpt-4.1" in available_models("openai")
    monkeypatch.setattr("app.core.model_discovery.fetch_model_ids", lambda *args: ["account-specific"])
    assert available_models("openai") == ["account-specific"]


def test_discovery_honors_builtin_protocol_override(state):
    from app.backends.ms_agent.providers import get_provider_secret
    ModelSettingsManager(state).add_provider("deepseek", protocol="anthropic", base_url="https://api.deepseek.com/anthropic")
    assert get_provider_secret("deepseek")[1] == "anthropic"


@pytest.mark.parametrize("value", [0, -1, 1023, 100_000_001])
def test_context_limit_validation(value):
    with pytest.raises(ValidationError):
        ModelUpdate(context_limit=value)


def test_invalid_effort_rejected():
    with pytest.raises(ValidationError):
        ModelUpdate(reasoning_effort="turbo")


def test_restart_preserves_automatic_vision(state):
    from app.backends.ms_agent.bootstrap import bootstrap

    model = models.create_model(ModelCreate(provider_id="openai", name="gpt-4.1", display_name="Catalog model"))
    bootstrap()
    restored = models.list_models("openai")[0]
    assert restored.id == model.id
    assert restored.supports_vision is None
    assert restored.effective_supports_vision


def test_invalid_saved_budget_remains_editable(state):
    model = models.create_model(ModelCreate(
        provider_id="anthropic", name="claude-opus-4-5",
        advanced_params={"max_tokens": 512, "thinking_budget": 4096},
    ))
    assert "budget" in model.generation_defaults.configuration_error
    assert models.list_models("anthropic")[0].id == model.id
    fixed = models.update_model(model.id, ModelUpdate(advanced_params={"max_tokens": 8192}))
    assert fixed.generation_defaults.configuration_error == ""
