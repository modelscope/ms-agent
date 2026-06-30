import os
from typing import Any, Dict, List

import json
from ms_agent.utils.logger import get_logger

logger = get_logger()

_DEFAULT_VERSION = '0.1.0'


def build_agent_card(
    config_path: str | None = None,
    host: str = '0.0.0.0',
    port: int = 5000,
    version: str = _DEFAULT_VERSION,
    title: str = 'MS-Agent',
    description: str = ('Lightweight framework for empowering agents '
                        'with autonomous exploration'),
    skills: list[dict] | None = None,
) -> dict:
    """Build an A2A ``AgentCard`` dict from ms-agent config.

    The returned dict matches the A2A AgentCard schema and can be passed
    directly to ``a2a.types.AgentCard(**card_dict)`` or serialised to JSON.
    """
    from a2a.types import (
        AgentCard,
        AgentCapabilities,
        AgentSkill,
    )

    resolved_host = host if host != '0.0.0.0' else 'localhost'
    url = f'http://{resolved_host}:{port}/'

    if config_path and os.path.exists(config_path):
        try:
            from ms_agent.config.config import Config
            config = Config.from_task(config_path)
            cfg_desc = getattr(config, 'description', None)
            if cfg_desc:
                description = str(cfg_desc)
            cfg_name = getattr(config, 'name', None)
            if cfg_name:
                title = str(cfg_name)
        except Exception:
            logger.debug(
                'Could not load config for agent card metadata', exc_info=True)

    skill_list: list[AgentSkill] = []
    if skills:
        for s in skills:
            skill_list.append(
                AgentSkill(
                    id=s.get('id', 'general'),
                    name=s.get('name', title),
                    description=s.get('description', description),
                    tags=s.get('tags', []),
                    examples=s.get('examples', []),
                ))
    else:
        skill_list.append(
            AgentSkill(
                id='general',
                name=title,
                description=description,
                tags=['general', 'agent'],
                examples=['Help me research a topic'],
            ))

    card = AgentCard(
        name=title.lower().replace(' ', '-'),
        description=description,
        url=url,
        version=version,
        capabilities=AgentCapabilities(streaming=True),
        skills=skill_list,
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
    )
    return card


def generate_agent_card_json(
    config_path: str | None = None,
    output_path: str = 'agent-card.json',
    host: str = '0.0.0.0',
    port: int = 5000,
    version: str = _DEFAULT_VERSION,
    title: str = 'MS-Agent',
    description: str = ('Lightweight framework for empowering agents '
                        'with autonomous exploration'),
    skills: list[dict] | None = None,
) -> dict:
    """Build an agent card and optionally write it to disk as JSON."""
    card = build_agent_card(
        config_path=config_path,
        host=host,
        port=port,
        version=version,
        title=title,
        description=description,
        skills=skills,
    )

    card_dict = card.model_dump(by_alias=True, exclude_none=True)

    if output_path:
        abs_path = os.path.abspath(output_path)
        with open(abs_path, 'w') as f:
            json.dump(card_dict, f, indent=2)
        logger.info('A2A Agent Card written to %s', abs_path)

    return card_dict
