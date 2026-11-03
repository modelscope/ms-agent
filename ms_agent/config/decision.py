"""Decision profiles and persisted defaults, shared by every SDK interface."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from ms_agent.utils.json_store import json_transaction, read_json

DEFAULTS = {
    'protocol': 'systemone',
    'policy_version': 'v1',
    'context': {
        'enabled': True,
        'trigger_ratio': 0.85,
        'target_ratio': 0.65,
        'keep_probability_max': 0.05,
        'protect_recent_groups': 2,
        'max_decision_requests': 2,
        'decision_timeout_seconds': 5,
        'summary_max_chunks': 4
    },
    'supervision': {
        'enabled': True,
        'intervention_threshold': 0.95,
        'max_process_checks': 6,
        'max_finish_checks': 2,
        'max_reflections': 2,
        'max_finish_corrections': 1,
        'cooldown_tool_rounds': 3,
        'decision_timeout_seconds': 2
    },
}


def mode(value):
    if value not in ('standard', 'decision'):
        raise ValueError('Unknown execution mode')
    return value


def profile(value: dict) -> dict:
    result = deepcopy(DEFAULTS)
    for key in ('provider', 'model', 'base_url', 'protocol', 'policy_version'):
        if key in value:
            result[key] = value[key]
    if result['protocol'] != 'systemone' or result['policy_version'] != 'v1':
        raise ValueError('Unsupported decision protocol or policy version')
    if result.get('base_url'):
        from urllib.parse import urlsplit
        parsed = urlsplit(result['base_url'])
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query
                or parsed.fragment):
            raise ValueError('Invalid decision endpoint')
    for section in ('context', 'supervision'):
        options = value.get(section) or {}
        if set(options) - set(DEFAULTS[section]):
            raise ValueError(f'Unknown {section} decision option')
        result[section].update(options)
        for key, val in result[section].items():
            if key == 'enabled':
                if not isinstance(val, bool):
                    raise ValueError('Decision enabled must be boolean')
            elif isinstance(val, bool) or not isinstance(
                    val, (float, int)) or not 0 <= val <= 100:
                raise ValueError(f'Invalid decision option: {key}')
        for key, val in result[section].items():
            if key.startswith('max_') or key in ('protect_recent_groups',
                                                 'cooldown_tool_rounds',
                                                 'summary_max_chunks'):
                if not isinstance(val, int) or val < 1:
                    raise ValueError(
                        f'Decision option must be a positive integer: {key}')
    context = result['context']
    if not 0 < context['target_ratio'] < context['trigger_ratio'] < 1:
        raise ValueError('Decision context target must be below its trigger')
    if not 0 <= context['keep_probability_max'] <= 0.5:
        raise ValueError('Invalid keep probability threshold')
    if not 0.5 <= result['supervision']['intervention_threshold'] <= 1:
        raise ValueError('Invalid intervention threshold')
    if not (context['enabled'] or result['supervision']['enabled']):
        raise ValueError('Decision mode needs at least one enabled capability')
    return result


class DecisionSettings:

    def __init__(self, directory):
        self.path = Path(directory).expanduser() / 'settings.json'

    def get(self):
        data = read_json(self.path)
        return {
            'default_execution_mode':
            mode(data.get('default_execution_mode', 'standard')),
            'decision':
            deepcopy(data.get('decision') or {})
        }

    def update(self, *, default_execution_mode=None, decision=None):
        with json_transaction(self.path) as data:
            if decision is not None:
                candidate = profile(decision)
                self.snapshot(data=data, value=candidate)
                data['decision'] = candidate
            if default_execution_mode is not None:
                mode(default_execution_mode)
                if default_execution_mode == 'decision':
                    self.snapshot(data=data)
                data['default_execution_mode'] = default_execution_mode
        return self.get()

    def snapshot(self, *, data=None, value=None):
        from ms_agent.config.model_settings import resolve_model_settings
        data = read_json(self.path) if data is None else data
        cfg = profile(
            value if value is not None else data.get('decision') or {})
        if not cfg.get('provider') or not cfg.get('model'):
            raise ValueError('Configure a decision provider and model first')
        resolved = resolve_model_settings(data, cfg['provider'], cfg['model'])
        if not resolved.get('api_key') or not (cfg.get('base_url')
                                               or resolved.get('base_url')):
            raise ValueError(
                'Configure the decision provider endpoint and credentials first'
            )
        cfg['base_url'] = cfg.get('base_url') or resolved['base_url']
        return profile(cfg)

    def client(self, snapshot):
        from ms_agent.config.model_settings import resolve_model_settings
        from ms_agent.decision.client import SystemOneClient
        cfg = profile(snapshot)
        resolved = resolve_model_settings(
            read_json(self.path), cfg['provider'], cfg['model'])
        return SystemOneClient(
            base_url=cfg['base_url'],
            api_key=resolved.get('api_key', ''),
            model=cfg['model'])
