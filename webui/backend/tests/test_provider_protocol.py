"""Model selection and partial provider edits preserve the effective protocol."""
import json

import pytest
from fastapi.testclient import TestClient

from app.backends.ms_agent import agent_settings, common, model_link, models, providers
from app.schemas.agent_settings import AgentSettings
from app.schemas.model import ModelCreate


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    from app.core.settings import settings

    monkeypatch.setenv("MS_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "ms_agent_llm_model", "")
    return tmp_path


def data(response):
    assert response.status_code < 300, response.text
    return response.json()["data"]


@pytest.mark.parametrize("provider,protocol", [
    ("anthropic", "anthropic"), ("openai", "openai"), ("deepseek", "openai"),
])
def test_add_select_and_restart_preserve_builtin_protocol(isolated_home, provider, protocol):
    from app.main import create_app

    with TestClient(create_app()) as client:
        before = data(client.get(f"/api/providers/{provider}"))
        model = data(client.post("/api/models", json={
            "provider_id": provider, "name": "protocol-test-model",
        }))
        data(client.put("/api/agent-settings", json={
            "default_provider_id": provider, "default_model_id": model["id"],
        }))
        after = data(client.get(f"/api/providers/{provider}"))
        assert after["protocol"] == before["protocol"] == protocol
        assert after["name"] == before["name"]

    # A new app runs bootstrap.ensure_link against the persisted selection.
    with TestClient(create_app()) as restarted:
        assert data(restarted.get(f"/api/providers/{provider}"))["protocol"] == protocol
        assert data(restarted.get("/api/agent-settings"))["default_model_id"] == model["id"]

    saved = json.loads((isolated_home / "settings.json").read_text())
    assert "protocol" not in saved["providers"][provider]


@pytest.mark.parametrize("patch", [
    {"api_key": "test-placeholder-not-a-real-key"},
    {"name": "My Claude provider"},
    {"base_url": "https://gateway.example.invalid/anthropic"},
])
def test_partial_anthropic_edit_preserves_native_protocol(isolated_home, patch):
    from app.main import create_app

    with TestClient(create_app()) as client:
        updated = data(client.patch("/api/providers/anthropic", json=patch))
        assert updated["protocol"] == "anthropic"
        model = data(client.post("/api/models", json={
            "provider_id": "anthropic", "name": "protocol-test-model",
        }))
        data(client.put("/api/agent-settings", json={"default_model_id": model["id"]}))
        assert data(client.get("/api/providers/anthropic"))["protocol"] == "anthropic"


@pytest.mark.parametrize("provider,override,expected_transport", [
    ("anthropic", None, "AnthropicMessagesTransport"),
    ("anthropic", "openai", "OpenAICompatTransport"),
    ("deepseek", "anthropic", "AnthropicMessagesTransport"),
    ("ReviewGateway", "anthropic", "AnthropicMessagesTransport"),
])
def test_selected_model_routes_with_native_or_explicit_protocol(
    isolated_home, provider, override, expected_transport,
):
    from app.backends.ms_agent.config import build_agent
    from app.schemas.provider import ProviderUpdate
    from ms_agent.llm.router import ProviderRouter
    from ms_agent.ui.events import RecordingSink

    entry = {"api_key": "test-placeholder-not-a-real-key", "models": []}
    if override is not None:
        entry.update(protocol=override, base_url="https://gateway.example.invalid")
    model_link._save({"providers": {provider: entry}})
    model = models.create_model(ModelCreate(provider_id=provider, name="protocol-test-model"))
    agent_settings.update_settings(AgentSettings(default_model_id=model.id))
    model_link.ensure_link()
    # Editing another field must also preserve a deliberate compatible gateway.
    providers.update_provider(provider, ProviderUpdate(name="Review provider"))
    model_link.ensure_link()

    project = common.pm().create(name="Protocol regression", memory_enabled=False)
    session = common.sm_for(project).create()
    agent = build_agent(project, session, event_sink=RecordingSink(), input_source=None, mcp_config={})
    routed = ProviderRouter().create(agent.config)
    try:
        assert type(routed.transport).__name__ == expected_transport
        assert agent.config.llm.model == model.name
        if override is not None:
            assert agent.config.llm.protocol == override
    finally:
        # Client construction performs no model request; release its HTTP pool.
        routed.transport.client.close()
