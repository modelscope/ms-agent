"""Credential fault behavior across management API and chat SSE."""
import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from ms_agent.config.secrets import SecretError, SecretStore, write_managed_config

from app.main import app


@pytest.fixture
def storage(tmp_path, monkeypatch):
    home = tmp_path / "data"
    monkeypatch.setenv("MS_AGENT_HOME", str(home))
    monkeypatch.delenv("MS_AGENT_SECRET_KEY", raising=False)
    monkeypatch.delenv("MS_AGENT_SECRET_KEY_FILE", raising=False)
    write_managed_config(home / "settings.json", {
        "providers": {"probe": {"api_key": "synthetic-test-secret", "models": ["m"]}},
        "tools": {"web_search": {"engine": "exa", "exa_api_key": "search-test-secret"}},
    }, home=home)
    return home


@pytest.mark.parametrize("fault", ["missing", "wrong", "invalid", "external-empty", "external-ambiguous"])
def test_faults_are_visible_and_discovery_never_uses_ciphertext(storage, monkeypatch, fault):
    key = SecretStore(storage).key_file
    if fault == "missing":
        key.unlink()
    elif fault == "wrong":
        key.write_bytes(Fernet.generate_key())
    elif fault == "invalid":
        key.write_bytes(b"invalid")
    elif fault == "external-empty":
        monkeypatch.setenv("MS_AGENT_SECRET_KEY", "")
    else:
        monkeypatch.setenv("MS_AGENT_SECRET_KEY", Fernet.generate_key().decode())
        monkeypatch.setenv("MS_AGENT_SECRET_KEY_FILE", str(key))
    with TestClient(app) as client:
        response = client.get("/api/providers/probe")
        assert response.status_code == 200
        assert response.json()["data"]["api_key_status"] == "unavailable"
        assert response.json()["data"]["api_key_masked"] == ""
        assert client.get("/api/search-settings").json()["data"]["key_status"] == "unavailable"
        response = client.get("/api/providers/probe/available-models")
        assert response.status_code == 409
        assert "enc:v1:" not in response.text and "synthetic-test-secret" not in response.text


def test_mixed_wrong_key_file_is_never_rewritten_on_read(storage):
    from app.backends.ms_agent.tool_settings import ensure_tool_settings
    path = storage / "settings.json"
    data = json.loads(path.read_text())
    data["providers"]["legacy"] = {"api_key": "legacy-plaintext"}
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    SecretStore(storage).key_file.write_bytes(Fernet.generate_key())
    assert ensure_tool_settings(storage)["providers"]["legacy"]["api_key"] == "legacy-plaintext"
    assert path.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_chat_build_secret_error_is_reported_as_complete_sse(monkeypatch, empty):
    from app.backends.ms_agent import chat
    from app.schemas.chat import ChatRequest, ChatMessage
    def fail(_req):
        if empty:
            from app.backends.errors import BadRequest
            raise BadRequest("The selected provider's API key is empty.")
        raise SecretError("The instance master key is missing.")
    monkeypatch.setattr(chat, "_resolve_or_create", fail)
    frames = [json.loads(frame["data"]) async for frame in chat.stream(
        ChatRequest(message=ChatMessage(role="user", content="hello")))]
    assert [frame["type"] for frame in frames] == ["error", "done"]
    assert frames[0]["meta"]["recoverable"] is True


def test_validation_does_not_echo_secret_body():
    with TestClient(app) as client:
        response = client.patch("/api/providers/openai", json={"api_key": {"nested": "synthetic-test-secret"}})
        assert response.status_code == 422
        assert "synthetic-test-secret" not in response.text


@pytest.mark.parametrize("legacy", [False, True])
def test_webui_upgrade_resolves_auxiliary_credentials_without_rewriting_plaintext(
    tmp_path, monkeypatch, legacy
):
    from app.backends.ms_agent import config, titler
    from ms_agent.llm.credentials import CredentialResolver
    from omegaconf import OmegaConf

    home = tmp_path / "home"
    monkeypatch.setenv("MS_AGENT_HOME", str(home))
    monkeypatch.delenv("MS_AGENT_SECRET_KEY", raising=False)
    monkeypatch.delenv("MS_AGENT_SECRET_KEY_FILE", raising=False)
    data = {
        "providers": {
            name: {"api_key": f"synthetic-{name}-key", "models": [model],
                   "base_url": "https://example.test/v1", "protocol": "openai"}
            for name, model in (("conversation", "chat"), ("facts", "extract"),
                                ("vectors", "embed"))
        },
        "llm": {"provider": "conversation", "model": "chat"},
    }
    path = home / "settings.json"
    if legacy:
        home.mkdir()
        path.write_text(json.dumps(data))
        assert not SecretStore(home).key_file.exists()
    else:
        write_managed_config(path, data, home=home)
    with TestClient(app):
        saved = json.loads(path.read_text())
        before = path.read_bytes()
        assert all(entry["api_key"].startswith("enc:v1:")
                   for entry in saved["providers"].values())
        selected = OmegaConf.create({"llm": {
            "api_key": saved["providers"]["conversation"]["api_key"]}})
        assert CredentialResolver.resolve_api_key(
            CredentialResolver.provider_spec("conversation"), selected
        ) == "synthetic-conversation-key"
        assert titler._llm_config()[1] == "synthetic-conversation-key"
        memory = {"llm_provider_id": "facts", "llm_model": "extract",
                  "embed_provider_id": "vectors", "embed_model": "embed"}
        assert config._mem0_llm(saved, memory)["config"]["api_key"] == "synthetic-facts-key"
        assert config._resolve_embedder(saved, memory)["api_key"] == "synthetic-vectors-key"
        assert path.read_bytes() == before
        # Auxiliary calls must fail on key loss, even if a fallback env key exists.
        SecretStore(home).key_file.unlink()
        monkeypatch.setenv("OPENAI_API_KEY", "synthetic-fallback-key")
        for consume in (lambda: config._mem0_llm(saved, memory),
                        lambda: config._resolve_embedder(saved, memory),
                        titler._llm_config):
            with pytest.raises(SecretError):
                consume()
