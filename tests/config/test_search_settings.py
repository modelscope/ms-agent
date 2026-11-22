import json

from ms_agent.config.search_settings import SearchSettingsManager


def test_default_engine_when_empty(tmp_path):
    m = SearchSettingsManager(tmp_path)
    cur = m.get()
    assert cur.engine == 'tavily'
    assert cur.enabled is True
    assert cur.has_key is False
    assert cur.supports_keyless is True


def test_set_engine_preserves_other_keys(tmp_path):
    m = SearchSettingsManager(tmp_path)
    m.set_engine('exa')
    m.set_api_key('exa-secret')
    m.set_engine('tavily')
    data = json.loads((tmp_path / 'settings.json').read_text())
    block = data['tools']['web_search']
    assert block['engine'] == 'tavily'
    assert block['exa_api_key'] == 'exa-secret'
    assert block.get('mcp') is False


def test_clear_exa_key_drops_legacy_aliases(tmp_path):
    p = tmp_path / 'settings.json'
    p.write_text(json.dumps({
        'tools': {
            'web_search': {
                'engine': 'exa',
                'exa_api_key': 'new',
                'api_key': 'legacy',
            }
        }
    }))
    m = SearchSettingsManager(tmp_path)
    assert m.get().has_key is True
    m.set_api_key(None)
    block = json.loads(p.read_text())['tools']['web_search']
    assert 'exa_api_key' not in block
    assert 'api_key' not in block
    assert m.get().has_key is False


def test_arxiv_rejects_key(tmp_path):
    m = SearchSettingsManager(tmp_path)
    m.set_engine('arxiv')
    try:
        m.set_api_key('x')
        raise AssertionError('expected ValueError')
    except ValueError as exc:
        assert 'arxiv' in str(exc)


def test_unknown_engine_rejected(tmp_path):
    m = SearchSettingsManager(tmp_path)
    try:
        m.set_engine('bing')
        raise AssertionError('expected ValueError')
    except ValueError as exc:
        assert 'Unknown' in str(exc)


def test_preserves_unrelated_settings(tmp_path):
    p = tmp_path / 'settings.json'
    p.write_text(json.dumps({'theme': 'dark', 'llm': {'model': 'x'}}))
    m = SearchSettingsManager(tmp_path)
    m.set_engine('arxiv')
    data = json.loads(p.read_text())
    assert data['theme'] == 'dark'
    assert data['llm']['model'] == 'x'
