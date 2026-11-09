# Copyright (c) ModelScope Contributors. All rights reserved.
"""Offline catalog, trust boundaries and explicit release synchronization."""
import copy
import gzip
import importlib.util
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_file(path):
    spec = importlib.util.spec_from_file_location('_catalog_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def catalog():
    return load_file(ROOT / 'ms_agent/llm/model_catalog.py')


@pytest.fixture
def updater():
    return load_file(ROOT / '.dev_scripts/update_model_catalog.py')


@pytest.fixture
def small():
    return {'test': {'id': 'test', 'name': 'Test',
                     'npm': '@ai-sdk/openai-compatible',
                     'api': 'https://test.invalid/v1', 'env': ['TEST_API_KEY'],
                     'models': {'Model': {
                         'id': 'Model', 'name': 'Model', 'reasoning': True,
                         'tool_call': True, 'temperature': False,
                         'limit': {'context': 1000, 'output': 100},
                         'cost': {'input': 0, 'output': 2},
                         'modalities': {'input': ['text'], 'output': ['text']},
                     }}}}


def encoded(data):
    return json.dumps(data).encode()


def test_import_is_lazy_and_queries_read_once(catalog, monkeypatch):
    assert catalog._cache is catalog._UNSET
    validate = Mock(wraps=catalog.validate_bundle)
    monkeypatch.setattr(catalog, 'validate_bundle', validate)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: catalog.catalog_info(), range(16)))
    assert validate.call_count == 1
    assert all(result['available'] for result in results)
    providers = catalog._cache[0]
    assert results[0]['provider_count'] == len(providers)
    assert results[0]['model_count'] == sum(len(p['models']) for p in providers.values())
    assert results[0]['revision'] == 'sha256:' + results[0]['sha256']


@pytest.mark.parametrize('alias, expected', [
    ('zhipu', 'zhipuai'), ('GLM', 'zhipuai'), ('bigmodel', 'zhipuai'),
    ('kimi', 'moonshotai-cn'), ('moonshot', 'moonshotai-cn'),
    ('dashscope', 'alibaba-cn'), ('minimax', 'minimax-cn'), ('google', 'google'),
])
def test_aliases(catalog, alias, expected):
    assert catalog.get_provider(alias)['id'] == expected
    assert catalog.get_provider(alias)['catalog_provider'] == expected


@pytest.mark.parametrize('provider, url, expected', [
    ('kimi', 'https://api.moonshot.ai/v1', 'moonshotai'),
    ('moonshotai', 'https://api.moonshot.cn/v1/', 'moonshotai-cn'),
    ('dashscope', 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1', 'alibaba'),
    ('minimax', 'https://api.minimax.io/v1', 'minimax'),
    ('minimax', 'https://api.minimaxi.com/v1', 'minimax-cn'),
    ('minimax', 'https://api.minimax.cn/v1', 'minimax-cn'),
    ('zhipu', 'https://api.z.ai/api/paas/v4', 'zai'),
    ('private-alias', 'https://API.OPENAI.COM:443/v1/', 'openai'),
    ('', 'https://api.minimax.io/anthropic/v1', 'minimax'),
    ('custom', 'https://api.longcat.chat/openai', 'longcat'),
    ('custom', 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1', 'alibaba-token-plan-cn'),
    ('dashscope', 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1', 'alibaba-token-plan-cn'),
])
def test_official_endpoints(catalog, provider, url, expected):
    assert catalog.get_provider(provider, base_url=url)['id'] == expected


@pytest.mark.parametrize('url', [
    'https://api.moonshot.ai.evil.invalid/v1',
    'https://evil.invalid/api.moonshot.ai/v1',
    'https://api.moonshot.ai@evil.invalid/v1',
    'https://evil@api.moonshot.ai/v1',
    'https://api.moonshot.ai:444/v1',
    'http://api.moonshot.ai/v1',
    'https://api.moonshot.ai/v1/chat/completions',
    'https://api.moonshot.ai/v1?region=cn',
    'https://api.moonshot.ai/v1#fragment',
    'https://api.moonshot.ai/%76%31',
    'https://api.moonshot.ai/v1/../v1',
    'https://api.moonshot.ai/v1\\evil',
    'https://api.moonshot.ai/v1\n',
    'https://[invalid/v1',
    'https://api.moonshot.ai:invalid/v1',
    'https://open.bigmodel.cn/api/coding/paas/v4',
])
def test_no_endpoint_suffix_or_path_guessing(catalog, url):
    assert catalog.get_provider('custom', base_url=url) is None
    # An unknown endpoint cannot change an explicitly chosen identity/region.
    assert catalog.get_provider('kimi', base_url=url)['id'] == 'moonshotai-cn'


def test_no_cross_provider_model_guess(catalog):
    assert catalog.get_model('private', 'gpt-4o', base_url='https://private/v1') is None
    assert catalog.get_model('', 'gpt-4o') is None
    assert catalog.get_model('deepseek', 'gpt-4o') is None
    assert catalog.get_model('openai', 'openai/gpt-4o') is None
    assert catalog.get_provider('openai', base_url='https://api.moonshot.cn/v1') is None
    assert catalog.list_model_ids('private') == []


def test_raw_deep_copy_missing_empty_and_case(catalog, small):
    models = small['test']['models']
    models['empty'] = dict(copy.deepcopy(models['Model']), id='empty',
                           reasoning_options=[])
    models['controls'] = dict(copy.deepcopy(models['Model']), id='controls',
                              reasoning_options=[
                                  {'type': 'effort', 'values': [None, 'high']},
                                  {'type': 'budget_tokens', 'min': -1, 'max': 20}])
    catalog._cache = (small, {'revision': 'fixture'})
    found = catalog.get_model('test', 'MODEL')
    assert found['id'] == 'Model'
    assert 'reasoning_options' not in found
    assert found['catalog_revision'] == 'fixture'
    assert catalog.get_model('test', 'empty')['reasoning_options'] == []
    assert catalog.get_model('test', 'controls')['reasoning_options'][0]['values'][0] is None
    found['cost']['input'] = 999
    provider = catalog.get_provider('test')
    provider['models'].clear()
    ids = catalog.list_model_ids('test')
    ids.clear()
    assert catalog.get_model('test', 'Model')['cost']['input'] == 0
    models['model'] = dict(copy.deepcopy(models['Model']), id='model')
    assert catalog.get_model('test', 'MODEL') is None
    assert catalog.get_model('test', 'Model')['id'] == 'Model'


def test_pinned_snapshot_matches_raw_fields(catalog):
    providers, _ = catalog.validate_bundle()
    for provider_id in ('openai', 'google', 'anthropic', 'moonshotai-cn'):
        for model_id, raw in providers[provider_id]['models'].items():
            result = catalog.get_model(provider_id, model_id)
            result.pop('catalog_provider')
            result.pop('catalog_revision')
            assert result == raw


@pytest.mark.parametrize('damage', ['missing', 'json', 'checksum', 'manifest', 'license'])
def test_runtime_failure_warns_once(catalog, tmp_path, monkeypatch, damage):
    for name in (catalog.SNAPSHOT, catalog.MANIFEST, 'LICENSE'):
        (tmp_path / name).write_bytes((catalog.DATA_DIR / name).read_bytes())
    if damage == 'missing':
        (tmp_path / catalog.SNAPSHOT).unlink()
    elif damage == 'json':
        (tmp_path / catalog.SNAPSHOT).write_bytes(b'{')
    elif damage == 'checksum':
        with (tmp_path / catalog.SNAPSHOT).open('ab') as stream:
            stream.write(b' ')
    elif damage == 'manifest':
        (tmp_path / catalog.MANIFEST).write_bytes(b'[]')
    else:
        (tmp_path / 'LICENSE').write_bytes(b'invalid')
    monkeypatch.setattr(catalog, 'DATA_DIR', tmp_path)
    with pytest.warns(RuntimeWarning) as captured:
        for _ in range(3):
            assert catalog.get_model('openai', 'gpt-4o') is None
            assert catalog.get_provider('openai') is None
            assert catalog.list_model_ids('openai') == []
            assert catalog.compatible_providers() == []
            assert catalog.catalog_info()['available'] is False
    assert len(captured) == 1


@pytest.mark.parametrize('path, value', [
    (('id',), 'wrong'), (('env',), ['BAD;NAME']), (('npm',), ['@ai-sdk/openai']),
    (('api',), 'file:///etc/passwd'), (('api',), 'https://u:p@api.invalid/v1'),
    (('models', 'Model', 'reasoning'), 'true'),
    (('models', 'Model', 'cost', 'input'), -1),
    (('models', 'Model', 'cost', 'input'), float('nan')),
    (('models', 'Model', 'cost', 'input'), float('inf')),
    (('models', 'Model', 'cost', 'input'), True),
    (('models', 'Model', 'limit', 'context'), 1.5),
    (('models', 'Model', 'limit', 'context'), 10**400),
    (('models', 'Model', 'reasoning_options'), None),
    (('models', 'Model', 'reasoning_options'), [{'type': 'invented'}]),
    (('models', 'Model', 'reasoning_options'), [{'type': 'budget_tokens', 'min': -2}]),
    (('models', 'Model', 'reasoning_options'), [{'type': 'budget_tokens', 'min': 20, 'max': 1}]),
    (('models', 'Model', 'modalities'), {'input': ['unknown'], 'output': ['text']}),
    (('models', 'Model', 'provider'), {'npm': 'file:evil'}),
    (('models', 'Model', 'provider'), {'api': 'javascript:evil'}),
    (('models', 'Model', 'provider'), {'shape': 'unknown'}),
    (('models', 'Model', 'provider'), {'headers': {'x-key': 'a\r\nb'}}),
    (('models', 'Model', 'cost'), {'tiers': [{'input': 1}]}),
    (('models', 'Model', 'cost'), {'context_over_200k': {'input': -1}}),
    (('models', 'Model', 'experimental'), {'modes': {'fast': {'cost': {'input': -1}}}}),
])
def test_untrusted_structure_and_numbers(catalog, small, path, value):
    target = small['test']
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        catalog.validate_snapshot(encoded(small))


def test_duplicates_size_and_nesting(catalog, small, monkeypatch):
    with pytest.raises(ValueError, match='duplicate'):
        catalog.validate_snapshot(b'{"test":{},"test":{}}')
    with pytest.raises((ValueError, RecursionError)):
        catalog.validate_snapshot(b'[' * 100 + b'0' + b']' * 100)
    monkeypatch.setattr(catalog, 'MAX_SNAPSHOT_BYTES', 100)
    with pytest.raises(ValueError, match='size'):
        catalog.validate_snapshot(encoded(small))


def test_reproducible_update_and_failure_preserves_bundle(updater, small, tmp_path):
    raw = encoded(small)
    timestamp = '2026-09-21T00:00:00+00:00'
    updater.update(raw, timestamp, tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    updater.update(raw + b'\n', timestamp, tmp_path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert (tmp_path / updater.catalog.SNAPSHOT).read_bytes() == raw + b'\n'
    assert updater.main(['--check', '--output-dir', str(tmp_path)]) == 0
    with pytest.raises(ValueError):
        updater.update(b'{"invalid":{}}', timestamp, tmp_path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_replace_failure_rolls_back(updater, small, tmp_path, monkeypatch):
    timestamp = '2026-09-21T00:00:00+00:00'
    updater.update(encoded(small), timestamp, tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    replace = updater.os.replace

    def fail_manifest(source, destination):
        if source.name == updater.catalog.MANIFEST:
            raise OSError('simulated failed replacement')
        replace(source, destination)

    monkeypatch.setattr(updater.os, 'replace', fail_manifest)
    small['test']['models']['Model']['cost']['input'] = 1
    with pytest.raises(OSError):
        updater.update(encoded(small), timestamp, tmp_path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize('kind', ['gzip', 'oversized', 'redirect', 'timeout'])
def test_shared_download_is_bounded(updater, small, monkeypatch, kind):
    import asyncio
    import aiohttp
    from types import SimpleNamespace

    raw = encoded(small)
    payload = gzip.compress(raw if kind != 'oversized' else b'x' * 20000)
    if kind == 'oversized':
        monkeypatch.setattr(updater.catalog, 'MAX_SNAPSHOT_BYTES', 1000)

    class Response:
        status = 302 if kind == 'redirect' else 200
        url = updater.catalog.SOURCE
        headers = {'Content-Encoding': 'gzip'}
        async def __aenter__(self):
            if kind == 'timeout':
                raise asyncio.TimeoutError()
            return self
        async def __aexit__(self, *args):
            pass
        async def iter_chunked(self, size):
            yield payload
        @property
        def content(self):
            return self

    class Client:
        def __init__(self, **kwargs):
            assert kwargs['timeout'].total == 60
            assert kwargs['auto_decompress'] is False
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def get(self, url, **kwargs):
            assert url == updater.catalog.SOURCE
            assert kwargs['allow_redirects'] is False
            assert kwargs['headers']['Accept-Encoding'] == 'gzip'
            return Response()

    monkeypatch.setattr(aiohttp, 'ClientSession', Client)
    if kind == 'gzip':
        assert updater.download() == raw
    else:
        with pytest.raises((ValueError, TimeoutError)):
            updater.download()


def test_strict_provider_admission(catalog):
    providers, manifest = catalog.validate_bundle()
    catalog._cache = (providers, manifest)
    assert {p['id'] for p in catalog.compatible_providers()} == {
        'alibaba', 'zai', 'moonshotai', 'longcat', 'xiaomi',
        'stepfun', 'stepfun-ai', 'siliconflow-cn', 'siliconflow'}
    for key in ('azure', 'amazon-bedrock', 'google-vertex', 'github-copilot',
                'infomaniak', 'cloudflare-workers-ai', 'lmstudio', 'openai',
                'groq', 'cerebras', 'llmgateway', 'agentrouter', '302ai'):
        assert key not in {p['id'] for p in catalog.compatible_providers()}
    providers['alibaba']['npm'] = '@ai-sdk/openai'
    providers['zai']['api'] += '.evil'
    providers['moonshotai']['env'].append('OTHER_AUTH')
    providers['longcat']['headers'] = {'required-auth': 'extra'}
    next(iter(providers['xiaomi']['models'].values()))['provider'] = {'shape': 'responses'}
    names = {p['id'] for p in catalog.compatible_providers()}
    assert not {'alibaba', 'zai', 'moonshotai', 'longcat', 'xiaomi'} & names


def test_registry_keeps_original_ten_and_safe_defaults():
    from ms_agent.llm.spec import ProviderRegistry
    registry = ProviderRegistry()
    providers = registry.list_providers()
    assert [p.name for p in providers[:10]] == [
        'modelscope', 'openai', 'anthropic', 'google', 'zhipu', 'kimi',
        'deepseek', 'dashscope', 'minimax', 'openrouter']
    assert [p.default_base_url for p in providers[:10]] == [
        'https://api-inference.modelscope.cn/v1', 'https://api.openai.com/v1',
        'https://api.anthropic.com',
        'https://generativelanguage.googleapis.com/v1beta/openai/',
        'https://open.bigmodel.cn/api/paas/v4', 'https://api.moonshot.cn/v1',
        'https://api.deepseek.com/v1',
        'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'https://api.minimaxi.com/v1', 'https://openrouter.ai/api/v1']
    assert len(providers) == 19
    for provider in providers[10:]:
        assert provider.transport == 'openai_compat'
        assert provider.keywords == []
        assert provider.aliases == []
        assert provider.continue_gen_mode is None
    assert registry.resolve_by_model('some-random-model') is None


def test_missing_catalog_does_not_remove_original_providers(monkeypatch):
    from ms_agent.llm import model_catalog
    from ms_agent.llm.spec import ProviderRegistry
    monkeypatch.setattr(model_catalog, '_cache', None)
    assert len(ProviderRegistry().list_providers()) == 10


def test_new_providers_resolve_env_and_create_compatible_transport(monkeypatch):
    from omegaconf import OmegaConf

    from ms_agent.llm import router
    from ms_agent.llm.model_catalog import list_model_ids
    from ms_agent.llm.spec import ProviderRegistry
    transport = Mock()
    monkeypatch.setattr(router, '_build_transport', transport)
    for provider in ProviderRegistry().list_providers()[10:]:
        monkeypatch.setenv(provider.api_key_env[0], 'catalog-test-key')
        model_id = list_model_ids(provider.name)[0]
        instance = router.ProviderRouter().create(OmegaConf.create({
            'llm': {'service': provider.name, 'model': model_id}}))
        spec, model, key, url, _ = transport.call_args.args
        assert instance.spec.name == provider.name
        assert spec.transport == 'openai_compat'
        assert model == model_id
        assert key == 'catalog-test-key'
        assert url == provider.default_base_url


def test_same_model_name_is_provider_scoped_and_missing_price_stays_unknown(catalog, small):
    small['other'] = copy.deepcopy(small['test'])
    small['other']['id'] = 'other'
    small['other']['models']['Model'].pop('cost')
    catalog._cache = (small, {'revision': 'fixture'})
    assert catalog.get_model('test', 'Model')['cost']['input'] == 0
    assert 'cost' not in catalog.get_model('other', 'Model')
    assert catalog.get_model('private', 'Model') is None


def test_local_input_cli_requires_provenance_and_preserves_failure(updater, small, tmp_path):
    source = tmp_path / 'upstream.json'
    output = tmp_path / 'bundle'
    output.mkdir()
    source.write_bytes(encoded(small))
    args = ['--input', str(source), '--output-dir', str(output)]
    with pytest.raises(SystemExit):
        updater.main(args)
    args.extend(['--fetched-at', '2026-09-21T00:00:00Z'])
    assert updater.main(args) == 0
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    source.write_bytes(b'not JSON')
    assert updater.main(args) == 1
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}
