# Copyright (c) ModelScope Contributors. All rights reserved.
"""Lazy, offline models.dev metadata with validated provenance and exact provider identities."""
from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import math
import re
import threading
import warnings
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

SOURCE = 'https://models.dev/api.json'
LICENSE_SOURCE = 'https://github.com/anomalyco/models.dev/blob/dev/LICENSE'
DATA_DIR = Path(__file__).resolve().parent / 'data'
SNAPSHOT = 'models_dev.json'
MANIFEST = 'models_dev.manifest.json'
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_PROVIDERS = 1024
MAX_MODELS = 100000
_ENV = re.compile(r'[A-Z0-9_]{1,128}')
_NPM = re.compile(r'(?:@[a-z0-9_.-]+/)?[a-z0-9_./-]{1,128}')
_PLACEHOLDER = re.compile(r'\$\{[A-Z0-9_]+\}')

_ALIASES = {
    'zhipu': 'zhipuai',
    'glm': 'zhipuai',
    'bigmodel': 'zhipuai',
    'kimi': 'moonshotai-cn',
    'moonshot': 'moonshotai-cn',
    'dashscope': 'alibaba-cn',
    'minimax': 'minimax-cn',
}
_FAMILIES = (
    frozenset(('moonshotai', 'moonshotai-cn')),
    frozenset(('alibaba', 'alibaba-cn', 'alibaba-token-plan-cn',
               'alibaba-token-plan')),
    frozenset(('minimax', 'minimax-cn')),
    frozenset(('zai', 'zhipuai')),
    frozenset(('siliconflow', 'siliconflow-cn')),
    frozenset(('stepfun', 'stepfun-ai')),
)

# Reviewed inference services with ordinary bearer API keys. Both endpoint AND
# env are pinned, and npm must still be exactly @ai-sdk/openai-compatible.
# This is deliberately not a list derived from npm alone: gateways/proxies,
# coding subscriptions, OAuth, dynamic URLs, and vendor SDKs are not admitted.
# Additions require review; upstream changes never silently widen this list.
_COMPATIBLE = {
    'alibaba': ('https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
                'DASHSCOPE_API_KEY'),
    'zai': ('https://api.z.ai/api/paas/v4', 'ZHIPU_API_KEY'),
    'moonshotai': ('https://api.moonshot.ai/v1', 'MOONSHOT_API_KEY'),
    'longcat': ('https://api.longcat.chat/openai', 'LONGCAT_API_KEY'),
    'xiaomi': ('https://api.xiaomimimo.com/v1', 'XIAOMI_API_KEY'),
    'stepfun': ('https://api.stepfun.com/v1', 'STEPFUN_API_KEY'),
    'stepfun-ai': ('https://api.stepfun.ai/v1', 'STEPFUN_API_KEY'),
    'siliconflow-cn':
    ('https://api.siliconflow.cn/v1', 'SILICONFLOW_CN_API_KEY'),
    'siliconflow': ('https://api.siliconflow.com/v1', 'SILICONFLOW_API_KEY')
}
# Exact official base endpoints, not suffix/substring matching and not learned
# from untrusted snapshot URLs. Paths distinguish regions and billing plans.
_ENDPOINTS = {
    'modelscope': ('https://api-inference.modelscope.cn/v1', ),
    'openai': ('https://api.openai.com/v1', ),
    'anthropic': ('https://api.anthropic.com', 'https://api.anthropic.com/v1'),
    'google': ('https://generativelanguage.googleapis.com/v1beta/openai', ),
    'zhipuai': ('https://open.bigmodel.cn/api/paas/v4', ),
    'moonshotai-cn': ('https://api.moonshot.cn/v1', ),
    'deepseek': ('https://api.deepseek.com', 'https://api.deepseek.com/v1',
                 'https://api.deepseek.com/beta'),
    'alibaba-cn': ('https://dashscope.aliyuncs.com/compatible-mode/v1', ),
    'alibaba-token-plan-cn':
    ('https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1', ),
    'alibaba-token-plan':
    ('https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1',
     ),
    'minimax-cn': ('https://api.minimaxi.com/v1', 'https://api.minimax.cn/v1',
                   'https://api.minimax.cn/anthropic/v1',
                   'https://api.minimaxi.com/anthropic/v1'),
    'minimax':
    ('https://api.minimax.io/v1', 'https://api.minimax.io/anthropic/v1'),
    'openrouter': ('https://openrouter.ai/api/v1', ),
}
_UNSET = object()
_cache = _UNSET
_lock = threading.Lock()


def _require(condition, message):
    if not condition:
        raise ValueError('Invalid model catalog: ' + message)


def _text(value, *, maximum=4096, empty=False):
    _require(
        isinstance(value, str) and len(value) <= maximum
        and (empty or bool(value))
        and not any(ord(c) < 32 and c not in '\n\r\t' for c in value), 'text')


def _number(value, *, minimum=0, integer=False):
    _require(
        type(value) in ((int, ) if integer else
                        (int, float)) and minimum <= value <= 10**15
        and math.isfinite(value), 'finite bounded number')


def _tree(value, depth=0):
    _require(depth <= 24, 'nesting depth')
    if isinstance(value, dict):
        _require(len(value) <= MAX_MODELS, 'object size')
        for key, child in value.items():
            _text(key, maximum=1024)
            _tree(child, depth + 1)
    elif isinstance(value, list):
        _require(len(value) <= 1024, 'array size')
        for child in value:
            _tree(child, depth + 1)
    elif isinstance(value, str):
        _text(value, maximum=65536, empty=True)
    elif type(value) in (int, float):
        _number(value, minimum=-1)
    else:
        _require(value is None or type(value) is bool, 'JSON value')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def _decode(raw, maximum):
    _require(0 < len(raw) <= maximum, 'resource size')
    result = json.loads(raw, object_pairs_hook=_unique_object)
    _tree(result)
    return result


def _api(value):
    """Validate descriptive URLs; templates/local HTTP are metadata only."""
    _text(value, maximum=2048)
    expanded = _PLACEHOLDER.sub('placeholder.invalid', value)
    if value.startswith('${'):
        expanded = 'https://' + expanded
    _require(not re.search(r'[\s{}$\\]', expanded), 'API URL characters')
    url = urlsplit(expanded)
    _require(
        url.scheme in ('https', 'http') and bool(url.hostname)
        and not url.username and not url.password and not url.query
        and not url.fragment, 'API URL')
    _require(url.port is None or 0 < url.port <= 65535, 'API port')


def _protocol(record):
    _require(isinstance(record, dict), 'protocol object')
    if 'npm' in record:
        _require(
            isinstance(record['npm'], str) and _NPM.fullmatch(record['npm']),
            'npm identifier')
    if 'api' in record:
        _api(record['api'])
    if 'shape' in record:
        _require(record['shape'] in ('completions', 'responses'), 'API shape')
    if 'body' in record:
        _require(isinstance(record['body'], dict), 'protocol body')
    if 'headers' in record:
        _require(isinstance(record['headers'], dict), 'protocol headers')
        for key, value in record['headers'].items():
            _require(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', key), 'header name')
            _text(value)
            _require(not re.search(r'[\r\n]', value), 'header value')


def _cost(record, *, tier=False):
    _require(isinstance(record, dict), 'cost object')
    for key, value in record.items():
        if key == 'tiers':
            _require(not tier and isinstance(value, list) and len(value) <= 64,
                     'cost tiers')
            for item in value:
                _require(
                    isinstance(item, dict) and 'tier' in item, 'cost tier')
                _cost(item, tier=True)
        elif key == 'tier':
            _require(
                tier and isinstance(value, dict)
                and value.get('type') == 'context', 'tier discriminator')
            _number(value.get('size'), integer=True)
        elif key == 'context_over_200k':
            _require(not tier, 'nested cost tier')
            _cost(value, tier=True)
        else:
            _number(value)


def _reasoning(options):
    _require(
        isinstance(options, list) and len(options) <= 16,
        'reasoning options array')
    for option in options:
        _require(isinstance(option, dict), 'reasoning option')
        kind = option.get('type')
        _require(
            kind in ('toggle', 'effort', 'budget_tokens'), 'reasoning type')
        allowed = {'type'}
        if kind == 'effort':
            allowed.add('values')
            values = option.get('values')
            _require(
                isinstance(values, list) and 0 < len(values) <= 32,
                'effort values')
            for value in values:
                # Upstream null is retained, never invented as an off option.
                if value is not None:
                    _text(value, maximum=64)
            _require(len(set(values)) == len(values), 'duplicate effort')
        elif kind == 'budget_tokens':
            allowed.update(('min', 'max'))
            for key in ('min', 'max'):
                if key in option:
                    # -1 is an upstream automatic-budget sentinel, not a price.
                    _number(
                        option[key],
                        minimum=-1 if key == 'min' else 0,
                        integer=True)
            if 'min' in option and 'max' in option:
                _require(option['min'] <= option['max'], 'budget range')
        _require(set(option) <= allowed, 'reasoning option fields')


def validate_snapshot(raw: bytes) -> dict:
    """Strict validation shared by runtime, offline builds and the updater."""
    providers = _decode(raw, MAX_SNAPSHOT_BYTES)
    _require(
        isinstance(providers, dict) and 0 < len(providers) <= MAX_PROVIDERS,
        'providers object')
    count = 0
    for provider_id, provider in providers.items():
        _require(
            re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,127}', provider_id),
            'provider identifier')
        _require(
            isinstance(provider, dict) and provider.get('id') == provider_id,
            'provider identity')
        _text(provider.get('name'), maximum=256)
        _require('npm' in provider, 'provider npm')
        _protocol(provider)
        env = provider.get('env')
        _require(isinstance(env, list) and len(env) <= 32, 'provider env')
        for name in env:
            _require(
                isinstance(name, str) and _ENV.fullmatch(name), 'env name')
        models = provider.get('models')
        _require(isinstance(models, dict), 'models object')
        count += len(models)
        _require(count <= MAX_MODELS, 'model count')
        for model_id, model in models.items():
            _text(model_id, maximum=512)
            _require(
                isinstance(model, dict) and model.get('id') == model_id,
                'model identity')
            _text(model.get('name'), maximum=512)
            for field in ('reasoning', 'temperature', 'tool_call',
                          'attachment', 'open_weights', 'structured_output'):
                if field in model:
                    _require(type(model[field]) is bool, field + ' boolean')
            for field in ('reasoning', 'tool_call', 'limit', 'modalities'):
                _require(field in model, 'missing ' + field)
            limit = model['limit']
            _require(
                isinstance(limit, dict)
                and {'context', 'output'} <= set(limit), 'model limits')
            for value in limit.values():
                _number(value, integer=True)
            if 'cost' in model:
                _cost(model['cost'])
            if 'reasoning_options' in model:
                _reasoning(model['reasoning_options'])
            modalities = model['modalities']
            _require(
                isinstance(modalities, dict)
                and set(modalities) == {'input', 'output'}, 'modalities')
            for values in modalities.values():
                _require(
                    isinstance(values, list) and len(values) <= 16,
                    'modality list')
                for value in values:
                    _require(
                        value in ('text', 'image', 'audio', 'video', 'pdf'),
                        'modality')
            if 'provider' in model:
                _protocol(model['provider'])
            if 'experimental' in model:
                experimental = model['experimental']
                _require(
                    isinstance(experimental, dict)
                    and isinstance(experimental.get('modes'), dict),
                    'experimental modes')
                for mode in experimental['modes'].values():
                    _require(isinstance(mode, dict), 'experimental mode')
                    if 'cost' in mode:
                        _cost(mode['cost'])
                    if 'provider' in mode:
                        _protocol(mode['provider'])
    _require(count > 0, 'empty model catalog')
    return providers


def _read(path, maximum):
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    _require(0 < len(raw) <= maximum, 'resource size')
    return raw


def validate_bundle(directory: Path = DATA_DIR) -> tuple[dict, dict]:
    """Fail closed for release builds; never fetch or repair resources."""
    directory = Path(directory)
    manifest = _decode(_read(directory / MANIFEST, 32768), 32768)
    _require(
        isinstance(manifest, dict) and manifest.get('format') == 1,
        'manifest format')
    _require(manifest.get('source') == SOURCE, 'manifest source')
    digest = manifest.get('sha256')
    _require(
        isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest),
        'manifest sha256')
    _require(manifest.get('revision') == 'sha256:' + digest, 'revision')
    fetched_at = manifest.get('fetched_at')
    _text(fetched_at, maximum=64)
    _require(
        datetime.fromisoformat(fetched_at.replace('Z', '+00:00')).tzinfo
        is not None, 'timezone-aware fetched_at')
    license_bytes = _read(directory / 'LICENSE', 65536)
    _require(
        manifest.get('license') == 'MIT'
        and manifest.get('license_source') == LICENSE_SOURCE
        and manifest.get('license_sha256')
        == hashlib.sha256(license_bytes).hexdigest(), 'license provenance')
    _require(
        b'MIT License' in license_bytes
        and b'Copyright (c) 2025 models.dev' in license_bytes,
        'upstream license')
    raw = _read(directory / SNAPSHOT, MAX_SNAPSHOT_BYTES)
    _require(hashlib.sha256(raw).hexdigest() == digest, 'snapshot checksum')
    providers = validate_snapshot(raw)
    _require(
        manifest.get('provider_count') == len(providers)
        and manifest.get('model_count') == sum(
            len(p['models']) for p in providers.values()), 'manifest counts')
    return providers, manifest


def _load():
    global _cache
    if _cache is _UNSET:
        with _lock:
            if _cache is _UNSET:
                try:
                    bundle = validate_bundle(DATA_DIR)
                except (OSError, ValueError, TypeError, RecursionError):
                    bundle = None
                if __package__:
                    from .catalog_update import choose_bundle
                    bundle = choose_bundle(bundle)
                _cache = bundle
                if bundle is None:
                    warnings.warn(
                        'Model catalog unavailable; using manual model '
                        'configuration.',
                        RuntimeWarning,
                        stacklevel=2)
    return _cache


def _endpoint(base_url):
    if not isinstance(base_url, str) or not base_url or re.search(
            r'[\s\\%{}]', base_url):
        return None
    try:
        url = urlsplit(base_url)
        if (url.scheme != 'https' or not url.hostname or url.username
                or url.password or url.query or url.fragment
                or url.port not in (None, 443)):
            return None
        return url.hostname.lower(), url.path.rstrip('/')
    except ValueError:
        return None


def _resolve(provider_id, base_url, providers):
    if not isinstance(provider_id, str):
        return None
    key = provider_id.lower()
    key = _ALIASES.get(key, key)
    endpoint = _endpoint(base_url)
    match = None
    if endpoint:
        for candidate, urls in _ENDPOINTS.items():
            if any(endpoint == _endpoint(url) for url in urls):
                match = candidate
                break
        if match is None:
            for candidate, (url, _) in _COMPATIBLE.items():
                if endpoint == _endpoint(url):
                    match = candidate
                    break
    if match is not None:
        if (key in providers and key != match
                and not any({key, match} <= family for family in _FAMILIES)):
            return None
        key = match
    return key if key in providers else None


def _provider_record(provider_id, base_url):
    bundle = _load()
    if bundle is None:
        return None
    providers, manifest = bundle
    key = _resolve(provider_id, base_url, providers)
    if key is None:
        return None
    return key, providers[key], manifest['revision']


def _annotate(record, provider_id, revision):
    result = copy.deepcopy(record)
    result['catalog_provider'] = provider_id
    result['catalog_revision'] = revision
    return result


def get_provider(provider_id: str, *, base_url: str = '') -> dict | None:
    """Return a detached provider record, including unmodified model fields."""
    record = _provider_record(provider_id, base_url)
    if record is None:
        return None
    key, provider, revision = record
    return _annotate(provider, key, revision)


def get_model(provider_id: str,
              model_id: str,
              *,
              base_url: str = '') -> dict | None:
    """Return raw model fields plus provenance; absent fields stay absent."""
    if not isinstance(model_id, str) or not model_id:
        return None
    record = _provider_record(provider_id, base_url)
    if record is None:
        return None
    key, provider, revision = record
    models = provider['models']
    model = models.get(model_id)
    if model is None:
        # Case is the only tolerated spelling difference. Ambiguity is unknown.
        matches = [
            value for name, value in models.items()
            if name.casefold() == model_id.casefold()
        ]
        if len(matches) != 1:
            return None
        model = matches[0]
    return _annotate(model, key, revision)


def list_model_ids(provider_id: str, *, base_url: str = '') -> list[str]:
    record = _provider_record(provider_id, base_url)
    return list(record[1]['models']) if record else []


def catalog_info() -> dict:
    bundle = _load()
    if bundle is None:
        return {
            'source': SOURCE,
            'revision': None,
            'fetched_at': None,
            'available': False
        }
    return dict(copy.deepcopy(bundle[1]), available=True)


def compatible_providers() -> list[dict]:
    """Reviewed additions for spec.py; no SDK imports or model-name keywords."""
    bundle = _load()
    if bundle is None:
        return []
    result = []
    for key, (api, env) in _COMPATIBLE.items():
        provider = bundle[0].get(key)
        if (provider and provider.get('npm') == '@ai-sdk/openai-compatible'
                and provider.get('api') == api
                and provider.get('env') == [env] and set(provider) <=
            {'id', 'name', 'api', 'env', 'npm', 'doc', 'models'}
                and provider['models']
                and all(not model.get('provider')
                        for model in provider['models'].values())):
            result.append({
                field: copy.deepcopy(provider[field])
                for field in ('id', 'name', 'api', 'env')
            })
    return result


async def download(timeout: float = 8) -> bytes:
    """Bound total request time and compressed/decompressed sizes; no redirects."""
    import aiohttp

    async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout),
            auto_decompress=False) as client:
        async with client.get(
                SOURCE,
                allow_redirects=False,
                headers={
                    'User-Agent': 'MS-Agent-model-catalog/1.0',
                    'Accept': 'application/json',
                    'Accept-Encoding': 'gzip'
                }) as response:
            if response.status != 200 or str(response.url) != SOURCE:
                raise ValueError('Unexpected models.dev response')
            wire = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                wire.extend(chunk)
                if len(wire) > MAX_SNAPSHOT_BYTES:
                    raise ValueError('Compressed catalog exceeds size limit')
            encoding = response.headers.get('Content-Encoding', '').lower()
    if encoding == 'gzip':
        with gzip.GzipFile(fileobj=io.BytesIO(wire)) as stream:
            raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
    elif encoding in ('', 'identity'):
        raw = bytes(wire)
    else:
        raise ValueError('Unsupported catalog content encoding')
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError('Catalog exceeds decompressed size limit')
    return raw


def manifest_for(raw: bytes, fetched_at: str) -> dict:
    providers = validate_snapshot(raw)
    license_bytes = _read(DATA_DIR / 'LICENSE', 65536)
    digest = hashlib.sha256(raw).hexdigest()
    return {
        'format': 1,
        'source': SOURCE,
        'revision': 'sha256:' + digest,
        'sha256': digest,
        'fetched_at': fetched_at,
        'provider_count': len(providers),
        'model_count': sum(len(p['models']) for p in providers.values()),
        'license': 'MIT',
        'license_source': LICENSE_SOURCE,
        'license_sha256': hashlib.sha256(license_bytes).hexdigest()
    }
