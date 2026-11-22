"""Native constructors decrypt even when callers bypass the model factory."""
from unittest.mock import patch

import pytest
from omegaconf import OmegaConf

from ms_agent.config.secrets import HOME_FIELD, SecretError, SecretStore


@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
@pytest.mark.parametrize('explicit', [False, True])
def test_native_clients_resolve_selected_key_without_mutating_config(
        tmp_path, monkeypatch, protocol, explicit):
    from ms_agent.llm.openai_llm import OpenAI
    from ms_agent.llm.anthropic_llm import Anthropic
    home = tmp_path / 'instance'
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path / 'unrelated'))
    monkeypatch.setenv('OPENAI_API_KEY', 'environment-fallback-must-not-win')
    cipher = SecretStore(home).encrypt('synthetic-native-key')
    field = protocol + '_api_key'
    config = OmegaConf.create({
        HOME_FIELD: str(home),
        'llm': {
            'service': protocol,
            'model': 'm',
            field: cipher
        }
    })
    constructor = OpenAI if protocol == 'openai' else Anthropic
    with patch('openai.OpenAI' if protocol ==
               'openai' else 'anthropic.Anthropic') as client:
        constructor(config, **({'api_key': cipher} if explicit else {}))
        assert client.call_args.kwargs['api_key'] == 'synthetic-native-key'
        assert config.llm[field] == cipher
        SecretStore(home).key_file.unlink()
        with pytest.raises(SecretError):
            constructor(config, **({'api_key': cipher} if explicit else {}))
        assert client.call_count == 1
