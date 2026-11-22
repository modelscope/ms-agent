"""Auxiliary search consumers follow the resolver's instance home."""
from omegaconf import OmegaConf
import pytest

from ms_agent.config.secrets import HOME_FIELD, SecretError, SecretStore
from ms_agent.tools.search.websearch_tool import get_content_fetcher


def test_extractor_uses_bound_home_without_plaintext_config_mutation(
        tmp_path, monkeypatch):
    home = tmp_path / 'instance'
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path / 'another-instance'))
    value = SecretStore(home).encrypt('synthetic-search-secret')
    config = OmegaConf.create({HOME_FIELD: str(home)})
    fetcher = get_content_fetcher(
        'tavily_extract', tavily_api_key=value, secret_config=config)
    assert fetcher._api_key == 'synthetic-search-secret'
    assert value.startswith('enc:v1:')
    SecretStore(home).key_file.unlink()
    with pytest.raises(SecretError):
        get_content_fetcher(
            'tavily_extract', tavily_api_key=value, secret_config=config)
