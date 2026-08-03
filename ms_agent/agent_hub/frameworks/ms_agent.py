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

    def sanitize_outbound_file(self, rel_path: str, content: bytes) -> bytes:
        """Fail-closed upload sanitize for the secret-bearing config files.

        The inbound hook passes malformed content through verbatim (a broken
        remote file adds no new exposure when written to disk), but on UPLOAD
        that same pass-through would push the user's plaintext keys into the
        remote repo's git history. So a config file we cannot parse -- and
        therefore cannot verify as secret-free -- is refused here instead.
        """
        if rel_path == 'settings.json':
            try:
                json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                raise ValueError(
                    f'{rel_path} is not valid JSON; cannot verify it is free '
                    f'of secrets -- refusing to upload it. Fix the file and '
                    f'retry.')
        elif rel_path in ('config.yaml', 'agent.yaml'):
            try:
                content.decode('utf-8')
            except UnicodeDecodeError:
                raise ValueError(
                    f'{rel_path} is not valid UTF-8; cannot verify it is '
                    f'free of secrets -- refusing to upload it. Fix the file '
                    f'and retry.')
        return self.sanitize_inbound_file(rel_path, content)


register_framework('ms-agent', MsAgentWorkspace)
