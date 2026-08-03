# Copyright (c) ModelScope Contributors. All rights reserved.
"""QwenPaw workspace specification (root-per-agent)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ms_agent.utils.logger import get_logger
from .._workspace import (ALL_AGENT_NAME, DEFAULT_AGENT_NAME,
                          GLOBAL_AGENT_NAME, WorkspaceSpec, is_secret_key,
                          register_framework)
from ._bundled_skills import BundledSkillFilterMixin

logger = get_logger()


class QwenpawWorkspace(BundledSkillFilterMixin, WorkspaceSpec):
    """Workspace spec for the QwenPaw (a.k.a. CoPaw) agent framework.

    QwenPaw stores per-agent workspaces under ``~/.qwenpaw/workspaces/{id}`` (legacy ``~/.copaw``);
    the default agent lives in ``workspaces/default``. Unlike other products,
    QwenPaw does *not* discover agents by scanning the workspaces directory:
    the desktop app loads agents from a central registry in
    ``config.json`` (the ``agents.profiles`` map). An agent whose files
    exist on disk but is absent from that registry is invisible in the UI, so
    :meth:`apply` both writes the files *and* registers the agent.

    Portable files:

    * persona markdown (``AGENTS.md``/``SOUL.md``/``PROFILE.md``/... )
    * ``skills/`` (recursively) plus the workspace ``skill.json`` manifest
    * ``agent.json`` -- the agent configuration. It is collected as-is but
      sanitized on :meth:`apply` (machine-specific ``workspace_dir``/``id`` are
      rewritten and per-channel secrets/tokens are stripped).

    In ``all`` mode, ``workspace_root`` lifts to ``<config>/workspaces/`` and
    patterns are prefixed with ``*/`` so that each agent directory becomes a
    path prefix in the collected resource dict.
    """

    # CoPaw/QwenPaw share a data root. The desktop app installs to
    # ``~/.copaw`` (config.json + workspaces registry), so it takes top
    # priority; ``~/.qwenpaw`` is only a fallback. Probe both, preferring
    # ``.copaw``; default to it when neither exists yet (fresh install).
    _CONFIG_DIRNAMES = ('.copaw', '.qwenpaw')

    # Channel keys that are machine-local but whose name has no secret suffix
    # :func:`is_secret_key` would catch: a local sqlite path. Blanked in
    # addition to the shared secret-suffix rule.
    _CHANNEL_LOCAL_KEYS = frozenset(['db_path'])

    @property
    def product_name(self) -> str:
        return 'qwenpaw'

    @property
    def default_root(self) -> Path:
        # Prefer an existing data root; ``.copaw`` (the desktop app home)
        # wins over ``.qwenpaw`` when both are present. Default to ``.copaw``
        # when neither exists yet.
        home = Path.home()
        for name in self._CONFIG_DIRNAMES:
            candidate = home / name
            if candidate.is_dir():
                return candidate
        return home / self._CONFIG_DIRNAMES[0]

    @property
    def workspace_root(self) -> Path:
        # root-per-agent: derive the per-agent workspace from the data root.
        base = self.root / 'workspaces'
        if self._is_all():
            return base
        return base / self.agent_name

    @property
    def patterns(self) -> list[str]:
        return [
            'AGENTS.md',
            'SOUL.md',
            'PROFILE.md',
            'BOOTSTRAP.md',
            'MEMORY.md',
            'HEARTBEAT.md',
            'memory/*.md',
            'agent.json',
            'skill.json',
            # fnmatch ``*`` spans ``/`` so ``skills/*`` recurses the
            # whole skill tree (SKILL.md + references/assets/scripts).
            'skills/*',
        ]

    def _effective_patterns(self) -> list[str]:
        if self._is_all():
            return [f'*/{p}' for p in self.patterns]
        return self.patterns

    @property
    def is_root_per_agent(self) -> bool:
        return True

    def split_all_path(self, rel_path: str) -> tuple[str | None, str]:
        # agent directory name IS the agent name: ``<agent>/<bare>``.
        if '/' in rel_path:
            head, rest = rel_path.split('/', 1)
            return (head, rest)
        return (None, rel_path)

    def join_all_path(self, agent_name: str, bare_path: str) -> str:
        return f'{agent_name}/{bare_path}'

    def list_agents(self) -> list[str]:
        base = self.root / 'workspaces'
        if not base.is_dir():
            return [DEFAULT_AGENT_NAME]
        agents = [d.name for d in sorted(base.iterdir()) if d.is_dir()]
        return agents or [DEFAULT_AGENT_NAME]

    # ------------------------------------------------------------------
    # agent.json sanitization + config.json registration on apply
    # ------------------------------------------------------------------

    def _strip_agent_json_secrets(self, data: dict) -> None:
        """Blank every secret in an ``agent.json`` dict in place.

        Shared by the inbound (download) and outbound (upload) sanitizers so a
        key never lands on disk from a remote agent, and a local key is never
        pushed to the remote repo / its git history.

        The whole JSON tree is walked recursively and any key matching
        :func:`is_secret_key` is blanked wherever it lives (top-level
        ``model.api_key``, ``channels.*.client_secret``, future additions...).
        Two structural rules are applied on top of the vocabulary:

        * channel configs additionally blank ``_CHANNEL_LOCAL_KEYS``
          (machine-local paths such as ``db_path``);
        * every ``env`` mapping is cleared wholesale WHEREVER it lives -- env
          var names are arbitrary, so values there are treated as secrets
          even when the name does not match the vocabulary.  Anchoring on the
          ``env`` key (not on a parent block name) keeps every MCP schema
          spelling covered (``mcp.clients`` / ``mcp_clients`` /
          ``mcpClients``), mirroring :func:`scrub_json_secrets`.
        """

        def scrub(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    # Secret-named key: wipe the WHOLE value (even a nested
                    # mapping) -- credentials blobs must not survive because
                    # their inner field names happen to look harmless.
                    if is_secret_key(key):
                        node[key] = ''
                    elif key == 'env' and isinstance(value, dict):
                        node[key] = {k: '' for k in value}
                    elif isinstance(value, (dict, list)):
                        scrub(value)
            elif isinstance(node, list):
                for item in node:
                    scrub(item)

        scrub(data)
        # Channel configs: also blank machine-local (non-secret-named) keys.
        channels = data.get('channels')
        if isinstance(channels, dict):
            for ch in channels.values():
                if not isinstance(ch, dict):
                    continue
                for key in list(ch.keys()):
                    if key in self._CHANNEL_LOCAL_KEYS:
                        ch[key] = ''

    def _sanitize_agent_json(self, agent_name: str, content: str) -> str:
        """Rewrite machine-specific fields and strip per-channel secrets.

        Returns the sanitized JSON text. On parse failure the original text is
        returned unchanged (best-effort; a malformed file should not abort the
        whole download).
        """
        try:
            data: Any = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            logger.warning('agent.json is not valid JSON; writing as-is')
            return content
        if not isinstance(data, dict):
            return content
        # Rebind identity/location to the local target agent.
        data['id'] = agent_name
        data['workspace_dir'] = str(self.root / 'workspaces' / agent_name)
        self._strip_agent_json_secrets(data)
        return json.dumps(data, ensure_ascii=False, indent=2)

    def _strip_outbound_agent_json(self, content: str) -> str:
        """Strip secrets from an ``agent.json`` for upload (no identity rebind).

        Only the secret-bearing fields are blanked; ``id`` / ``workspace_dir``
        keep their local values (they are rebound on the next download).

        Sanitizing is a security boundary and the UPLOAD direction must fail
        closed: a file we cannot parse cannot be verified secret-free, so a
        malformed ``agent.json`` raises instead of being pushed verbatim
        (which would put the user's plaintext keys into the remote repo's
        git history forever).  The inbound (download) path keeps its
        best-effort pass-through -- a malformed remote file adds no new
        exposure when written to disk.
        """
        try:
            data: Any = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            raise ValueError(
                'agent.json is not valid JSON; cannot verify it is free of '
                'secrets -- refusing to upload it. Fix the file and retry.')
        if not isinstance(data, dict):
            return content
        self._strip_agent_json_secrets(data)
        return json.dumps(data, ensure_ascii=False, indent=2)

    def _register_agent(self, agent_name: str) -> None:
        """Add *agent_name* to the data root's ``config.json`` ``agents`` registry.

        Best-effort and idempotent: an existing profile is updated in place and
        the agent is appended to ``agent_order`` only if absent. When the config
        file is missing or unparsable the registration is skipped.
        """
        if agent_name in (ALL_AGENT_NAME, GLOBAL_AGENT_NAME):
            return
        config_path = self.root / 'config.json'
        if not config_path.is_file():
            logger.warning(
                'QwenPaw config.json not found at %s; agent %r written but not '
                'registered (it will be invisible in the UI until QwenPaw '
                'rescans).',
                config_path,
                agent_name,
            )
            return
        try:
            cfg = json.loads(config_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning(
                'Cannot read QwenPaw config.json (%s); skip register', e)
            return
        if not isinstance(cfg, dict):
            return
        agents = cfg.get('agents')
        if not isinstance(agents, dict):
            agents = {}
            cfg['agents'] = agents
        profiles = agents.get('profiles')
        if not isinstance(profiles, dict):
            profiles = {}
            agents['profiles'] = profiles
        workspace_dir = str(self.root / 'workspaces' / agent_name)
        existing = profiles.get(agent_name)
        profile = existing if isinstance(existing, dict) else {}
        profile.update({
            'id': agent_name,
            'workspace_dir': workspace_dir,
            'enabled': True,
        })
        profiles[agent_name] = profile
        order = agents.get('agent_order')
        if not isinstance(order, list):
            order = list(profiles.keys())
            agents['agent_order'] = order
        if agent_name not in order:
            order.append(agent_name)
        try:
            config_path.write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2),
                encoding='utf-8')
        except OSError as e:
            logger.warning(
                'Cannot write QwenPaw config.json (%s); skip register', e)

    def sanitize_inbound_file(self, rel_path: str, content: bytes) -> bytes:
        """Sanitize inbound ``agent.json`` (strip secrets, rebind identity).

        Applied uniformly on every inbound write path (full ``apply`` and
        incremental ``pull_incremental``), so a remote ``agent.json`` never
        lands on disk with secrets regardless of sync mode.
        """
        if self._is_all():
            agent, bare = self.split_all_path(rel_path)
            if not (agent and bare == 'agent.json'):
                return content
            target_agent = agent
        else:
            if rel_path != 'agent.json':
                return content
            target_agent = self.agent_name or DEFAULT_AGENT_NAME
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            return content
        return self._sanitize_agent_json(target_agent, text).encode('utf-8')

    def sanitize_outbound_file(self, rel_path: str, content: bytes) -> bytes:
        """Strip secrets from outbound ``agent.json`` before it is pushed.

        Mirrors the file-selection logic of :meth:`sanitize_inbound_file` but
        only blanks secrets -- identity is NOT rebound on upload (the local
        file already carries the correct identity), so a user's channel / MCP
        keys never reach the remote repo or its git history.
        """
        if self._is_all():
            agent, bare = self.split_all_path(rel_path)
            if not (agent and bare == 'agent.json'):
                return content
        else:
            if rel_path != 'agent.json':
                return content
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            raise ValueError(
                f'{rel_path} is not valid UTF-8; cannot verify it is free of '
                f'secrets -- refusing to upload it. Fix the file and retry.')
        return self._strip_outbound_agent_json(text).encode('utf-8')

    def apply(self, resources: dict[str, str]) -> list[str]:
        """Write files (``agent.json`` sanitized via the inbound hook) then
        register the agent(s) according to scope.

        Registration policy differs by scope:

        * ``-n all`` (whole-repo batch sync) writes files **without touching**
          the ``config.json`` registry. Batch sync only mirrors file content;
          which agents are visible in the UI is owned by the user (via the
          QwenPaw UI). Registering here would resurrect agents the user has
          deleted in the UI (their ``agent.json`` may still linger on disk,
          get re-uploaded, then pulled back), so ``all`` never registers.
        * ``-n <agent>`` (explicit single agent) registers that agent, so a
          freshly downloaded agent becomes visible in the UI as intended.
        """
        # ``super().apply`` runs ``sanitize_inbound_file`` per file, so
        # ``agent.json`` sanitization happens there -- do not re-sanitize here.
        written = super().apply(resources)
        if self._is_all():
            logger.info(
                'Applied %d file(s) in all-mode; registry left unchanged '
                '(agent visibility is owned by the QwenPaw UI).', len(written))
            return written
        agent_name = self.agent_name or DEFAULT_AGENT_NAME
        self._register_agent(agent_name)
        return written


register_framework('qwenpaw', QwenpawWorkspace)
