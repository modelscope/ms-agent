# Copyright (c) ModelScope Contributors. All rights reserved.
import json

from ms_agent.config.model_settings import ModelSettingsManager


def test_add_list_remove_provider(tmp_path):
    m = ModelSettingsManager(global_dir=str(tmp_path))
    m.add_provider('acme', name='Acme', protocol='openai',
                   api_key='k', base_url='https://acme/v1', models=['a-1'])
    customs = m.list_custom_providers()
    assert customs['acme']['base_url'] == 'https://acme/v1'
    assert 'a-1' in customs['acme']['models']
    # builtin + custom listed together
    ids = {p['id'] for p in m.list_providers()}
    assert 'acme' in ids and 'openai' in ids and 'deepseek' in ids
    m.remove_provider('acme')
    assert 'acme' not in m.list_custom_providers()


def test_models_and_default(tmp_path):
    m = ModelSettingsManager(global_dir=str(tmp_path))
    m.add_provider('acme', protocol='openai')
    m.add_model('acme', 'a-2')
    assert 'a-2' in m.list_custom_providers()['acme']['models']
    m.set_default_model('a-2', provider='acme')
    assert m.get_default_model() == 'acme/a-2'
    m.remove_model('acme', 'a-2')
    assert 'a-2' not in m.list_custom_providers()['acme']['models']


def test_preserves_other_sections(tmp_path):
    p = tmp_path / 'settings.json'
    p.write_text(json.dumps({'theme': 'dark', 'llm': {'provider': 'x'}}))
    m = ModelSettingsManager(global_dir=str(tmp_path))
    m.add_provider('acme', protocol='openai')
    data = json.loads(p.read_text())
    assert data['theme'] == 'dark' and data['llm']['provider'] == 'x'
    assert 'acme' in data['providers']


def test_resolver_consumes_default_model():
    from ms_agent.config.resolver import ConfigResolver
    cfg = ConfigResolver._settings_to_agent_config(
        {'default_model': 'deepseek/deepseek-chat'})
    assert cfg.llm.service == 'deepseek'
    assert cfg.llm.model == 'deepseek-chat'
    # explicit llm.model wins over default_model
    cfg2 = ConfigResolver._settings_to_agent_config(
        {'llm': {'model': 'pinned'}, 'default_model': 'deepseek/x'})
    assert cfg2.llm.model == 'pinned'
