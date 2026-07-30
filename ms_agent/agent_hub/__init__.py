# Copyright (c) ModelScope Contributors. All rights reserved.
"""Agent workspace management for ms-agent (migrated from modelscope-hub).

This package holds the agent-workspace *business logic* (framework specs,
merge/convert, local/remote sync, watch daemon, backups) and the CLI command
implementations. The low-level remote transport lives in modelscope-hub
(:class:`modelscope_hub.agent.AgentApi`), which this package depends on.

Public API
----------
- :class:`AgentApi` -- HTTP client for agent repository operations (re-exported
  from modelscope-hub).
- :class:`WorkspaceSpec` -- Abstract base for framework workspace definitions.
- :data:`FRAMEWORK_REGISTRY` -- Mapping of framework names to WorkspaceSpec classes.
- :func:`register_framework` -- Register a new framework at runtime.
- :func:`get_defaults` -- Load default templates for a framework.

Built-in frameworks (auto-registered on import):
  qoder, qwenpaw, openclaw, hermes, nanobot, openhuman, ms-agent
"""
from modelscope_hub.agent import AgentApi

# Trigger auto-registration of all built-in frameworks.
from . import frameworks as _frameworks  # noqa: F401
from ._commands import (api_error_message, available_frameworks, build_spec,
                        cmd_backups, cmd_convert, cmd_download, cmd_list,
                        cmd_recover, cmd_restore, cmd_status, cmd_stop,
                        cmd_upload, cmd_watch, convert_resources,
                        convert_workspace, repo_name, resolve_local_name,
                        resolve_remote)
from ._defaults import get_defaults
from ._merge import (FullMergeResult, HeartbeatMerger, MergeAction,
                     MergeResult, SectionMerger, merge_resources)
from ._workspace import (ALL_AGENT_NAME, DEFAULT_AGENT_NAME,
                         FRAMEWORK_REGISTRY, GLOBAL_AGENT_NAME, WorkspaceSpec,
                         register_framework)

__all__ = [
    'AgentApi',
    'WorkspaceSpec',
    'FRAMEWORK_REGISTRY',
    'register_framework',
    'get_defaults',
    'DEFAULT_AGENT_NAME',
    'ALL_AGENT_NAME',
    'GLOBAL_AGENT_NAME',
    'FullMergeResult',
    'MergeAction',
    'MergeResult',
    'SectionMerger',
    'HeartbeatMerger',
    'merge_resources',
    'api_error_message',
    'available_frameworks',
    'build_spec',
    'cmd_backups',
    'cmd_convert',
    'cmd_download',
    'cmd_list',
    'cmd_recover',
    'cmd_restore',
    'cmd_status',
    'cmd_stop',
    'cmd_upload',
    'cmd_watch',
    'convert_resources',
    'convert_workspace',
    'repo_name',
    'resolve_local_name',
    'resolve_remote',
]
