# Copyright (c) ModelScope Contributors. All rights reserved.
"""ms-agent Capability Gateway.

Provides a unified abstraction layer that packages ms-agent's internal
capabilities (projects, components, and atomic tools) into a registry
accessible via Python API, MCP Server, or Skill-based discovery.

Quick start::

    from ms_agent.capabilities import create_registry

    registry = create_registry()

    # Discover capabilities
    caps = registry.discover(tags=["research"])

    # Invoke a capability
    result = await registry.invoke("replace_file_contents", {
        "path": "main.py",
        "source": "old_text",
        "target": "new_text",
    })
"""

from __future__ import annotations

from typing import Any

from ms_agent.capabilities.descriptor import CapabilityDescriptor
from ms_agent.capabilities.registry import CapabilityRegistry


def create_registry(config: Any = None) -> CapabilityRegistry:
    """Create a :class:`CapabilityRegistry` with all built-in capabilities.

    Each wrapper module under ``ms_agent.capabilities.wrappers`` registers
    its capabilities into the shared registry.  Wrapper imports are deferred
    so that heavyweight dependencies (e.g. LSP servers) are only loaded when
    their capabilities are actually invoked.
    """
    registry = CapabilityRegistry()

    from ms_agent.capabilities.wrappers import agent_delegate, deep_research, filesystem, lsp_code_server, web_search

    filesystem.register_all(registry, config)
    lsp_code_server.register_all(registry, config)
    deep_research.register_all(registry, config)
    web_search.register_all(registry, config)
    agent_delegate.register_all(registry, config)

    return registry


__all__ = [
    'CapabilityDescriptor',
    'CapabilityRegistry',
    'create_registry',
]
