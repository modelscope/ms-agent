"""Wire a project's memory toggle to ``memory.unified_memory``.

Same shape GitLab WebUI ``_apply_webui_memory`` writes so TUI and WebUI share
MEMORY.md under ``<work>/.ms_agent/memory/``. Vector/mem0 stays WebUI-owned:
TUI persists the backend flag but does not silently fall back to file.
"""
from __future__ import annotations

from typing import Any

from omegaconf import OmegaConf, open_dict


def _drop_memory(config) -> None:
    if OmegaConf.select(config, 'memory', default=None) is None:
        return
    with open_dict(config):
        if 'memory' in config:
            del config.memory


def apply_project_memory(config, project: Any) -> str:
    """Enable or strip unified_memory from *config* from *project* flags.

    Returns ``off``, ``file``, or ``vector-unavailable``.
    """
    if not getattr(project, 'memory_enabled', False):
        _drop_memory(config)
        return 'off'

    backend = getattr(project, 'memory_backend', None) or 'file'
    if backend == 'vector':
        # Match WebUI: never write a file MEMORY.md the vector UI would hide.
        _drop_memory(config)
        return 'vector-unavailable'
    if backend not in ('file', None, ''):
        backend = 'file'

    pid = getattr(project, 'id', None) or 'default'
    node = {
        'storage': {'backend': 'file'},
        'namespace': {'user_id': pid},
        'user_id': pid,
        'add_after_step': {'user_id': pid},
    }
    OmegaConf.update(config, 'memory.unified_memory', node, merge=True)
    mem_node = OmegaConf.select(config, 'memory', default=None)
    if mem_node is not None:
        for key in [k for k in mem_node if k != 'unified_memory']:
            del mem_node[key]
    return 'file'
