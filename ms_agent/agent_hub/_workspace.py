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


# Mapping keys whose VALUES are secret bags regardless of the inner key names:
# ``env`` (MCP server environment variables) and ``headers`` (HTTP headers are
# bearer credentials in disguise -- their names are arbitrary, e.g. a gateway
# may demand ``X-Auth-Code``, which no key-name vocabulary could enumerate).
# Every scrubber blanks the whole mapping, keeping only the key names.
SECRET_BAG_KEYS = frozenset(('env', 'headers'))

# Keys whose LIST value is a stdio command line to scrub positionally
# (``args`` and its common alias ``argv``) -- shared by every scrubber.
ARGS_LIST_KEYS = ('args', 'argv')

_URL_RE = re.compile(r'^[A-Za-z][A-Za-z0-9+.\-]*://')

# Query-parameter names treated as secrets BEYOND :func:`is_secret_key`:
# an OAuth ``code`` or a request ``signature`` is a credential in a URL even
# though a bare config key named ``code`` is not (too broad for the global
# vocabulary). Header names need no counterpart -- they have the bag rule.
_URL_SECRET_PARAMS = frozenset(('sig', 'signature', 'pwd', 'code'))


def scrub_url_secrets(url: str) -> str:
    """Strip credentials embedded in a URL, leaving the rest byte-identical.

    Three carriers are removed:

    * userinfo passwords -- ``https://user:pass@host`` becomes
      ``https://user@host`` (the username is kept);
    * bare userinfo -- ``https://<token>@host`` (no colon) is dropped
      entirely: colon-less userinfo is how PAT-style tokens travel
      (``https://ghp_xxx@host``) and cannot be told from a username, so
      fail-closed wins;
    * query parameters whose NAME matches :func:`is_secret_key` or
      :data:`_URL_SECRET_PARAMS` -- the name is kept and the VALUE blanked
      (``?api_key=X&model=y`` -> ``?api_key=&model=y``), mirroring how
      headers / env / args keep names and blank values.

    Only a string that IS a bare absolute URL is processed: it must start
    with ``scheme://`` and contain no whitespace, so free text that merely
    CONTAINS a URL (a prompt sentence, a doc note) is never truncated or
    rewritten, and a ``URL # comment`` scalar is handled by the caller's
    comment split. Non-secret URLs round-trip byte-identically; malformed
    input is returned as-is (this helper must never raise on the outbound
    path).
    """
    if not isinstance(url, str) or not _URL_RE.match(url):
        return url
    if re.search(r'\s', url):
        return url
    scheme, sep, rest = url.partition('://')
    # The authority ends at the first '/', '?' or '#'.
    cut = len(rest)
    for ch in ('/', '?', '#'):
        idx = rest.find(ch)
        if idx != -1:
            cut = min(cut, idx)
    authority, tail = rest[:cut], rest[cut:]
    at = authority.rfind('@')
    if at != -1:
        userinfo = authority[:at]
        user, colon, password = userinfo.partition(':')
        if colon and password:
            authority = (f'{user}@' if user else '') + authority[at + 1:]
        elif userinfo:
            # Bare userinfo (no colon): indistinguishable from a token.
            authority = authority[at + 1:]
    path = tail
    query = fragment = ''
    if '#' in path:
        path, frag = path.split('#', 1)
        fragment = '#' + frag
    if '?' in path:
        path, q = path.split('?', 1)
        pairs = []
        for p in q.split('&'):
            name = p.split('=', 1)[0]
            if p and (is_secret_key(name)
                      or name.lower() in _URL_SECRET_PARAMS):
                pairs.append(name + '=')
            else:
                pairs.append(p)
        query = '?' + '&'.join(pairs)
    return f'{scheme}{sep}{authority}{path}{query}{fragment}'


_SECRET_FLAG_RE = re.compile(r'^-{1,2}[A-Za-z][\w.\-]*$')


def scrub_args_secrets(args: list) -> list:
    """Blank secrets passed on a stdio command line (an ``args`` list).

    Three spellings are covered:

    * ``--api-key VALUE`` -- when a flag's name matches
      :func:`is_secret_key`, the FOLLOWING element (the value) is blanked;
    * ``--api-key=VALUE`` / ``-token=VALUE`` -- the value after ``=`` is
      blanked in place (dash count does not matter);
    * ``NAME=VALUE`` -- env-style assignments like the ones docker ``-e``
      forwards (``["-e", "GITHUB_TOKEN=ghp_x"]``): NAME is checked against
      the vocabulary and the value blanked, keeping the ``NAME=`` prefix.

    Elements containing ``://`` are URLs, never NAME=VALUE pairs -- they are
    left to the callers' URL pass. Non-secret elements pass through as-is;
    non-string items are untouched.
    """
    if not isinstance(args, list):
        return args
    out = list(args)
    n = len(out)
    i = 0
    while i < n:
        item = out[i]
        if isinstance(item, str):
            if '=' in item and '://' not in item:
                name = item.partition('=')[0]
                if is_secret_key(name.lstrip('-')):
                    out[i] = name + '='
            elif _SECRET_FLAG_RE.match(item):
                name = item.lstrip('-')
                if is_secret_key(name) and i + 1 < n \
                        and isinstance(out[i + 1], str) \
                        and not _SECRET_FLAG_RE.match(out[i + 1]):
                    out[i + 1] = ''
                    i += 1
        i += 1
    return out


def _split_inline_comment(val: str) -> tuple[str, str]:
    """Split a trailing ``# ...`` comment off a scalar value.

    A ``#`` opens a comment only outside quotes and either at the start of
    the value or right after whitespace (the YAML/TOML rule), so
    ``https://h/p#frag`` and ``"a # b"`` keep their ``#``. Returns
    ``(value_region, comment)`` where *comment* is ``''`` when there is no
    comment; *value_region* keeps any whitespace that preceded the ``#``.
    """
    quote = ''
    for idx, ch in enumerate(val):
        if quote:
            if ch == quote:
                quote = ''
        elif ch in '\'"':
            quote = ch
        elif ch == '#' and (idx == 0 or val[idx - 1] in ' \t'):
            return val[:idx], val[idx:]
    return val, ''


def scrub_scalar_url_token(val: str) -> str:
    """Scrub credentials in a URL scalar, keeping quotes/whitespace/comment.

    Used by the line-based YAML/TOML scrubbers on raw ``key: value``
    captures: the value may carry surrounding whitespace, quotes and a
    trailing ``# comment``. The comment is split off FIRST (outside quotes)
    so ``url: https://h?token=X # note`` scrubs the URL part only -- the
    comment is re-appended verbatim instead of being glued into the value.
    Returns *val* byte-identical unless a secret was actually removed.
    """
    region, comment = _split_inline_comment(val)
    lead = region[:len(region) - len(region.lstrip())]
    trail = region[len(region.rstrip()):]
    core = region.strip()
    quote = ''
    if len(core) >= 2 and core[0] == core[-1] and core[0] in '\'"':
        quote = core[0]
        core = core[1:-1]
    cleaned = scrub_url_secrets(core)
    if cleaned == core:
        return val
    return f'{lead}{quote}{cleaned}{quote}{trail}{comment}'


def _scrub_yaml_flow_args(val: str) -> str:
    """Positional scrub of a flow-style ``args: [-y, srv, --api-key, X]``.

    Returns the rewritten value text (brackets included) or *val* unchanged
    when nothing secret was found. Items may be quoted; quotes are stripped
    for flag detection and dropped in the (rewritten) output. Mirrors
    :func:`scrub_args_secrets` plus URL scrubbing of each item.
    """
    lead = val[:len(val) - len(val.lstrip())]
    body = val.strip()
    if not body.startswith('['):
        return val
    end = body.find(']')
    if end == -1:
        return val
    inner, trail = body[1:end], body[end + 1:]
    items = [it.strip() for it in inner.split(',')] if inner.strip() else []
    norm = []
    for it in items:
        if len(it) >= 2 and it[0] == it[-1] and it[0] in '\'"':
            norm.append(it[1:-1])
        else:
            norm.append(it)
    scrubbed = [scrub_url_secrets(it) for it in scrub_args_secrets(norm)]
    if scrubbed == norm:
        return val
    parts = []
    for orig, norm_it, scrub_it in zip(items, norm, scrubbed):
        if scrub_it == norm_it:
            parts.append(orig)
        elif scrub_it == '':
            parts.append("''")
        else:
            parts.append(scrub_it)
    return f'{lead}[{", ".join(parts)}]{trail}'


def scrub_toml_array_args(val: str) -> str:
    """Positional scrub of a single-line TOML ``args = ["-y", "--token", X]``.

    Like :func:`_scrub_yaml_flow_args` but TOML strings must stay quoted, so
    each item keeps (or receives) its quotes in the rewritten output. Returns
    *val* unchanged when nothing secret was found.
    """
    lead = val[:len(val) - len(val.lstrip())]
    body = val.strip()
    if not body.startswith('['):
        return val
    end = body.find(']')
    if end == -1:
        return val
    inner, trail = body[1:end], body[end + 1:]
    items = [it.strip() for it in inner.split(',') if it.strip()]
    norm, quotes = [], []
    for it in items:
        if len(it) >= 2 and it[0] == it[-1] and it[0] in '\'"':
            quotes.append(it[0])
            norm.append(it[1:-1])
        else:
            quotes.append('"')
            norm.append(it)
    scrubbed = [scrub_url_secrets(it) for it in scrub_args_secrets(norm)]
    if scrubbed == norm:
        return val
    parts = []
    for orig, norm_it, scrub_it, q in zip(items, norm, scrubbed, quotes):
        if scrub_it == norm_it:
            parts.append(orig)
        else:
            parts.append(f'{q}{scrub_it}{q}')
    return f'{lead}[{", ".join(parts)}]{trail}'


def scrub_yaml_secrets(text: str) -> str:
    """Blank secret values in a YAML config *text*, line-by-line.

    Regex/line based (not a YAML round-trip) so user comments, key order and
    formatting are preserved -- only the secret *values* are cleared. Rules
    per ``key: value`` line:

    * a key whose name matches :func:`is_secret_key` -> value cleared, anywhere
      in the tree (e.g. top-level ``model.api_key`` or ``llm.modelscope_api_key``);
    * every scalar nested inside an ``env`` or ``headers`` mapping
      (:data:`SECRET_BAG_KEYS`) -> value cleared regardless of key name, at
      ANY depth (those blocks are free-form secret bags where API keys live
      under arbitrary names) -- same policy as the JSON/TOML scrubbers;
    * any scalar that IS a bare absolute URL -> userinfo credentials and
      secret query parameters stripped (:func:`scrub_url_secrets`), wherever
      it lives (``base_url``, MCP ``url``, ...); a trailing ``# comment`` is
      split off first so it is never glued into the value;
    * ``args`` lists anywhere (block ``- item`` and flow ``[a, b]`` styles)
      -> secret flag values, ``NAME=VALUE`` env assignments and URL items are
      scrubbed, mirroring :func:`scrub_args_secrets`.

    Beyond simple ``key: <scalar>`` lines the scrubber also covers the other
    legal spellings a secret can hide in:

    * flow mappings (``llm: {api_key: X, model: y}``) -- secret pairs inside
      the braces are cleared in place; an ``env: {...}`` / ``headers: {...}``
      flow mapping is cleared wholesale, and URL values inside are scrubbed;
    * block/folded scalars (``api_key: |`` / ``>`` and their chomping
      variants) -- the opener is blanked and the indented content lines that
      carry the secret are dropped;
    * a block opener carrying an inline comment (``mcp_servers:  # remote``)
      is still recognized as an opener.

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
    list_item = re.compile(r'^(?P<indent>[ \t]*)-[ \t]+(?P<val>\S.*)$')
    # Indent of the active secret-bag (``env`` / ``headers``) / ``args``
    # block openers; ``None`` = not inside. Both are tracked at ANY depth,
    # mirroring the JSON scrubber's global policy.
    bag_indent: int | None = None
    args_indent: int | None = None
    # Inside a block ``args:`` list: the previous item was a secret flag whose
    # value is still owed (``--api-key`` -> the NEXT item is that value).
    args_pending = False
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
        # Block ``args:`` list items: positional scrub of the stdio command
        # line (secret flag values blanked, URL items scrubbed).
        if args_indent is not None:
            cur = len(line) - len(line.lstrip(' \t'))
            am = list_item.match(line)
            if am and cur >= args_indent:
                core = am.group('val').strip()
                quote = ''
                if len(core) >= 2 and core[0] == core[-1] \
                        and core[0] in '\'"':
                    quote = core[0]
                    core = core[1:-1]
                if args_pending and not _SECRET_FLAG_RE.match(core):
                    # The value owed to the previous secret flag: blank it.
                    out.append(f"{am.group('indent')}- ''")
                    args_pending = False
                    continue
                args_pending = False
                if _SECRET_FLAG_RE.match(core) and '=' not in core \
                        and is_secret_key(core.lstrip('-')):
                    args_pending = True
                    out.append(line)
                    continue
                if '=' in core and '://' not in core:
                    name = core.partition('=')[0]
                    if is_secret_key(name.lstrip('-')):
                        out.append(f"{am.group('indent')}- {quote}{name}="
                                   f"{quote}")
                        continue
                cleaned = scrub_url_secrets(core)
                if cleaned != core:
                    out.append(f"{am.group('indent')}- {quote}{cleaned}"
                               f"{quote}")
                    continue
                out.append(line)
                continue
            if cur <= args_indent:
                args_indent = None
                args_pending = False
        m = kv.match(line)
        if not m:
            out.append(line)
            continue
        indent = len(m.group('indent'))
        # Dedenting to <= a block opener's indent leaves that block.
        if bag_indent is not None and indent <= bag_indent:
            bag_indent = None
        if args_indent is not None and indent <= args_indent:
            args_indent = None
            args_pending = False
        key = m.group('key').strip()
        val = m.group('val')
        in_bag = bag_indent is not None and indent > bag_indent
        secret_key = is_secret_key(key)
        # Block/folded scalar opener (| / > + chomping variants): the secret
        # lives on the FOLLOWING deeper-indented lines -- blank the key and
        # drop that content.
        if val is not None and block_opener.match(val.strip()):
            if secret_key or in_bag:
                out.append(
                    f"{m.group('indent')}{m.group('key')}{m.group('sep')}''")
                skip_indent = indent
            else:
                out.append(line)
            continue
        # Flow mapping value: scrub secret pairs inside the braces. An
        # ``env`` / ``headers`` (or secret-named) flow mapping is a free-form
        # secret bag -> clear every value in it.
        if val is not None and val.lstrip().startswith(
                '{') and val.strip() != '{}':
            clear_all = secret_key or in_bag or key in SECRET_BAG_KEYS

            def _repl(pm, _all=clear_all):
                if _all or is_secret_key(pm.group('key').strip('"\'')):
                    return f"{pm.group('key')}{pm.group('sep')}''"
                cleaned = scrub_scalar_url_token(pm.group('val'))
                if cleaned != pm.group('val'):
                    return (f"{pm.group('key')}{pm.group('sep')}{cleaned}")
                return pm.group(0)

            out.append(f"{m.group('indent')}{m.group('key')}{m.group('sep')}"
                       f'{flow_pair.sub(_repl, val)}')
            continue
        # A trailing comment must not hide a block opener:
        # ``mcp_servers:  # remote`` still opens a block.
        bare_val = _split_inline_comment(val)[0].strip() if val else None
        has_scalar = bare_val not in (None, '', '{}', '[]')
        # A key with no scalar value opens a mapping/list block: track the
        # secret-bag and ``args`` openers (at any depth, matching the JSON
        # policy) so their descendants can be scoped, then emit the opener
        # line unchanged.
        if not has_scalar:
            if key in SECRET_BAG_KEYS:
                bag_indent = indent
            elif key in ARGS_LIST_KEYS:
                args_indent = indent
                args_pending = False
            out.append(line)
            continue
        if secret_key or in_bag:
            out.append(
                f"{m.group('indent')}{m.group('key')}{m.group('sep')}''")
            continue
        # Flow-list ``args: [...]``: positional scrub inside the brackets.
        if key in ARGS_LIST_KEYS and val.lstrip().startswith('['):
            cleaned = _scrub_yaml_flow_args(val)
            if cleaned != val:
                out.append(f"{m.group('indent')}{m.group('key')}"
                           f"{m.group('sep')}{cleaned}")
            else:
                out.append(line)
            continue
        cleaned = scrub_scalar_url_token(val)
        if cleaned != val:
            out.append(
                f"{m.group('indent')}{m.group('key')}{m.group('sep')}"
                f'{cleaned}')
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
    * every value inside an ``env`` or ``headers`` mapping -> blanked
      regardless of key name (:data:`SECRET_BAG_KEYS`; both are free-form
      secret bags -- env var and header names are arbitrary);
    * command-line lists under ``args`` / ``argv`` (:data:`ARGS_LIST_KEYS`)
      -> secret flag values and ``NAME=VALUE`` env assignments blanked
      (:func:`scrub_args_secrets`);
    * every string that IS a bare absolute URL -> userinfo credentials and
      secret query parameters stripped (:func:`scrub_url_secrets`), wherever
      it lives (provider ``base_url``, MCP ``url``, ...). Free text that
      merely CONTAINS a URL (a prompt sentence) is left untouched -- only
      whitespace-free, scheme-led strings are treated as URLs.

    Non-secret structure and values are preserved; nested dicts / lists are
    walked recursively.
    """
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in SECRET_BAG_KEYS and isinstance(val, dict):
                obj[key] = {k: '' for k in val}
            elif is_secret_key(key):
                obj[key] = ''
            elif key in ARGS_LIST_KEYS and isinstance(val, list):
                obj[key] = scrub_args_secrets(val)
                scrub_json_secrets(obj[key])
            elif isinstance(val, str):
                obj[key] = scrub_url_secrets(val)
            else:
                scrub_json_secrets(val)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            if isinstance(item, str):
                obj[idx] = scrub_url_secrets(item)
            else:
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
