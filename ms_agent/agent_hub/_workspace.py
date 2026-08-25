# Copyright (c) ModelScope Contributors. All rights reserved.
"""Agent workspace file specification and framework registry.

Each agent framework stores its files in a known on-disk layout.  A subclass of
:class:`WorkspaceSpec` declares, for one framework, *where* the files live
(``workspace_root``) and *which* of them are portable (``patterns``).
``collect()`` walks the workspace and returns
``{workspace_relative_path: text_content}``.

Sub-agents
----------
A single installation can host several sub-agents.  There are three layouts:

* **root-per-agent** -- the sub-agent *is* a directory; selecting it changes
  ``workspace_root`` (e.g. qwenpaw ``workspaces/<name>``).
* **file-per-agent + shared** -- the sub-agent is one file inside a shared root,
  collected alongside the shared resources; a ``{name}`` placeholder in
  ``patterns`` is formatted with the sub-agent name (e.g. qoder ``agents/<name>.md``).
* **single-agent** -- one persona per install; the sub-agent name is only the
  repository identity and does not affect file selection.

Framework Registration
----------------------
Use :func:`register_framework` to add a new framework at runtime::

    from ms_agent.agent_hub import WorkspaceSpec, register_framework

    class MyFramework(WorkspaceSpec):
        ...

    register_framework("my-framework", MyFramework)
"""
from __future__ import annotations

import fnmatch
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Type

from ms_agent.utils.logger import get_logger

logger = get_logger()

MAX_FILE_SIZE = 1 * 1024 * 1024  # 1 MB

DEFAULT_AGENT_NAME = 'default'
ALL_AGENT_NAME = 'all'
GLOBAL_AGENT_NAME = '__global__'

_SECRET_KEY_RE = re.compile(
    r'(?:^|[_-])'
    r'(?:api[_-]?keys?|apikeys?|access[_-]?keys?|secret[_-]?keys?|'
    r'client[_-]?secrets?|access[_-]?tokens?|auth[_-]?tokens?|token[_-]?file|'
    r'authorization|bearer|cookies?|session[_-]?ids?|sessionids?|'
    r'keys?|tokens?|secrets?|passwords?|passwd|credentials?|sk)$',
    re.IGNORECASE,
)


def is_secret_key(name: str) -> bool:
    """Whether a config key name denotes a machine-local secret to blank.

    Shared by every framework's config sanitizer so the inbound and outbound
    paths use one secret vocabulary. See :data:`_SECRET_KEY_RE` for the exact
    (secret-suffix) matching policy.
    """
    return bool(_SECRET_KEY_RE.search(name.strip()))


def scrub_yaml_secrets(
    text: str, mcp_block_keys: tuple[str, ...] = ('mcp_servers', 'mcpServers')
) -> str:
    """Blank secret values in a YAML config *text*, line-by-line.

    Regex/line based (not a YAML round-trip) so user comments, key order and
    formatting are preserved -- only the secret *values* are cleared. Two rules
    are applied per ``key: value`` line:

    * a key whose name matches :func:`is_secret_key` -> value cleared, anywhere
      in the tree (e.g. top-level ``model.api_key`` or ``llm.modelscope_api_key``);
    * every scalar nested inside an MCP-server ``env`` mapping (a block opened
      by any key in *mcp_block_keys*, then a nested ``env:``) -> value cleared
      regardless of key name (that block is a free-form secret bag where API
      keys live under arbitrary names).

    Beyond simple ``key: <scalar>`` lines the scrubber also covers the other
    legal spellings a secret can hide in:

    * flow mappings (``llm: {api_key: X, model: y}``) -- secret pairs inside
      the braces are cleared in place; an ``env: {...}`` flow mapping is
      cleared wholesale;
    * block/folded scalars (``api_key: |`` / ``>`` and their chomping
      variants) -- the opener is blanked and the indented content lines that
      carry the secret are dropped.

    Comments, blank lines and non-secret lines are emitted verbatim.

    Shared by every framework whose config is YAML (hermes ``config.yaml``,
    ms-agent ``config.yaml`` / ``agent.yaml``) so they use one secret vocabulary.
    """
    kv = re.compile(
        r'^(?P<indent>[ \t]*)(?P<key>[^\s:#][^:]*?)(?P<sep>[ \t]*:[ \t]*)'
        r'(?P<val>\S.*)?$')
    flow_pair = re.compile(r'(?P<key>["\']?[\w.\-]+["\']?)(?P<sep>\s*:\s*)'
                           r'(?P<val>[^,{}\[\]]+)')
    block_opener = re.compile(r'^[|>][+-]?\d*$')
    # Indent of the active mcp-servers / nested ``env:`` block openers;
    # ``None`` means we are not currently inside that block.
    mcp_indent: int | None = None
    env_indent: int | None = None
    # Inside a secret block scalar: drop lines indented deeper than this.
    skip_indent: int | None = None
    out: list[str] = []
    for line in text.split('\n'):
        stripped = line.strip()
        if skip_indent is not None:
            if not stripped:
                continue  # blank line inside the dropped block scalar
            cur = len(line) - len(line.lstrip(' \t'))
            if cur > skip_indent:
                continue  # secret block-scalar content line: drop
            skip_indent = None
        # Comments / blank lines never carry secrets nor change block scope.
        if not stripped or stripped.startswith('#'):
            out.append(line)
            continue
        m = kv.match(line)
        if not m:
            out.append(line)
            continue
        indent = len(m.group('indent'))
        # Dedenting to <= a block opener's indent leaves that block.
        if env_indent is not None and indent <= env_indent:
            env_indent = None
        if mcp_indent is not None and indent <= mcp_indent:
            mcp_indent = None
        key = m.group('key').strip()
        val = m.group('val')
        in_env = env_indent is not None and indent > env_indent
        secret_key = is_secret_key(key)
        # Block/folded scalar opener (| / > + chomping variants): the secret
        # lives on the FOLLOWING deeper-indented lines -- blank the key and
        # drop that content.
        if val is not None and block_opener.match(val.strip()):
            if secret_key or in_env:
                out.append(
                    f"{m.group('indent')}{m.group('key')}{m.group('sep')}''")
                skip_indent = indent
            else:
                out.append(line)
            continue
        # Flow mapping value: scrub secret pairs inside the braces. An
        # ``env`` (or secret-named) flow mapping is a free-form secret bag ->
        # clear every value in it.
        if val is not None and val.lstrip().startswith(
                '{') and val.strip() != '{}':
            clear_all = secret_key or in_env or key == 'env'

            def _repl(pm, _all=clear_all):
                if _all or is_secret_key(pm.group('key').strip('"\'')):
                    return f"{pm.group('key')}{pm.group('sep')}''"
                return pm.group(0)

            out.append(f"{m.group('indent')}{m.group('key')}{m.group('sep')}"
                       f'{flow_pair.sub(_repl, val)}')
            continue
        has_scalar = val is not None and val.strip() not in ('{}', '[]')
        # A key with no scalar value opens a mapping/list block: track the
        # mcp-servers and nested ``env`` openers so their descendants can be
        # scoped, then emit the opener line unchanged.
        if not has_scalar:
            if key in mcp_block_keys:
                mcp_indent = indent
            elif key == 'env' and mcp_indent is not None:
                env_indent = indent
            out.append(line)
            continue
        if secret_key or in_env:
            out.append(
                f"{m.group('indent')}{m.group('key')}{m.group('sep')}''")
        else:
            out.append(line)
    return '\n'.join(out)


def scrub_json_secrets(obj) -> None:
    """Recursively blank secret values in a parsed JSON structure, in place.

    Mirrors the YAML/TOML scrubbers' vocabulary so JSON config files (ms-agent
    ``settings.json``) use one secret policy:

    * a key matching :func:`is_secret_key` -> value blanked to ``''`` whatever
      its type (a nested mapping under e.g. ``credentials`` is wiped wholesale
      -- its inner field names may look harmless);
    * every value inside an ``env`` mapping -> blanked regardless of key name
      (an ``env`` block, e.g. under an MCP server, is a free-form secret bag).

    Non-secret structure and values are preserved; nested dicts / lists are
    walked recursively.
    """
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == 'env' and isinstance(val, dict):
                obj[key] = {k: '' for k in val}
            elif is_secret_key(key):
                obj[key] = ''
            else:
                scrub_json_secrets(val)
    elif isinstance(obj, list):
        for item in obj:
            scrub_json_secrets(item)


class WorkspaceSpec(ABC):
    """Abstract base for agent framework workspace file specifications.

    :param agent_name: the sub-agent to operate on.  Used to resolve
        ``workspace_root`` (root-per-agent) and/or to format ``{name}``
        placeholders in ``patterns`` (file-per-agent).

        The special value ``"all"`` selects *every* sub-agent at once.

    :param local_dir: explicit framework data-root override; when given, it
        replaces the framework's default root. Its meaning is uniform across all
        frameworks (always the data root); per-agent subdirectories are derived
        from it (e.g. qwenpaw ``workspaces/<name>``).
    """

    def __init__(self,
                 agent_name: str = DEFAULT_AGENT_NAME,
                 local_dir: Path | None = None):
        self.agent_name = agent_name or DEFAULT_AGENT_NAME
        self._local_dir = Path(local_dir).expanduser() if local_dir else None

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def product_name(self) -> str:
        ...

    @property
    @abstractmethod
    def default_root(self) -> Path:
        """Framework data root (before ``local_dir`` override).

        This is the *root*, not necessarily the collected directory: single-agent
        and file-per-agent frameworks collect directly here, while root-per-agent
        frameworks derive ``workspace_root`` by appending a per-agent subdirectory
        (e.g. ``workspaces/<name>``)."""
        ...

    @property
    @abstractmethod
    def patterns(self) -> list[str]:
        """fnmatch globs (workspace-relative); may contain ``{name}``."""
        ...

    # ------------------------------------------------------------------
    # All-mode & watch constraint
    # ------------------------------------------------------------------

    def _is_all(self) -> bool:
        """Whether we are in 'all sub-agents' mode."""
        return self.agent_name == ALL_AGENT_NAME

    @property
    def supports_individual_watch(self) -> bool:
        """Whether ``watch`` supports a single sub-agent name.

        File-per-agent+shared products must override this to ``False`` because
        shared files would cascade changes between repos.
        """
        return True

    def _effective_patterns(self) -> list[str]:
        """Patterns to match against.  Root-per-agent classes override this to
        add an agent-name prefix in all mode."""
        return self.patterns

    # ------------------------------------------------------------------
    # All-mode path prefixing (for cross-framework conversion)
    # ------------------------------------------------------------------

    @property
    def is_root_per_agent(self) -> bool:
        """Whether sub-agents are separate directories (root-per-agent layout).

        All-mode cross-framework conversion is only well-defined between two
        root-per-agent frameworks, where every agent maps 1:1 to a directory
        prefix.  Other layouts return ``False``.
        """
        return False

    def split_all_path(self, rel_path: str) -> tuple[str | None, str]:
        """Split an all-mode path into ``(agent_name, bare_path)``.

        ``bare_path`` is the path relative to a single agent's root (i.e. what a
        non-all spec would use).  Returns ``(None, rel_path)`` when the path has
        no recognizable agent prefix (e.g. top-level ``README.md``).
        Root-per-agent frameworks override this.
        """
        return (None, rel_path)

    def join_all_path(self, agent_name: str, bare_path: str) -> str:
        """Inverse of :meth:`split_all_path`: build this framework's all-mode
        path for *agent_name* + *bare_path*."""
        return bare_path

    # ------------------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------------------

    # Sub-paths (in priority order) that may hold the real data root when
    # ``local_dir`` is given one level too high -- e.g. nanobot's install root
    # ``.nanobot`` versus its data root ``.nanobot/workspace``.  Empty (the
    # default) means the install root IS the data root, so no probing happens.
    _ROOT_SUBDIRS: tuple[str, ...] = ()

    def _holds_own_files(self, base: Path) -> bool:
        """Whether *base* directly holds this framework's files.

        Markers are the leading segments of every pattern that carry no
        wildcard or ``{name}`` placeholder, i.e. the fixed top-level entries
        a populated workspace of this framework must have.
        """
        for pattern in self.patterns:
            head = pattern.split('/')[0]
            if any(c in head for c in '*?{'):
                continue
            if (base / head).exists():
                return True
        return False

    def _probe_root(self, base: Path) -> Path:
        """Resolve *base* to the data root, descending one known sub-path.

        Users naturally pass the install root (``--local_dir ~/.nanobot``)
        while the files live a level down (``~/.nanobot/workspace``), which
        used to fail with a bare 'no files found'.  Descend only into a
        declared sub-path that already EXISTS, and only when *base* holds none
        of this framework's own files -- so an explicit data root still wins,
        and a fresh/empty output dir is never redirected (that would silently
        relocate written files).  Deliberately not a recursive search: this
        path is also the WRITE target for download/convert, where guessing a
        nested directory (a backup copy, say) could clobber unrelated files.
        """
        if not self._ROOT_SUBDIRS or self._holds_own_files(base):
            return base
        for sub in self._ROOT_SUBDIRS:
            candidate = base / sub
            if candidate.is_dir():
                return candidate
        return base

    @property
    def root(self) -> Path:
        """Effective framework data root: ``local_dir`` override, else default.

        ``local_dir`` ALWAYS means the data root, uniformly across every
        framework; per-agent subdirectories (if any) are derived from it by
        ``workspace_root``.  An override that points at the install root
        instead is normalized by :meth:`_probe_root`.
        """
        if self._local_dir is not None:
            return self._probe_root(self._local_dir)
        return self.default_root

    @property
    def workspace_root(self) -> Path:
        """Directory ``collect``/``apply`` operate on.

        Defaults to the data root (single-agent / file-per-agent, where the root
        IS the workspace). Root-per-agent frameworks override this to append the
        per-agent subdirectory."""
        return self.root

    def _is_global(self) -> bool:
        """Whether we are in global-only mode (shared files only, no sub-agent)."""
        return self.agent_name == GLOBAL_AGENT_NAME

    def resolved_patterns(self) -> list[str]:
        """Resolve glob patterns for the current agent mode.

        Convention: In global mode (``GLOBAL_AGENT_NAME``), patterns containing
        the ``{name}`` placeholder are excluded because they target specific
        sub-agents.  Shared/framework-level patterns (those without ``{name}``)
        remain.
        """
        if self._is_global():
            return [p for p in self._effective_patterns() if '{name}' not in p]
        name = '*' if self._is_all() else self.agent_name
        return [p.format(name=name) for p in self._effective_patterns()]

    def matches(self, rel_path: str, patterns: list[str]) -> bool:
        """Return True if *rel_path* matches any of the given glob *patterns*."""
        for pattern in patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
        return False

    def _walk_matched(self) -> list[tuple[str, Path]]:
        """Walk workspace and return (rel_path, Path) for matched files."""
        root = self.workspace_root
        if not root.is_dir():
            return []
        patterns = self.resolved_patterns()
        matched: list[tuple[str, Path]] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith('.'))
            for fname in sorted(filenames):
                if fname.startswith('.'):
                    continue
                f = Path(dirpath) / fname
                if f.is_symlink():
                    continue
                try:
                    rel = f.relative_to(root).as_posix()
                except ValueError:
                    continue
                if not self.matches(rel, patterns):
                    continue
                if self._is_excluded_asset(rel):
                    continue
                try:
                    size = f.stat().st_size
                    if size > MAX_FILE_SIZE:
                        logger.warning(
                            'Skip large file %s (%d bytes exceeds limit %d)',
                            f, size, MAX_FILE_SIZE)
                        continue
                except OSError:
                    continue
                matched.append((rel, f))
        return matched

    def _is_excluded_asset(self, rel_path: str) -> bool:
        """Hook: drop specific *matched* files from collection.

        Base excludes nothing. Frameworks override to skip files that are
        theirs by default and should not travel across machines/frameworks
        (e.g. Hermes's bundled default skill library).
        """
        return False

    def collect(self) -> dict[str, str]:
        """Gather allowed workspace files as {relative_path: text_content}."""
        result: dict[str, str] = {}
        for rel, f in self._walk_matched():
            try:
                result[rel] = f.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError) as e:
                logger.warning('Skip %s: %s', f, e)
        return result

    def collect_bytes(self) -> dict[str, bytes]:
        """Gather allowed workspace files as {relative_path: raw_bytes}.

        Unlike :meth:`collect`, this includes binary files and does not skip
        on UnicodeDecodeError.
        """
        result: dict[str, bytes] = {}
        for rel, f in self._walk_matched():
            try:
                result[rel] = f.read_bytes()
            except OSError as e:
                logger.warning('Skip %s: %s', f, e)
        return result

    def list_agents(self) -> list[str]:
        """Discover sub-agent names available on disk.

        Default: single-agent products report ``["default"]``.  Root-per-agent
        and file-per-agent products override this to enumerate their layout.
        """
        return [DEFAULT_AGENT_NAME]

    def resolve_default_agent_name(self) -> str:
        """Which agent an omitted ``--name`` should operate on.

        Default: the ``default`` agent.  Frameworks that keep a notion of an
        *active* sub-agent (e.g. openhuman's ``activeProfileId``) override
        this so a name-less convert picks the persona the user is actually
        working with instead of the bare default.  Must never raise: an
        absent / unreadable active-agent marker falls back to
        ``DEFAULT_AGENT_NAME``.
        """
        return DEFAULT_AGENT_NAME

    def _list_agents_from_dir(self, agents_dir: Path) -> list[str]:
        """List agents from a directory, prepending DEFAULT if not present."""
        agents = _list_agent_files(agents_dir)
        if DEFAULT_AGENT_NAME not in agents:
            agents = [DEFAULT_AGENT_NAME] + agents
        return agents

    def sanitize_inbound_file(self, rel_path: str, content: bytes) -> bytes:
        """Sanitize a single inbound (remote -> local) file before it is written.

        This is the single choke point every inbound write path MUST pass
        through (full ``apply`` and incremental ``pull_incremental`` alike), so
        framework-specific cleaning (e.g. stripping secrets from QwenPaw
        ``agent.json``) is applied uniformly regardless of sync mode.

        The base implementation returns *content* unchanged. Subclasses may
        override to rewrite specific files. Implementations must be
        byte-preserving for files they do not care about.
        """
        return content

    def sanitize_outbound_file(self, rel_path: str, content: bytes) -> bytes:
        """Sanitize a single outbound (local -> remote) file before it is pushed.

        Symmetric to :meth:`sanitize_inbound_file`: this is the choke point the
        upload / watch push paths pass local files through, so machine-local
        secrets (API keys / tokens a user left in a local config file) are
        stripped BEFORE anything leaves the machine -- never uploaded to the
        remote repo, and therefore never written into its git history.

        The base implementation delegates to :meth:`sanitize_inbound_file`, so a
        framework whose inbound cleaning does no machine-local identity rebinding
        (hermes ``config.yaml``, openhuman ``config.toml``) gets a correct
        outbound sanitize for free. Frameworks whose inbound hook DOES rebind
        identity (qwenpaw ``agent.json``) must override this to blank secrets
        WITHOUT writing machine-local identity into the upload.
        """
        return self.sanitize_inbound_file(rel_path, content)

    def apply(self, resources: dict) -> list[str]:
        """Write resource files back to the workspace.  Returns list of written paths.

        Values may be ``str`` (text, encoded as UTF-8) or ``bytes`` (binary
        assets such as skill PDFs/images), written verbatim.
        """
        root = self.workspace_root.resolve()
        written: list[str] = []
        for rel_path, content in resources.items():
            target = (root / rel_path).resolve()
            if not target.is_relative_to(root):
                logger.warning('Path traversal blocked: %s', rel_path)
                continue
            raw = content if isinstance(content,
                                        bytes) else content.encode('utf-8')
            sanitized = self.sanitize_inbound_file(rel_path, raw)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(sanitized)
            written.append(str(target))
        return written


def _list_agent_files(agents_dir: Path) -> list[str]:
    """Return the stems of ``*.md`` files in an ``agents/`` directory."""
    if not agents_dir.is_dir():
        return []
    return sorted(f.stem for f in agents_dir.glob('*.md') if f.is_file())


# ---------------------------------------------------------------------------
# Framework registry
# ---------------------------------------------------------------------------
FRAMEWORK_REGISTRY: dict[str, Type[WorkspaceSpec]] = {}


def register_framework(name: str, cls: Type[WorkspaceSpec]) -> None:
    """Register a framework workspace spec.  Idempotent.

    Example::

        from ms_agent.agent_hub import WorkspaceSpec, register_framework

        class MyCustomWorkspace(WorkspaceSpec):
            ...

        register_framework("my-framework", MyCustomWorkspace)
    """
    FRAMEWORK_REGISTRY[name] = cls
