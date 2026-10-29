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
    data = json.loads((tmp_path / 'settings.json').read_text())
    assert data['llm']['provider'] == 'acme'
    assert data['llm']['model'] == 'a-2'
    m.set_default_model('acme glued-id', provider='acme')
    assert m.get_default_model() == 'acme/glued-id'
    m.remove_model('acme', 'a-2')
    assert 'a-2' not in m.list_custom_providers()['acme']['models']
    assert m.remove_model('acme', 'missing') is False


def test_add_model_materializes_a_provider_without_inventing_metadata(tmp_path):
    """The entry a first model creates must describe nothing but that model.

    Readers merge these entries over the built-in registry, so a stored field is
    taken as the user's own override. Seeding a name and a protocol here made
    adding the first model to a built-in provider an unasked-for rename (to its
    id) and an unasked-for protocol change.
    """
    m = ModelSettingsManager(global_dir=str(tmp_path))
    m.add_model('google', 'gemini-3-pro')
    assert m.list_custom_providers()['google'] == {'models': ['gemini-3-pro']}


def test_preserves_other_sections(tmp_path):
    p = tmp_path / 'settings.json'
    p.write_text(json.dumps({'theme': 'dark', 'llm': {'provider': 'x'}}))
    m = ModelSettingsManager(global_dir=str(tmp_path))
    m.add_provider('acme', protocol='openai')
    data = json.loads(p.read_text())
    assert data['theme'] == 'dark' and data['llm']['provider'] == 'x'
    assert 'acme' in data['providers']


def test_patch_provider_does_not_reset_protocol(tmp_path):
    m = ModelSettingsManager(global_dir=str(tmp_path))
    m.add_provider(
        'acme', protocol='anthropic', api_key='old',
        base_url='https://old/v1')
    m.patch_provider('acme', api_key='new')
    entry = m.list_custom_providers()['acme']
    assert entry['protocol'] == 'anthropic'
    assert entry['api_key'] == 'new'
    assert entry['base_url'] == 'https://old/v1'
    m.patch_provider('acme', clear_api_key=True)
    assert 'api_key' not in m.list_custom_providers()['acme']


def test_resolver_consumes_default_model():
    from ms_agent.config.resolver import ConfigResolver
    cfg = ConfigResolver._settings_to_agent_config(
        {'default_model': 'deepseek/deepseek-chat'})
    assert cfg.llm.service == 'deepseek'
    assert cfg.llm.model == 'deepseek-chat'
    glued = ConfigResolver._settings_to_agent_config(
        {'default_model': 'minimax/minimax MiniMax-M2.1'})
    assert glued.llm.service == 'minimax'
    assert glued.llm.model == 'MiniMax-M2.1'
    # explicit llm.model wins over default_model
    cfg2 = ConfigResolver._settings_to_agent_config(
        {'llm': {'model': 'pinned'}, 'default_model': 'deepseek/x'})
    assert cfg2.llm.model == 'pinned'


def test_resolver_copies_provider_catalog_credentials():
    from ms_agent.config.resolver import ConfigResolver
    cfg = ConfigResolver._settings_to_agent_config({
        'default_model': 'openai/qwen3.7-plus',
        'providers': {
            'openai': {
                'api_key': 'sk-cat',
                'base_url': 'https://example.invalid/v1',
                'protocol': 'openai',
            },
        },
    })
    assert cfg.llm.service == 'openai'
    assert cfg.llm.model == 'qwen3.7-plus'
    assert cfg.llm.openai_api_key == 'sk-cat'
    assert cfg.llm.openai_base_url == 'https://example.invalid/v1'
    assert cfg.llm.protocol == 'openai'
