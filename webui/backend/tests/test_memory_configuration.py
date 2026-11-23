"""Memory uses the same credentials as chat and never silently picks a model."""
from types import SimpleNamespace

import pytest

from app.backends.ms_agent import config as C, memory_configuration as MC
from app.backends.ms_agent import models, providers, sidecar, session_models
from app.backends.ms_agent.mapping import encode_model_id, model_to_schema
from app.backends.errors import BadRequest
from app.schemas.memory import MemoryModelCheck


@pytest.fixture
def configured(monkeypatch):
    data = {
        "llm": {"provider": "gateway", "model": "chat"},
        "providers": {"gateway": {"base_url": "https://example.test/v1"}},
    }
    monkeypatch.setenv("OPENAI_API_KEY", "env-only-secret")
    monkeypatch.setattr(C, "_read_settings", lambda: data)
    monkeypatch.setattr(models, "list_models", lambda *args: [])
    return data


def test_env_credentials_reach_both_memory_clients(configured):
    llm = C._mem0_llm(configured)
    embed = C._resolve_embedder(configured, {
        "embed_provider_id": "gateway", "embed_model": "embed"})
    assert llm["config"]["api_key"] == embed["api_key"] == "env-only-secret"
    assert llm["config"]["model"] == "chat"
    assert llm["config"]["openai_base_url"] == embed["base_url"]
    assert "api_key" not in configured["providers"]["gateway"]


def test_explicit_credentials_override_environment(configured):
    configured["providers"]["gateway"]["api_key"] = "explicit"
    assert C._mem0_llm(configured)["config"]["api_key"] == "explicit"


def test_provider_options_expose_availability_never_keys(configured, monkeypatch):
    monkeypatch.setattr(providers, "list_providers", lambda: [SimpleNamespace(id="gateway")])
    result = [p.model_dump() for p in MC.provider_options()]
    assert result[0]["credentials_available"] is True
    assert "secret" not in str(result) and "api_key" not in str(result)


def test_check_is_read_only_and_only_probes_on_request(configured, monkeypatch):
    calls = []
    monkeypatch.setattr(C, "_probe_embed_dimension", lambda desc: (calls.append(desc) or (1024, True)))
    body = MemoryModelCheck(memory_embed_provider_id="gateway", memory_embed_model="embed")
    assert MC.check_models(body).valid and not calls
    checked = MC.check_models(body.model_copy(update={"probe": True}))
    assert checked.verified and checked.embedder.dimension == 1024
    assert len(calls) == 1


def test_missing_extraction_key_blocks_probe(configured, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setattr(C, "_probe_embed_dimension", lambda _: pytest.fail("must not probe"))
    result = MC.check_models(MemoryModelCheck(
        memory_embed_provider_id="gateway", memory_embed_model="embed", probe=True))
    assert not result.valid and not result.verified
    assert "llm_unavailable" in [e.code for e in result.errors]


def test_known_chat_model_rejected_for_embedding(configured, monkeypatch):
    monkeypatch.setattr(models, "list_models", lambda *args: [SimpleNamespace(name="chat", purpose="chat")])
    result = MC.check_models(MemoryModelCheck(
        memory_embed_provider_id="gateway", memory_embed_model="chat"))
    assert [e.code for e in result.errors] == ["embed_model_type"]


def test_embedding_model_rejected_for_extraction(configured, monkeypatch):
    monkeypatch.setattr(models, "list_models", lambda *args: [SimpleNamespace(name="embed", purpose="embedding")])
    result = MC.check_models(MemoryModelCheck(
        memory_llm_provider_id="gateway", memory_llm_model="embed",
        memory_embed_provider_id="gateway", memory_embed_model="embed"))
    assert [e.code for e in result.errors] == ["llm_model_type"]


def test_probe_errors_are_safe_and_typed(configured, monkeypatch):
    import openai

    class Client:
        def __init__(self, **kwargs):
            self.embeddings = self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def create(self, **kwargs):
            raise ValueError("echoed credential: env-only-secret")

    monkeypatch.setattr(openai, "OpenAI", Client)
    result = MC.check_models(MemoryModelCheck(
        memory_embed_provider_id="gateway", memory_embed_model="embed", probe=True))
    assert result.errors[0].code == "embed_probe_failed"
    assert "secret" not in result.model_dump_json()


def test_build_error_clears_after_credentials_change(configured, monkeypatch):
    from ms_agent.utils import json_store
    monkeypatch.setattr(json_store, "read_json", lambda *args: configured)
    project = SimpleNamespace(id="config-failure")
    monkeypatch.setattr(C, "_project_memory_models", lambda _: {"embed_provider_id": "gateway"})
    MC.record_build_error(project, C.MemoryConfigError("embed_probe_failed", "check failed"))
    assert MC.current_build_error(project).code == "embed_probe_failed"
    token = C._model_snapshot.set(SimpleNamespace(settings={
        **configured, "llm": {"provider": "other-conversation", "model": "another-model"}}))
    try:
        MC.record_build_error(project, C.MemoryConfigError("embed_probe_failed", "runtime failed"))
    finally:
        C._model_snapshot.reset(token)
    assert MC.current_build_error(project).message == "runtime failed"
    monkeypatch.setenv("OPENAI_API_KEY", "replacement")
    assert MC.current_build_error(project) is None
    assert "secret" not in str(sidecar.get("memory", project.id))


def test_embedding_purpose_survives_mapping_and_cannot_select_chat():
    mid = encode_model_id("purpose-test", "embed")
    sidecar.merge("models", mid, {"purpose": "embedding"})
    assert model_to_schema("purpose-test", "embed").purpose == "embedding"
    with pytest.raises(BadRequest, match="Embedding"):
        session_models.validate_selection("purpose-test", "embed", data={
            "providers": {"purpose-test": {"models": ["embed"]}}})
