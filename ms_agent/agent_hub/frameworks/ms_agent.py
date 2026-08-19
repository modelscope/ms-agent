# Copyright (c) ModelScope Contributors. All rights reserved.
"""ms-agent workspace specification (single-agent install)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ms_agent.project.paths import global_home

from .._workspace import (WorkspaceSpec, register_framework,
                          scrub_json_secrets)


class MsAgentWorkspace(WorkspaceSpec):
    """Workspace spec for the ms-agent framework (single-agent install).

    ms-agent keeps its editable prompt files, config and skills under the
    global home (``$MS_AGENT_HOME`` or ``~/.ms_agent``). The user-configurable
    prompt content is now real on-disk Markdown, not config fields:

    * **persona** -- ``SOUL.md`` (real default persona, injected as-is).
    * **standing instructions** -- ``AGENTS.md`` (global; project-level
      ``<work_dir>/AGENTS.md`` layers on top and is out of this home).
    * **user profile** -- ``PROFILE.md`` (supersedes the old lowercase
      ``profile.md``, which the runtime rebuilds into this on first read).
    * **config** -- ``settings.json`` (switches / model / credentials) and
      ``mcp.json`` (MCP server definitions whose ``env`` blocks carry API
      keys); both are secret-scrubbed. Legacy ``config.yaml`` / ``agent.yaml``
      are project-level and package-internal respectively -- they do NOT live
      under the global home and are not collected.
    * **skills** -- ``skills/<name>/SKILL.md`` with a workspace-level
      ``skills.json`` inventory (runtime name; the old ``skill.json`` never
      existed on disk).

    Only the three Markdown files (SOUL/AGENTS/PROFILE) carry cross-framework
    semantics; the JSON/YAML config is ms-agent private and preserved on
    same-framework sync only. Memory is NOT here: the runtime keeps it
    project-level under ``<work_dir>/.ms_agent/memory/`` (no global memory by
    design), so the global-home workspace this spec models carries none.

    Machine bookkeeping never travels: the ``.soul.builtin`` /
    ``.agents.builtin`` / ``.profile.builtin`` sidecars are dotfiles (skipped
    by the collector), and ``*.bak`` rollups cannot match the exact-name
    patterns below.
    """

    @property
    def product_name(self) -> str:
        return 'ms-agent'

    @property
    def default_root(self) -> Path:
        # Honor MS_AGENT_HOME (read dynamically) rather than hard-coding
        # ~/.ms_agent, so a redirected home is collected/applied correctly.
        return global_home()

    @property
    def patterns(self) -> list[str]:
        return [
            # Editable prompt files (persona / instructions / profile)
            'SOUL.md',
            'AGENTS.md',
            'PROFILE.md',
            # Config (switches / model / credentials) -- secret-scrubbed.
            # Only settings.json and mcp.json live under the global home;
            # config.yaml is project-level (<work_dir>/.ms_agent/config.yaml)
            # and agent.yaml is the package-internal framework default -- neither
            # exists at the global root, so they are NOT collected here.
            'settings.json',
            'mcp.json',
            # Skills. fnmatch ``*`` spans ``/`` so ``skills/*`` recurses the
            # whole skill tree -- SKILL.md plus its auxiliary files
            # (references/, scripts/, assets/, ...), matching every other
            # framework's skill pattern. A narrower ``skills/*/SKILL.md`` would
            # drop those runtime dependencies both on collect and when this
            # spec is the allowlist for an inbound convert.
            'skills.json',
            'skills/*',
        ]

    # ------------------------------------------------------------------
    # config secret sanitization (inbound + outbound)
    # ------------------------------------------------------------------
    #
    # ms-agent injects model / provider credentials into its config files:
    # ``settings.json`` holds provider switches / keys (and may carry an
    # ``mcpServers.*.env`` secret bag), and ``mcp.json`` is the primary
    # MCP-server file whose ``env`` blocks hold arbitrary API keys. Both are
    # collected by ``patterns`` above, so they are stripped of secrets on
    # both the inbound and outbound path -- a user's keys never reach the
    # remote repo / its git history, and a remote key never lands on disk.
    #
    # ms-agent does no machine-local identity rebinding, so the base-class
    # outbound hook (which delegates to this inbound hook) reuses the same
    # cleaning on the upload path -- no separate outbound override is needed.

    def sanitize_inbound_file(self, rel_path: str, content: bytes) -> bytes:
        """Blank machine-local secrets, and keep sync from flipping skill switches.

        ``settings.json`` and ``mcp.json`` are parsed and scrubbed structurally
        (``env`` blocks blanked, secret-suffix keys blanked).
        ``skills.json`` keeps the *inventory* (``sources``)
        but its ``disabled`` list is a machine-local safety switch, so an inbound
        write must NOT overwrite the local one -- otherwise a download/restore
        would silently re-enable skills the user turned off. Every other file
        (and undecodable / malformed content) passes through verbatim.
        """
        if rel_path in ('settings.json', 'mcp.json'):
            try:
                data: Any = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return content
            scrub_json_secrets(data)
            return json.dumps(
                data, ensure_ascii=False, indent=2).encode('utf-8')
        if rel_path == 'skills.json':
            return self._preserve_local_skill_switches(content)
        return content

    def _preserve_local_skill_switches(self, content: bytes) -> bytes:
        """Carry the local ``disabled`` list into an inbound ``skills.json``.

        The enable/disable state (``disabled``) is a per-machine safety switch
        that must not travel; only the ``sources`` inventory syncs. If the
        incoming JSON is malformed it passes through untouched (a broken file on
        disk adds no exposure). A missing local file simply means no local
        switches to preserve.
        """
        try:
            incoming = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return content
        if not isinstance(incoming, dict):
            return content
        local_path = self.workspace_root / 'skills.json'
        local_disabled = None
        try:
            local = json.loads(local_path.read_text(encoding='utf-8'))
            if isinstance(local, dict) and 'disabled' in local:
                local_disabled = local['disabled']
        except (OSError, json.JSONDecodeError, ValueError):
            local_disabled = None
        if local_disabled is not None:
            incoming['disabled'] = local_disabled
        else:
            incoming.pop('disabled', None)
        return json.dumps(
            incoming, ensure_ascii=False, indent=2).encode('utf-8')

    def sanitize_outbound_file(self, rel_path: str, content: bytes) -> bytes:
        """Fail-closed upload sanitize for the secret-bearing config files.

        The inbound hook passes malformed content through verbatim (a broken
        remote file adds no new exposure when written to disk), but on UPLOAD
        that same pass-through would push the user's plaintext keys into the
        remote repo's git history. So a config file we cannot parse -- and
        therefore cannot verify as secret-free -- is refused here instead.

        ``skills.json`` carries no secrets, but its ``disabled`` list is a
        machine-local safety switch that must not be published; it is stripped
        so only the ``sources`` inventory leaves the machine.
        """
        if rel_path == 'skills.json':
            try:
                data = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return content
            if isinstance(data, dict):
                data.pop('disabled', None)
                return json.dumps(
                    data, ensure_ascii=False, indent=2).encode('utf-8')
            return content
        if rel_path in ('settings.json', 'mcp.json'):
            try:
                json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                raise ValueError(
                    f'{rel_path} is not valid JSON; cannot verify it is free '
                    f'of secrets -- refusing to upload it. Fix the file and '
                    f'retry.')
        return self.sanitize_inbound_file(rel_path, content)


register_framework('ms-agent', MsAgentWorkspace)
