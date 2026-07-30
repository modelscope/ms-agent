# Copyright (c) ModelScope Contributors. All rights reserved.
"""ms-agent workspace specification (single-agent install)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .._workspace import (WorkspaceSpec, register_framework,
                          scrub_json_secrets, scrub_yaml_secrets)


class MsAgentWorkspace(WorkspaceSpec):
    """Workspace spec for the ms-agent framework (single-agent install).

    ms-agent keeps its persona, memory and skills under ``~/.ms_agent``:

    * **persona** -- a single ``profile.md`` augmented by injected
      configuration (project-level ``config.yaml``, global ``settings.json``
      and a user-specified ``agent.yaml``).
    * **memory** -- ``MEMORY.md`` plus a structured ``facts.json``.
    * **skills** -- ``skills/<name>/SKILL.md`` with a workspace-level
      ``skill.json`` metadata index.

    Only ``profile.md`` (persona) and ``MEMORY.md`` (memory) carry
    cross-framework semantics; the YAML/JSON config and metadata files are
    ms-agent specific and are preserved on same-framework sync only.
    """

    @property
    def product_name(self) -> str:
        return 'ms-agent'

    @property
    def default_root(self) -> Path:
        return Path.home() / '.ms_agent'

    @property
    def patterns(self) -> list[str]:
        return [
            # Persona + injected configuration
            'profile.md',
            'config.yaml',
            'settings.json',
            'agent.yaml',
            # Memory
            'MEMORY.md',
            'facts.json',
            # Skills
            'skill.json',
            'skills/*/SKILL.md',
        ]

    # ------------------------------------------------------------------
    # config secret sanitization (inbound + outbound)
    # ------------------------------------------------------------------
    #
    # ms-agent injects model / provider credentials into its config files:
    # ``agent.yaml`` and ``config.yaml`` carry ``llm.*_api_key`` (and may hold
    # an ``mcpServers.*.env`` secret bag), while ``settings.json`` is the JSON
    # MCP-server file whose ``env`` blocks hold arbitrary API keys. All three
    # are collected by ``patterns`` above, so they are stripped of secrets on
    # both the inbound and outbound path -- a user's keys never reach the
    # remote repo / its git history, and a remote key never lands on disk.
    #
    # ms-agent does no machine-local identity rebinding, so the base-class
    # outbound hook (which delegates to this inbound hook) reuses the same
    # cleaning on the upload path -- no separate outbound override is needed.

    def sanitize_inbound_file(self, rel_path: str, content: bytes) -> bytes:
        """Blank machine-local secrets in ms-agent config files.

        ``config.yaml`` / ``agent.yaml`` are scrubbed line-by-line (shared YAML
        scrubber, ``mcpServers`` env aware); ``settings.json`` is parsed and
        scrubbed structurally. Every other file (and undecodable / malformed
        content) passes through verbatim.
        """
        if rel_path in ('config.yaml', 'agent.yaml'):
            try:
                text = content.decode('utf-8')
            except UnicodeDecodeError:
                return content
            return scrub_yaml_secrets(text).encode('utf-8')
        if rel_path == 'settings.json':
            try:
                data: Any = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return content
            scrub_json_secrets(data)
            return json.dumps(
                data, ensure_ascii=False, indent=2).encode('utf-8')
        return content


register_framework('ms-agent', MsAgentWorkspace)
