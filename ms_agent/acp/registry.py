import os
import sys
from typing import Any, Dict

import json
from ms_agent.utils.logger import get_logger

logger = get_logger()

_DEFAULT_VERSION = '0.1.0'


def generate_agent_manifest(
    config_path: str | None = None,
    output_path: str = 'agent.json',
    version: str = _DEFAULT_VERSION,
    title: str = 'MS-Agent',
    description:
    str = 'Lightweight framework for empowering agents with autonomous exploration',
) -> Dict[str, Any]:
    """Build and optionally write an ``agent.json`` manifest.

    The manifest follows the ACP Agent Registry specification so that
    tools like Zed's agent picker can auto-discover ms-agent.
    """
    exe = 'ms-agent'
    args = ['acp']
    if config_path:
        args.extend(['--config', config_path])

    manifest: Dict[str, Any] = {
        'name': 'ms-agent',
        'title': title,
        'version': version,
        'description': description,
        'protocol': 'acp',
        'protocolVersion': 1,
        'transport': {
            'type': 'stdio',
            'command': exe,
            'args': args,
        },
        'capabilities': {
            'loadSession': False,
            'promptCapabilities': {
                'image': False,
                'audio': False,
                'embeddedContext': True,
            },
            'sessionCapabilities': {
                'list': {},
            },
        },
    }

    if output_path:
        abs_path = os.path.abspath(output_path)
        with open(abs_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        logger.info('Agent manifest written to %s', abs_path)

    return manifest
