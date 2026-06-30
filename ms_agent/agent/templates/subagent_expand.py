# Copyright (c) Alibaba, Inc. and its affiliates.
"""Expand the ``subagents:`` shorthand into ``tools.agent_tools.definitions``.

A template (or any agent config) may declare::

    subagents: [explore, build, research]

which is expanded, at config-load time, into the equivalent ``agent_tools``
definitions, each pointing at the corresponding template via ``template://``::

    tools:
      agent_tools:
        definitions:
          - tool_name: explore
            config_path: template://explore
            description: <registry when_to_use>
            parameters: {request: string}
            output_mode: final_message

Non-destructive and idempotent: an explicit definition with the same
``tool_name`` always wins, so users can hand-tune any entry.
"""
from __future__ import annotations

from omegaconf import DictConfig, OmegaConf

from .registry import get_when_to_use


def _standard_parameters(name: str) -> dict:
    return {
        'type': 'object',
        'properties': {
            'request': {
                'type':
                'string',
                'description':
                (f'A self-contained task description for the {name} sub-agent. '
                 'Include all necessary context; the sub-agent does not see this '
                 'conversation.'),
            },
        },
        'required': ['request'],
        'additionalProperties': False,
    }


def expand_subagents(config: DictConfig) -> DictConfig:
    """Expand ``config.subagents`` into ``config.tools.agent_tools.definitions``.

    Returns ``config`` unchanged when there is no ``subagents`` key.
    """
    subagents = getattr(config, 'subagents', None)
    if not subagents:
        return config
    try:
        names = [
            str(n) for n in OmegaConf.to_container(subagents, resolve=True)
        ]
    except Exception:
        return config
    names = [n for n in names if n]
    if not names:
        return config

    if not hasattr(config, 'tools') or config.tools is None:
        config.tools = DictConfig({})
    tools = config.tools

    # Build the agent_tools block as a plain container, then assign it back in
    # one step. OmegaConf copies on assignment, so mutating a node *after*
    # assigning it would not persist -- build-then-assign-once avoids that.
    existing_at = getattr(tools, 'agent_tools', None)
    if existing_at is None:
        at_dict = {'mcp': False}
    else:
        at_dict = OmegaConf.to_container(existing_at, resolve=True)
        at_dict = at_dict if isinstance(at_dict, dict) else {}
    existing_defs = at_dict.get('definitions') or []

    existing_names = set()
    for d in existing_defs:
        tn = (d.get('tool_name') or d.get('name')) if isinstance(d,
                                                                 dict) else None
        if tn is not None:
            existing_names.add(str(tn))

    generated = []
    for name in names:
        if name in existing_names:
            continue  # explicit definition wins
        generated.append({
            'tool_name': name,
            'description': get_when_to_use(name),
            'config_path': f'template://{name}',
            'parameters': _standard_parameters(name),
            'output_mode': 'final_message',
            'max_output_chars': 200000,
        })

    at_dict['definitions'] = list(existing_defs) + generated
    tools.agent_tools = DictConfig(at_dict)
    return config
