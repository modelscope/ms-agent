# Copyright (c) ModelScope Contributors. All rights reserved.
"""Core command logic for agent workspace management.

This module contains the business logic for agent upload, download, convert,
watch, stop, and recover operations.  The CLI adapter (``ms_agent.cli.agent``)
calls these functions to perform the actual work.
"""
from __future__ import annotations

import getpass
import os
import sys
import zipfile
from modelscope_hub.agent import (AgentApi, agent_last_modified,
                                  agent_visibility_label)
from modelscope_hub.errors import APIError
from pathlib import Path

from ms_agent.utils.logger import get_logger
from . import _display as display
from ._defaults import get_defaults
from ._merge import merge_resources, merged_away_pairs
from ._workspace import (ALL_AGENT_NAME, DEFAULT_AGENT_NAME,
                         FRAMEWORK_REGISTRY, GLOBAL_AGENT_NAME, WorkspaceSpec)

logger = get_logger()

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _print_openhuman_next_steps(root) -> None:
    """After a successful convert/download, remind the user that the result is
    not yet usable: openhuman discovers agents only through the
    ``workspace/agents/<id>.toml`` registry, which we deliberately do not
    generate, so they must create it by hand.

    Uses ``Logger.info`` rather than ``display``/``print`` per the tech lead's
    requirement.
    """
    agents_dir = f'{root}/agents'
    doc = ('https://github.com/tinyhumansai/openhuman/blob/main/'
           'gitbooks/developing/architecture/agent-harness.md')
    example = ('https://github.com/tinyhumansai/openhuman/blob/main/'
               'src/openhuman/agent/registry/agents/researcher/agent.toml')
    logger.info(
        '转换/下载已完成，但当前还不能直接使用（若尚未注册）。OpenHuman 只通过 '
        'workspace/agents/<agent-id>.toml 注册表发现智能体，本次仅写入了 persona/skill 文件。\n'
        '请手动完成：\n'
        '  官方文档（如何构建 agent.toml）：' + doc + '\n'
        '  官方示例（researcher/agent.toml）：' + example + '\n'
        f'  1) 在 {agents_dir}/ 下手动创建 <agent-id>.toml，包含 id / when_to_use / '
        'system_prompt.inline（粘贴 SOUL.md 内容）/ model.exact="inherit"；id 仅限字母、数字、"_"、"-"。\n'
        '  2) UI「设置 → 智能体 → 新建智能体」，id / model / 工具白名单与 TOML 保持一致。\n'
        '  3) UI「设置 → 智能体配置 → 新建配置」，base agent id 填同一个 id。\n'
        '  4) 新建一个对话即可使用。'
    )
    logger.info(
        'Conversion/download finished, but the agent is NOT usable yet '
        '(if you have not registered it). OpenHuman discovers agents only via the '
        'workspace/agents/<agent-id>.toml registry; this run wrote persona/skill files only.\n'
        'Manual steps:\n'
        '  Official docs (how to build agent.toml): ' + doc + '\n'
        '  Official example (researcher/agent.toml): ' + example + '\n'
        f'  1) Create {agents_dir}/<agent-id>.toml with: id / when_to_use / '
        'system_prompt.inline (paste the SOUL.md content) / model.exact="inherit"; '
        'id may contain only letters, digits, "_", "-".\n'
        '  2) UI "Settings → Agents → New Agent": keep id / model / tool allowlist consistent with the TOML.\n'
        '  3) UI "Settings → Agent Config → New Config": set base agent id to the same id.\n'
        '  4) Start a new conversation.'
    )


def _fail(message: str) -> int:
    """Print an error and return exit code 1."""
    print(f'Error: {message}', file=sys.stderr)
    return 1


def api_error_message(e: APIError, action: str = 'request') -> str:
    """Return a user-friendly message based on the HTTP status code."""
    status = e.status_code or 0
    rid = f' (request_id={e.request_id})' if getattr(e, 'request_id',
                                                     None) else ''
    if status == 401:
        return 'authentication failed. Please login again.' + rid
    if status == 403:
        return ('permission denied. You do not have access to this resource.'
                + rid)
    if status == 404:
        return ('resource not found. Check the repository name and try again.'
                + rid)
    if status >= 500:
        return ('server encountered an issue. Please wait a moment and try '
                'again.' + rid)
    return f'{action} failed (HTTP {status}: {e.message}){rid}'


def repo_name(framework: str, name: str) -> str:
    """Derive the remote repository name from framework and sub-agent name.

    - name is "all" or empty: use framework alone
    - Both provided: ``{framework}-{name}``
    - Only one provided: use that value directly
    - Neither provided: ``"default"``
    """
    fw = (framework or '').strip()
    n = (name or '').strip()
    if n == ALL_AGENT_NAME:
        n = ''
    if fw and n:
        return f'{fw}-{n}'
    if fw:
        return fw
    if n:
        return n
    return 'default'


def resolve_remote(
    repo: str | None = None,
    name: str | None = None,
    framework: str = '',
    username: str = '',
) -> tuple[str, str]:
    """Resolve remote target as (group, repo_name).

    - repo contains '/' -> split into (group, repo_name), ignore username
    - repo without '/' -> (username, repo)
    - repo is None/empty -> derive from name+framework using repo_name logic
    """
    if repo:
        if '/' in repo:
            parts = repo.split('/', 1)
            return parts[0], parts[1]
        return username, repo
    derived = repo_name(framework, name or '')
    return username, derived


def resolve_local_name(name: str | None, framework: str, local_dir=None):
    """Resolve local agent name when --name is omitted.

    Returns (resolved_name, error_message).
    - If *name* is given -> use it directly.
    - If omitted:
      - root-per-agent / single-agent layout (no ``{name}`` placeholder) ->
        always ``DEFAULT_AGENT_NAME``.  'default' is a real workspace
        directory, so sibling sub-agents never trigger auto-select or an error.
      - file-per-agent+shared layout (patterns use ``{name}``) -> inspect the
        ``agents/`` files: exactly 1 non-default -> auto-select it; 0 ->
        ``GLOBAL_AGENT_NAME`` (shared files only); multiple -> error.
    """
    if name:
        return name, None

    spec_cls = FRAMEWORK_REGISTRY[framework]
    local = Path(local_dir).expanduser() if local_dir else None
    tmp_spec = spec_cls(agent_name=DEFAULT_AGENT_NAME, local_dir=local)

    # root-per-agent / single-agent: an omitted --name always means the default
    # agent.  Only layouts with a ``{name}`` placeholder (file-per-agent+shared)
    # have a meaningful shared/global mode or per-agent auto-selection.
    has_shared_mode = any('{name}' in p for p in tmp_spec.patterns)
    if not has_shared_mode:
        return DEFAULT_AGENT_NAME, None

    agents = tmp_spec.list_agents()
    real_agents = [a for a in agents if a != DEFAULT_AGENT_NAME]
    if len(real_agents) == 1:
        return real_agents[0], None
    if len(real_agents) == 0:
        return GLOBAL_AGENT_NAME, None
    return None, (f"multiple sub-agents found: {', '.join(agents)}. "
                  f'Please specify --name to select one.')


STABLE_FRAMEWORKS = frozenset(['ms-agent', 'qwenpaw'])

_TRY_EXP_ENV = 'TRY_EXP_FRAMEWORKS'


def _experimental_enabled() -> bool:
    """True when ``TRY_EXP_FRAMEWORKS`` opts into the experimental frameworks.

    Read on every call (not cached at import time) so tests and callers can
    flip the variable within a live process.
    """
    return os.environ.get(_TRY_EXP_ENV,
                          '').strip().lower() in ('1', 'true', 'yes', 'on')


def _enabled_frameworks() -> set[str]:
    """Registered frameworks the current environment is allowed to use."""
    if _experimental_enabled():
        return set(FRAMEWORK_REGISTRY)
    return {fw for fw in FRAMEWORK_REGISTRY if fw in STABLE_FRAMEWORKS}


def available_frameworks() -> str:
    """Comma-separated list of frameworks usable in the current environment."""
    return ', '.join(sorted(_enabled_frameworks()))


def check_framework(framework: str, label: str = 'framework') -> str | None:
    """Validate *framework*, returning an error message or ``None`` if OK.

    Distinguishes a genuinely unknown name from a registered-but-experimental
    one: the latter gets a hint about ``TRY_EXP_FRAMEWORKS`` instead of a
    misleading "unknown framework", since the framework does exist and works
    -- it is only gated.
    """
    if framework in _enabled_frameworks():
        return None
    if framework in FRAMEWORK_REGISTRY:
        return (f"{label} '{framework}' is experimental and not enabled. "
                f'Set {_TRY_EXP_ENV}=True to use it. '
                f'Enabled: {available_frameworks()}')
    return (f"unknown {label} '{framework}'. "
            f'Available: {available_frameworks()}')


def build_spec(framework: str, name: str, local_dir=None) -> WorkspaceSpec:
    """Build a WorkspaceSpec instance for the given framework and agent name."""
    spec_cls = FRAMEWORK_REGISTRY[framework]
    local = Path(local_dir).expanduser() if local_dir else None
    return spec_cls(agent_name=name, local_dir=local)


def _existing_skill_names(paths) -> list[str]:
    """Skill dir names already present on the target (``skills/<name>/...``).

    Fed to ``merge_resources(existing_skills=...)`` so a cross-framework
    convert / download never silently overwrites a skill the target already
    has (BUG-024).
    """
    return sorted({
        p.split('/')[1]
        for p in paths if p.startswith('skills/') and p.count('/') >= 2
    })


def convert_resources(
    resources: dict,
    source_fw: str,
    target_fw: str,
    existing_files: set[str] | None = None,
    *,
    all_mode: bool = False,
    src_spec: WorkspaceSpec | None = None,
    dst_spec: WorkspaceSpec | None = None,
    fill_missing_defaults: bool = True,
    collect_merges: list[tuple[str, str]] | None = None,
    collect_skips: list[str] | None = None,
) -> dict:
    """Convert workspace resources from one framework format to another.

    Reuses the cross-framework merge engine.  No-op when source == target.

    When *existing_files* is provided, default template files that already
    exist on the target are filtered out so the target's custom content is
    preserved.  Default templates for files the target does NOT have are kept.

    When *all_mode* is True (root-per-agent -> root-per-agent), paths carry an
    agent prefix; each agent is split out, converted independently as a single
    agent, then re-prefixed for the target framework.  Requires *src_spec* and
    *dst_spec*.

    When *collect_merges* is provided it is extended with ``(src, dst)`` pairs
    for files folded into a catch-all (no standalone target equivalent), so the
    caller can surface a "merged" hint.
    """
    if source_fw == target_fw:
        return resources
    if all_mode:
        return _convert_resources_all(
            resources,
            source_fw,
            target_fw,
            src_spec,
            dst_spec,
            fill_missing_defaults=fill_missing_defaults,
            collect_merges=collect_merges)
    result = merge_resources(
        incoming=resources,
        source_product=source_fw,
        target_product=target_fw,
        source_defaults=get_defaults(source_fw),
        target_defaults=get_defaults(target_fw),
        fill_missing_defaults=fill_missing_defaults,
        overflow_target=(_file_per_agent_identity_path(dst_spec)
                         if dst_spec is not None else None),
        identity_source=(_file_per_agent_identity_path(src_spec)
                         if src_spec is not None else None),
        existing_skills=(_existing_skill_names(existing_files)
                         if existing_files else None),
    )
    if collect_merges is not None:
        collect_merges.extend(merged_away_pairs(result))
    if collect_skips is not None:
        collect_skips.extend(
            a.path for a in result.actions
            if a.action == 'skip' and 'already exists' in a.detail)
    merged = result.merged_files
    if existing_files is not None:
        default_paths = {
            a.path
            for a in result.actions if a.action == 'default'
        }
        merged = {
            k: v
            for k, v in merged.items()
            if k not in default_paths or k not in existing_files
        }
    return merged


def _convert_resources_all(
    resources: dict,
    source_fw: str,
    target_fw: str,
    src_spec: WorkspaceSpec,
    dst_spec: WorkspaceSpec,
    fill_missing_defaults: bool = True,
    collect_merges: list[tuple[str, str]] | None = None,
) -> dict:
    """All-mode cross-framework convert (root-per-agent -> root-per-agent).

    Group incoming files by their source agent prefix, convert each agent as an
    isolated single-agent workspace, then re-prefix the results using the target
    framework's convention.  Top-level files without an agent prefix (e.g.
    README.md) belong to no agent and are dropped.
    """
    groups: dict[str, dict[str, str]] = {}
    for path, content in resources.items():
        agent, bare = src_spec.split_all_path(path)
        if agent is None:
            continue
        groups.setdefault(agent, {})[bare] = content

    src_defaults = get_defaults(source_fw)
    tgt_defaults = get_defaults(target_fw)
    out: dict[str, str] = {}
    for agent, bare_files in groups.items():
        result = merge_resources(
            incoming=bare_files,
            source_product=source_fw,
            target_product=target_fw,
            source_defaults=src_defaults,
            target_defaults=tgt_defaults,
            fill_missing_defaults=fill_missing_defaults,
        )
        for bare_path, content in result.merged_files.items():
            out[dst_spec.join_all_path(agent, bare_path)] = content
        if collect_merges is not None:
            # Re-prefix both sides with the target's per-agent convention so the
            # hint aligns with the written listing's paths.
            for src, dst in merged_away_pairs(result):
                collect_merges.append((
                    dst_spec.join_all_path(agent, src),
                    dst_spec.join_all_path(agent, dst),
                ))
    return out


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def cmd_status(framework: str, local_dir=None) -> int:
    """List discoverable sub-agents for a framework."""
    err = check_framework(framework)
    if err:
        return _fail(err)

    spec = build_spec(framework, DEFAULT_AGENT_NAME, local_dir)
    agents = spec.list_agents()
    print(f'Agents for {framework}:')
    for a in agents:
        tmp = build_spec(framework, a, local_dir)
        files = tmp.collect_bytes()
        print(f'  {a} — {len(files)} file(s), root: {tmp.workspace_root}')
        for rel in sorted(files):
            print(f'    {rel}')
    return 0


def cmd_upload(
    framework: str,
    name: str | None = None,
    local_dir=None,
    repo: str | None = None,
    dry_run: bool = False,
    *,
    visibility: str = 'public',
    endpoint: str | None = None,
    token: str | None = None,
    username: str | None = None,
) -> int:
    """Upload local agent files to remote."""
    err = check_framework(framework)
    if err:
        return _fail(err)

    local_name, err = resolve_local_name(name, framework, local_dir)
    if err:
        return _fail(err)

    spec = build_spec(framework, local_name, local_dir)
    root = spec.workspace_root
    resources: dict[str, bytes] = spec.collect_bytes()
    if not resources:
        display_name = local_name if local_name != GLOBAL_AGENT_NAME else 'global'
        return _fail(
            f'no files found for {framework}/{display_name} under {root}. '
            f'Check the path or pass --local_dir.')

    # Strip machine-local secrets (API keys / tokens the user left in a local
    # config file) BEFORE anything leaves the machine, so they are never pushed
    # to the remote repo or written into its git history. Sanitizing first also
    # lets a config that differs from its default template only by a secret
    # drop out below as an "unchanged default".
    #
    # Upload the user-customized subset only: drop files identical to the
    # framework default templates (same rule convert uses), so untouched
    # boilerplate is never pushed -- keeps upload and convert 1:1-consistent
    # about what "the user's own files" are.
    from ._sync import drop_unchanged_defaults, sanitize_outbound
    try:
        resources = drop_unchanged_defaults(
            sanitize_outbound(resources, spec), framework, spec)
    except ValueError as e:
        # Fail-closed sanitize: a config file that cannot be parsed cannot be
        # verified secret-free -- abort instead of pushing plaintext keys.
        return _fail(str(e))
    if not resources:
        display_name = local_name if local_name != GLOBAL_AGENT_NAME else 'global'
        return _fail(
            f'only default template files under {root} for {framework}/'
            f'{display_name}; nothing user-created to upload.')

    total_bytes = sum(len(v) for v in resources.values())
    from ._format import format_size
    display.header('Upload', f'{framework}/{local_name}')
    display.meta('source', root)
    display.meta('size', format_size(total_bytes))
    display.table(
        'Files',
        [(rel, format_size(len(resources[rel]))) for rel in sorted(resources)],
        headers=['FILE', 'SIZE'],
        color=display.COLOR_WRITTEN,
    )

    if dry_run:
        print('\n[dry-run] nothing uploaded.')
        return 0

    if not endpoint or not token:
        return _fail('not logged in. Provide endpoint and token.')
    if not username:
        return _fail('missing username.')

    client = AgentApi(endpoint=endpoint, token=token)

    effective_name = local_name if local_name != GLOBAL_AGENT_NAME else None
    group, repo_n = resolve_remote(
        repo=repo,
        name=effective_name,
        framework=framework,
        username=username,
    )

    try:
        from ._sync import push_mirror

        # Incremental mirror: list remote (sha256), upload only new/changed
        # files, and prune stale remote files within this upload's scope
        # (spec.resolved_patterns constrains deletes to the current agent's
        # prefix, never other sub-agents). Falls back to a full push when the
        # remote repo is empty/new.
        push_mirror(
            client,
            group,
            repo_n,
            framework,
            resources,
            prune_patterns=spec.resolved_patterns(),
            visibility=visibility,
        )
    except APIError as e:
        return _fail(api_error_message(e, 'upload'))
    except Exception as e:
        return _fail(f'upload failed: {e}')

    display.done(
        f'Synced {len(resources)} file(s) to {group}/{repo_n} (incremental)')
    return 0


def _download_file(client, group: str, repo_n: str, path: str):
    """Download one repo file byte-faithfully, decoding text when possible.

    Always fetches raw bytes (``binary=True``): the default text mode decodes
    the HTTP body with a guessed charset and re-encoding it corrupts binary
    assets (skills/*/assets/*, openhuman wiki/assets/*.png -- a PNG's ``\\x89``
    magic byte is not valid UTF-8).  Content that IS valid UTF-8 is returned
    as ``str`` so the conversion / merge pipeline sees the same text values as
    before; everything else stays ``bytes``, which convert passes through
    verbatim and ``spec.apply`` writes to disk unchanged.
    """
    raw = client.download_repo_file(group, repo_n, path, binary=True)
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw


def _remote_paths_for_agent(
    framework: str,
    requested: str,
    remote_paths: list[str],
    local_dir=None,
) -> tuple[dict[str, str] | None, str | None]:
    """Map remote repo paths to workspace-relative paths for *requested*.

    A repo uploaded with ``-n all`` from a root-per-agent framework stores the
    default agent at bare paths and every named agent under its per-agent
    prefix (hermes ``profiles/<name>/``, openclaw ``workspace-<name>/``,
    qwenpaw ``<name>/``).  When downloading a single agent from such a repo,
    only that agent's files may be taken (with the prefix stripped) --
    otherwise another agent's files would be written into the requested
    agent's directory and its own files silently dropped.

    Returns ``(mapping, error)``: *mapping* is ``{remote_path: relative_path}``
    restricted to the requested agent (identity mapping for legacy
    single-agent bare repos), *error* is set when the repo is an all-layout
    repo that has no files for *requested*.
    """
    identity = {p: p for p in remote_paths}
    if requested in (ALL_AGENT_NAME, GLOBAL_AGENT_NAME):
        # all: every agent's files are wanted as-is; global: shared files are
        # selected by the (name-free) pattern filter downstream.
        return identity, None
    probe = build_spec(framework, requested, local_dir)
    if not probe.is_root_per_agent:
        return identity, None

    prefix = probe.join_all_path(requested, '')
    if not prefix:
        # Requested agent lives at bare paths in all mode (hermes default):
        # keep bare files, exclude every named-agent prefix.
        selected = {
            p: p
            for p in remote_paths
            if probe.split_all_path(p)[0] in (requested, None)
        }
        return (selected, None) if selected else (
            None, f"repository has no files for agent '{requested}'.")

    selected = {
        p: p[len(prefix):]
        for p in remote_paths if p.startswith(prefix) and p != prefix
    }
    if selected:
        return selected, None

    # No prefixed files for the requested agent. Either this is a legacy
    # single-agent repo (bare paths ARE the requested agent's files) or an
    # all-layout repo that simply lacks this agent. Named-agent paths that do
    # NOT match the framework's bare workspace patterns are unambiguous
    # all-layout evidence (bare-pattern matches such as qwenpaw's
    # ``skills/x/SKILL.md`` would split like an agent prefix but are regular
    # single-agent content).
    bare_patterns = probe.resolved_patterns()
    other_agents: set[str] = set()
    has_bare = False
    for p in remote_paths:
        agent, _ = probe.split_all_path(p)
        if probe.matches(p, bare_patterns):
            has_bare = True
        elif agent not in (None, DEFAULT_AGENT_NAME):
            other_agents.add(agent)
    if other_agents:
        found = (['default'] if has_bare else []) + sorted(other_agents)
        return None, (f"repository has no agent named '{requested}' "
                      f"(agents in repo: {', '.join(found)}).")
    return identity, None


def cmd_download(
    framework: str,
    repo: str,
    name: str | None = None,
    target: str | None = None,
    local_dir=None,
    dry_run: bool = False,
    *,
    endpoint: str | None = None,
    token: str | None = None,
    username: str | None = None,
) -> int:
    """Download remote agent files to local.

    Token is optional for public repos.  However, when *repo* does not
    contain ``/`` we need *username* to derive the group, which requires
    authentication.
    """
    if not repo:
        return _fail(
            '--repo is required for download (the remote repository name)')
    err = check_framework(framework)
    if err:
        return _fail(err)

    if not endpoint:
        return _fail('not logged in. Provide endpoint.')

    # Token is optional for download (public repos don't require auth).
    # But if --repo doesn't contain '/', we need username to derive group.
    if '/' not in repo and not token:
        return _fail(f"--repo '{repo}' requires login to resolve owner. "
                     f"Use 'owner/name' format or run 'ms login' first.")
    if not token:
        token = ''
    if not username:
        username = ''

    group, repo_n = resolve_remote(
        repo=repo,
        name=name,
        framework=framework,
        username=username,
    )

    display.header('Download', f'{group}/{repo_n}', target or framework)

    client = AgentApi(endpoint=endpoint, token=token)
    # When no conversion is requested we can pull incrementally: list the remote
    # tree (with sha256), skip downloading files whose content already matches
    # the local copy, and later mirror-delete local files the remote dropped.
    # Conversion needs the full remote payload, so it stays full-download.
    incremental = (target or framework) == framework
    remote_all_paths: set[str] | None = None
    requested = name or DEFAULT_AGENT_NAME
    try:
        info = client.repo_info(group, repo_n)
        if info is None:
            return _fail(f'repository {group}/{repo_n} not found.')
        if incremental:
            from ._sync import sha256_content
            remote_detail = client.list_repo_files_detail(group, repo_n)
            if not remote_detail:
                return _fail(f'repository {group}/{repo_n} has no files.')
            # Restrict an all-layout repo to the requested agent's files
            # (prefix stripped); identity mapping for single-agent repos.
            remote_map, map_err = _remote_paths_for_agent(
                framework, requested, [f.path for f in remote_detail],
                local_dir)
            if map_err:
                return _fail(map_err)
            excluded = sorted({f.path
                               for f in remote_detail} - set(remote_map))
            if excluded:
                display.file_list(
                    'Excluded',
                    excluded,
                    color=display.COLOR_SKIP,
                    marker='[skip]',
                    note=f"belongs to other agents (requested '{requested}')")
            remote_detail = [f for f in remote_detail if f.path in remote_map]
            remote_all_paths = {remote_map[f.path] for f in remote_detail}
            # Local baseline for sha comparison (raw bytes -> sha256).
            probe_spec = build_spec(framework, name or DEFAULT_AGENT_NAME,
                                    local_dir)
            local_bytes = probe_spec.collect_bytes()
            local_sha = {k: sha256_content(v) for k, v in local_bytes.items()}
            # Split remote files into unchanged (skip) and to-download.
            skipped_same: list[str] = []
            to_download = []
            for f in remote_detail:
                rel = remote_map[f.path]
                if rel in local_sha and local_sha[rel] == f.sha256:
                    skipped_same.append(rel)
                else:
                    to_download.append(f)
            if skipped_same:
                display.file_list(
                    'Unchanged',
                    skipped_same,
                    color=display.COLOR_SKIP,
                    marker='[skip]',
                    note='sha256 matches local')
            resources = {}
            total = len(to_download)
            for i, f in enumerate(to_download, 1):
                print(f'  [{i}/{total}] downloading {f.path}', flush=True)
                resources[remote_map[f.path]] = _download_file(
                    client, group, repo_n, f.path)
        else:
            paths = client.list_repo_files(group, repo_n)
            if not paths:
                return _fail(f'repository {group}/{repo_n} has no files.')
            remote_map, map_err = _remote_paths_for_agent(
                framework, requested, paths, local_dir)
            if map_err:
                return _fail(map_err)
            excluded = sorted(set(paths) - set(remote_map))
            if excluded:
                display.file_list(
                    'Excluded',
                    excluded,
                    color=display.COLOR_SKIP,
                    marker='[skip]',
                    note=f"belongs to other agents (requested '{requested}')")
            paths = [p for p in paths if p in remote_map]
            resources = {}
            total = len(paths)
            for i, pth in enumerate(paths, 1):
                print(f'  [{i}/{total}] downloading {pth}', flush=True)
                resources[remote_map[pth]] = _download_file(
                    client, group, repo_n, pth)
    except APIError as e:
        return _fail(api_error_message(e, 'download'))
    except Exception as e:
        return _fail(f'download failed: {e}')

    # Optional format conversion.
    target_fw = target or framework
    err = check_framework(target_fw, 'target framework')
    if err:
        return _fail(err)

    local_name = name or DEFAULT_AGENT_NAME
    spec = build_spec(target_fw, local_name, local_dir)
    root = spec.workspace_root

    download_merges: list[tuple[str, str]] = []
    if target_fw != framework:
        if name == ALL_AGENT_NAME:
            # All-mode conversion only makes sense between two root-per-agent
            # frameworks (1:1 agent-directory mapping).  Other layouts (e.g.
            # file-per-agent qoder, single-agent) would collapse N agents into
            # a shared root, which is lossy and ambiguous -- reject explicitly.
            src_spec = build_spec(framework, local_name, local_dir)
            if not (src_spec.is_root_per_agent and spec.is_root_per_agent):
                return _fail(
                    'cross-framework conversion with --name all is only supported '
                    'between root-per-agent frameworks (e.g. qwenpaw <-> openclaw). '
                    'For other layouts, convert one agent at a time: '
                    '-n <agent> --target-framework <fw>.')
            resources = convert_resources(
                resources,
                framework,
                target_fw,
                all_mode=True,
                src_spec=src_spec,
                dst_spec=spec,
                collect_merges=download_merges,
                # Same policy as cmd_convert: never invent target default
                # templates the user did not have -- download+convert and
                # local convert must produce identical file sets.
                fill_missing_defaults=False,
            )
        else:
            existing_files = set(spec.collect().keys())
            download_skips: list[str] = []
            resources = convert_resources(
                resources,
                framework,
                target_fw,
                existing_files=existing_files,
                src_spec=build_spec(framework, local_name, local_dir),
                dst_spec=spec,
                collect_merges=download_merges,
                collect_skips=download_skips,
                fill_missing_defaults=False)
            display.file_list(
                'Skipped',
                download_skips,
                color=display.COLOR_SKIP,
                marker='[skip]',
                note='skill already exists on target, not overwritten',
            )

    patterns = spec.resolved_patterns()
    filtered = {
        k: v
        for k, v in resources.items() if spec.matches(k, patterns)
    }
    dropped = sorted(set(resources.keys()) - set(filtered.keys()))

    # In incremental mode an empty ``filtered`` just means every remote file is
    # already present locally with matching content -- not an error. Mirror
    # deletion may still need to run below. In full mode an empty match is a
    # real failure (nothing usable was downloaded).
    if not filtered and remote_all_paths is None:
        return _fail(
            'no downloaded files match the local workspace spec patterns.')

    if target_fw != framework:
        display.map_table(
            'Merged',
            download_merges,
            color=display.COLOR_MERGED,
            headers=('SOURCE', 'FOLDED INTO'),
            note=
            f'no {target_fw} equivalent; content preserved in the target file',
        )
    display.file_list(
        'Dropped',
        dropped,
        color=display.COLOR_DROPPED,
        marker='[drop]',
        note=f'not part of the {target_fw} workspace spec',
    )
    display.file_list(
        'Changed', filtered, color=display.COLOR_WRITTEN, root=root)

    if dry_run:
        print('\n[dry-run] nothing written.')
        return 0

    # Back up whatever is on disk before overwriting it. Download is the most
    # frequently used overwrite path, so it needs the same restore point that
    # convert / restore / watch --pull already create; without it a download
    # over a locally edited workspace was unrecoverable. The label follows the
    # shared ``{fw}_{name}_{date}_{time}`` convention (all-scope: ``{fw}_...``)
    # that ``backups -f <fw>`` parses, so this safety copy stays visible under
    # the framework filter.
    from ._sync import backup_local
    if spec.collect():
        backup_label = (
            target_fw if local_name == ALL_AGENT_NAME else
            f'{target_fw}_{local_name}')
        display.meta('backup', backup_local(spec, backup_label))

    written = spec.apply(filtered)
    display.done(f'Wrote {len(written)} file(s) under {root}')
    if target_fw == 'openhuman' and written:
        _print_openhuman_next_steps(root)

    # Download is overwrite/add-only and never deletes local files. The remote
    # holds only the user's customized content (unchanged framework defaults are
    # never uploaded), so a local file absent from the remote is normally a
    # default template -- or a not-yet-uploaded local file -- NOT a deletion.
    # Mirror-deleting here would wipe the framework's default scaffolding, so we
    # deliberately leave local-only files in place.
    return 0


def _file_per_agent_identity_path(dst_spec: WorkspaceSpec) -> str | None:
    """Resolve the per-agent identity file for a file-per-agent target.

    File-per-agent frameworks (e.g. qoder) declare a ``{name}`` placeholder
    pattern such as ``agents/{name}.md``.  Format it with the destination
    agent name so converted persona content can be routed into that file.
    Returns ``None`` when the layout has no single ``{name}`` file pattern.
    """
    if dst_spec.product_name == 'qoder':
        return None
    name = dst_spec.agent_name or DEFAULT_AGENT_NAME
    for pattern in dst_spec.patterns:
        # Only single-file placeholders (no wildcard) identify the persona file;
        # skip glob patterns like ``skills/{name}/*`` if any exist.
        if '{name}' in pattern and '*' not in pattern:
            return pattern.format(name=name)
    return None


def _collect_binary_passthrough(
    src_spec: WorkspaceSpec,
    text_resources: dict,
    source_fw: str,
    target_fw: str,
    dst_spec: WorkspaceSpec,
) -> dict:
    """Binary skill assets (PDFs/images/...) that the text ``collect()`` drops.

    They are pass-through (never merged): map 1:1 across single-agent
    frameworks (identical ``skills/`` paths); all-mode re-prefixes per agent.
    Only files valid for the target spec are kept.
    """
    raw = {
        k: v
        for k, v in src_spec.collect_bytes().items() if k not in text_resources
    }
    if not raw:
        return {}
    if source_fw == target_fw:
        out = raw
    elif src_spec._is_all() or dst_spec._is_all():
        out = {}
        for path, content in raw.items():
            agent, bare = src_spec.split_all_path(path)
            if agent is None:
                continue
            out[dst_spec.join_all_path(agent, bare)] = content
    else:
        out = raw
    dst_patterns = dst_spec.resolved_patterns()
    return {k: v for k, v in out.items() if dst_spec.matches(k, dst_patterns)}


def convert_workspace(
    src_spec: WorkspaceSpec,
    source_fw: str,
    target_fw: str,
    dst_spec: WorkspaceSpec,
    dry_run: bool = False,
) -> int:
    """Shared convert logic: merge -> filter defaults -> backup -> write.

    Returns 0 on success, 1 on failure.
    """
    src_root = src_spec.workspace_root
    resources = src_spec.collect()
    if not resources:
        return _fail(f'no {source_fw} files found under {src_root}.')

    # Full source text set captured BEFORE dropping unchanged defaults. The
    # binary passthrough below subtracts this so only genuinely-binary assets
    # (never seen by text collect) pass through -- text files we intentionally
    # drop as unchanged defaults must NOT sneak back in as "binary".
    source_text_paths = set(resources)

    # Carry only files the user actually modified from the source framework
    # default. Files byte-identical to the source default template are
    # boilerplate (no user content); dropping them means conversion yields real
    # content only, and no target scaffolding is created for them either.
    if source_fw != target_fw:
        from ._sync import drop_unchanged_defaults
        resources = drop_unchanged_defaults(resources, source_fw, src_spec)
        if not resources:
            return _fail(
                f'no user-modified {source_fw} files under {src_root} '
                f'(all files match the framework default templates).')

    existing = dst_spec.collect()
    existing_paths = set(existing.keys())

    # (src, dst) pairs for files folded into a catch-all (no standalone target
    # equivalent). Surfaced as a "Merged" hint so they are not seen as lost.
    merge_pairs: list[tuple[str, str]] = []

    if source_fw == target_fw:
        converted = resources
        default_paths: set = set()
        skipped_skills: list = []
    elif src_spec._is_all() or dst_spec._is_all():
        # All-mode conversion only makes sense between two root-per-agent
        # frameworks (1:1 agent-directory mapping).  Other layouts (e.g.
        # file-per-agent qoder, single-agent nanobot) would collapse N agents
        # into a shared root, which is lossy and ambiguous -- reject explicitly
        # (mirrors the guard in cmd_download's all-mode branch).
        if not (src_spec.is_root_per_agent and dst_spec.is_root_per_agent):
            return _fail(
                'cross-framework conversion with --name all is only supported '
                'between root-per-agent frameworks (e.g. qwenpaw <-> openclaw). '
                'For other layouts, convert one agent at a time: '
                '--from-name <agent> --target-framework <fw>.')
        converted = convert_resources(
            resources,
            source_fw,
            target_fw,
            all_mode=True,
            src_spec=src_spec,
            dst_spec=dst_spec,
            fill_missing_defaults=False,
            collect_merges=merge_pairs,
        )
        default_paths = set()
        skipped_skills = []
    else:
        # File-per-agent targets (e.g. qoder ``agents/{name}.md``) keep
        # per-agent identity in a dedicated sub-agent file; route overflow
        # (persona content with no shared mapping) there instead of the
        # shared catch-all so it does not pollute other sub-agents.
        # Symmetrically, a file-per-agent SOURCE's persona file is flagged so
        # it folds into the target's persona file instead of being dropped.
        overflow_target = None
        if any('{name}' in p for p in dst_spec.patterns):
            overflow_target = _file_per_agent_identity_path(dst_spec)
        result = merge_resources(
            incoming=resources,
            source_product=source_fw,
            target_product=target_fw,
            source_defaults=get_defaults(source_fw),
            target_defaults=get_defaults(target_fw),
            overflow_target=overflow_target,
            identity_source=_file_per_agent_identity_path(src_spec),
            fill_missing_defaults=False,
            existing_skills=_existing_skill_names(existing_paths),
        )
        default_paths = {
            a.path
            for a in result.actions if a.action == 'default'
        }
        merge_pairs = merged_away_pairs(result)
        skipped_skills = sorted(
            a.path for a in result.actions
            if a.action == 'skip' and 'already exists' in a.detail)
        converted = result.merged_files

    dst_root = dst_spec.workspace_root
    # Drop files that don't belong to the target framework's workspace spec.
    # merge_resources imports unmapped files (e.g. qwenpaw agent.json/skill.json)
    # as-is; without this filter they would leak into the target framework.
    # Mirrors the dst-spec guard in cmd_download's download path.
    dropped: list[str] = []
    if source_fw != target_fw:
        dst_patterns = dst_spec.resolved_patterns()
        dropped = sorted(
            k for k in converted if not dst_spec.matches(k, dst_patterns))
        converted = {
            k: v
            for k, v in converted.items() if dst_spec.matches(k, dst_patterns)
        }
    # Non-default files: always write (overwrite if exists).
    # Default files: write only if target does NOT already have them.
    effective = {
        k: v
        for k, v in converted.items()
        if k not in default_paths or k not in existing_paths
    }
    # Carry binary skill assets the text collect() skipped (verbatim).
    effective.update(
        _collect_binary_passthrough(src_spec, source_text_paths, source_fw,
                                    target_fw, dst_spec))
    skipped_defaults = sorted(default_paths & existing_paths)
    added_defaults = sorted(default_paths - existing_paths)

    # ---- Render ----
    display.header(
        'Convert',
        f'{source_fw}/{src_spec.agent_name}',
        f'{target_fw}/{dst_spec.agent_name}',
    )
    display.meta('source', src_root)
    display.meta('target', dst_root)
    counts = [('in', len(resources), 'bold'),
              ('written', len(effective), display.COLOR_WRITTEN)]
    if merge_pairs:
        counts.append(('merged', len(merge_pairs), display.COLOR_MERGED))
    if dropped:
        counts.append(('dropped', len(dropped), display.COLOR_DROPPED))
    display.summary(counts)

    display.file_list('Written', effective, color=display.COLOR_WRITTEN)
    display.map_table(
        'Merged',
        merge_pairs,
        color=display.COLOR_MERGED,
        headers=('SOURCE', 'FOLDED INTO'),
        note=f'no {target_fw} equivalent; content preserved in the target file',
    )
    display.file_list(
        'Dropped',
        dropped,
        color=display.COLOR_DROPPED,
        marker='[drop]',
        note=f'not part of the {target_fw} workspace spec',
    )
    display.file_list(
        'Skipped',
        skipped_skills,
        color=display.COLOR_SKIP,
        marker='[skip]',
        note='skill already exists on target, not overwritten',
    )
    if skipped_defaults:
        display.meta(
            'kept', f'{len(skipped_defaults)} existing default(s): '
            f"{', '.join(skipped_defaults)}")
    if added_defaults:
        display.meta(
            'added', f'{len(added_defaults)} default template(s): '
            f"{', '.join(added_defaults)}")

    if dry_run:
        print('\n[dry-run] nothing written.')
        return 0

    if not effective:
        print('\nNo effective files to write.')
        return 0

    # Backup existing target files before overwriting
    from ._sync import backup_local
    if existing:
        backup_path = backup_local(dst_spec,
                                   f'{target_fw}_{dst_spec.agent_name}')
        display.meta('backup', backup_path)

    written = dst_spec.apply(effective)
    display.done(f'Wrote {len(written)} file(s) under {dst_root}')
    if target_fw == 'openhuman':
        _print_openhuman_next_steps(dst_root)
    return 0


def cmd_convert(
    source_fw: str,
    target_fw: str,
    from_name: str | None = None,
    target_name: str | None = None,
    local_dir=None,
    out_dir=None,
    dry_run: bool = False,
) -> int:
    """Local-only format conversion: read a workspace, convert, write it out."""
    for fw, label in ((source_fw, '--from-framework'), (target_fw,
                                                        '--target-framework')):
        err = check_framework(fw, f'framework for {label}')
        if err:
            return _fail(err)

    if from_name:
        src_name = from_name
    else:
        # An omitted --from-name asks the framework which agent it should
        # convert: frameworks with an "active" sub-agent notion (openhuman's
        # activeProfileId) return it, everything else returns ``default``.
        src_name = build_spec(source_fw, DEFAULT_AGENT_NAME,
                              local_dir).resolve_default_agent_name()
    dst_name = target_name or src_name
    src_spec = build_spec(source_fw, src_name, local_dir)
    dst_spec = build_spec(target_fw, dst_name, out_dir)
    # Single-agent target frameworks (e.g. nanobot, openhuman) have no
    # sub-agent slots:
    # ``workspace_root`` ignores ``dst_name`` entirely, so every convert writes
    # to the same shared root. Warn the user that a non-default --target-name is
    # meaningless here and that this convert may overwrite an earlier one's
    # output landing at the same paths.
    dst_is_file_per_agent = any('{name}' in p for p in dst_spec.patterns)
    dst_is_single_agent = not dst_spec.is_root_per_agent and not dst_is_file_per_agent
    if (dst_is_single_agent and dst_name
            not in (DEFAULT_AGENT_NAME, GLOBAL_AGENT_NAME, ALL_AGENT_NAME)):
        print(
            f"Warning: '{target_fw}' is a single-agent framework with no sub-agent "
            f"slots; --target-name '{dst_name}' is ignored and content is written to "
            f'the shared root ({dst_spec.workspace_root}). This may overwrite output '
            f'from a previous convert into the same framework.',
            file=sys.stderr,
        )
    return convert_workspace(
        src_spec, source_fw, target_fw, dst_spec, dry_run=dry_run)


def cmd_watch(
    framework: str,
    name: str | None = None,
    local_dir=None,
    repo: str | None = None,
    pull: bool = False,
    *,
    endpoint: str | None = None,
    token: str | None = None,
    username: str | None = None,
) -> int:
    """Start background bidirectional sync for agent files."""
    from ._cache import pid_file
    from ._watcher import daemonize, watch_loop

    err = check_framework(framework)
    if err:
        return _fail(err)

    if name:
        local_name, err = resolve_local_name(name, framework, local_dir)
        if err:
            return _fail(err)
    else:
        local_name = ALL_AGENT_NAME

    if not endpoint or not token:
        return _fail('not logged in. Provide endpoint and token.')
    if not username:
        return _fail('missing username.')

    # Ensure no stale watch processes are running.
    pf = pid_file()
    from ._watcher import stop_daemon
    stop_daemon()

    spec = build_spec(framework, local_name, local_dir)
    client = AgentApi(endpoint=endpoint, token=token)

    # Guard: file-per-agent frameworks with a specific agent name.
    if (not spec.supports_individual_watch and local_name
            not in (GLOBAL_AGENT_NAME, ALL_AGENT_NAME, DEFAULT_AGENT_NAME)):
        return _fail(
            f"'{framework}' has shared files across sub-agents; "
            f'watch only supports global/default mode to avoid sync conflicts. '
            f'Use upload/download -n {local_name} for individual sub-agent operations.'
        )

    # Resolve remote target.
    effective_name = name if name else None
    group, repo_n = resolve_remote(
        repo=repo,
        name=effective_name,
        framework=framework,
        username=username,
    )

    # Guard: check remote repo framework matches local.
    try:
        info = client.repo_info(group, repo_n)
        if info:
            remote_fw = info.get('Framework', '')
            if remote_fw and remote_fw != framework:
                return _fail(
                    f'framework mismatch: local={framework}, remote={remote_fw}. '
                    f'Use convert or download --target for cross-framework sync.'
                )
    except APIError as e:
        if e.status_code in (403, 401):
            return _fail(api_error_message(e, 'watch'))
        elif e.status_code == 404:
            pass  # repo not found — first push will create it
        else:
            return _fail(
                f'failed to get repository info (HTTP {e.status_code}: {e.message})'
            )
    except Exception as e:
        return _fail(f'failed to get repository info: {e}')

    interval = 60
    push_only = not pull
    print(f'Starting sync for {group}/{repo_n} (interval={interval}s)...')
    print(f'  Framework: {framework}')
    print(f'  Root: {spec.workspace_root}')
    if push_only:
        print(
            '  Mode: push-only (local -> remote, will NOT pull remote changes)'
        )
    else:
        print(
            '  Mode: bidirectional (local <-> remote, WILL pull remote changes)'
        )
    print(f'  Stop: ms agent stop')

    daemonize(
        watch_loop,
        spec,
        client,
        group,
        repo_n,
        framework,
        interval,
        push_only=push_only)
    from ._cache import log_file
    print(f'  Watch started (PID file: {pf}).')
    print(f'  Log: {log_file()}')
    return 0


def cmd_stop() -> int:
    """Stop the background watch process."""
    from ._watcher import stop_daemon

    stopped = stop_daemon()
    if stopped:
        print('Watch process stopped.')
    else:
        print('No watch process running.')
    return 0


_BACKUP_WRAPPER = 'agent/'


def _strip_backup_wrapper(filename: str) -> str:
    """Strip the legacy ``agent/`` wrapper dir from a backup zip entry.

    Older backups stored files under an ``agent/`` prefix; new backups don't.
    Stripping keeps restore aligned with the workspace-relative layout used by
    ``collect``/``apply`` regardless of which format the zip uses.
    """
    if filename.startswith(_BACKUP_WRAPPER):
        return filename[len(_BACKUP_WRAPPER):]
    return filename


def _parse_backup_meta(stem: str) -> tuple[str, str]:
    """Parse a backup filename stem into ``(framework, name)``.

    Filenames look like ``{fw}{delim}{name}_{date}_{time}``; the leading
    ``{fw}{delim}{name}`` prefix is split on ``_`` (watch backups) or ``-``
    (upload backups).

    The framework is anchored on REGISTERED framework names first (longest
    match): ``ms-agent`` contains the ``-`` delimiter itself, so a naive
    split would yield ``('ms', 'agent-default')`` and break ``backups -f
    ms-agent`` filtering / restore lookup (BUG-032). Unregistered prefixes
    keep the legacy split as a fallback.
    """
    parts = stem.rsplit('_', 2)
    prefix = parts[0] if len(parts) >= 3 else stem
    for fw in sorted(FRAMEWORK_REGISTRY, key=len, reverse=True):
        if prefix == fw:
            return fw, ''  # all-scope backup: framework only
        if prefix.startswith(fw + '_') or prefix.startswith(fw + '-'):
            return fw, prefix[len(fw) + 1:]
    delim = '_' if '_' in prefix else '-'
    fw, _, nm = prefix.partition(delim)
    return fw, nm


def _filter_backups(backups, fw_filter, name_filter):
    """Filter backup files by framework/name parsed from their filenames."""
    if not (fw_filter or name_filter):
        return backups
    out = []
    for f in backups:
        fw, nm = _parse_backup_meta(f.stem)
        if fw_filter and fw != fw_filter:
            continue
        if name_filter and nm != name_filter:
            continue
        out.append(f)
    return out


def cmd_recover(
    target: str | None = None,
    framework: str | None = None,
    name: str | None = None,
    local_dir=None,
    list_backups: bool = False,
) -> int:
    """Restore agent files from a backup zip."""
    import datetime as _dt

    from ._cache import cache_dir

    cdir = cache_dir()

    backups = sorted(
        (f for f in cdir.iterdir() if f.suffix == '.zip' and f.is_file()),
        key=lambda f: f.stat().st_mtime,
    )

    # --list mode
    if list_backups:
        backups = _filter_backups(backups, framework, name)

        if not backups:
            print('No backups found.')
            return 0
        print(f'Backups in {cdir}:\n')
        last = backups[-1]
        for f in backups:
            mtime = _dt.datetime.fromtimestamp(f.stat().st_mtime)
            marker = '  [LAST]' if f == last else ''
            print(f'  {f.name}  ({mtime:%Y-%m-%d %H:%M:%S}){marker}')
        print(f'\n{len(backups)} backup(s) total.')
        return 0

    # Restore mode
    if not target:
        return _fail(
            "specify a target: 'last' or a backup filename. Use --list to see available backups."
        )

    backups = _filter_backups(backups, framework, name)

    if target == 'last':
        if not backups:
            return _fail('no backups found.')
        zip_path = backups[-1]
    else:
        fname = target if target.endswith('.zip') else f'{target}.zip'
        zip_path = cdir / fname
        if not zip_path.exists():
            zip_path = Path(target)
        if not zip_path.exists():
            return _fail(f'backup not found: {fname} (looked in {cdir})')

    if framework:
        err = check_framework(framework)
        if err:
            return _fail(err)

    # Reject a corrupt / non-zip archive up front -- BEFORE the pre-restore
    # backup and the delete-extra-files pass below touch the workspace, so a
    # truncated or mislabeled backup fails cleanly (consistent _fail output,
    # no half-done restore, no raw traceback).
    if not zipfile.is_zipfile(zip_path):
        return _fail(
            f"restore failed: '{zip_path.name}' is not a valid backup "
            f'archive (corrupt or not a zip file).')

    # Parse (framework, name) from the zip filename once, honoring both the
    # ``-`` (upload) and ``_`` (watch) delimiters, and fill in whatever the
    # caller left unspecified.  Reusing _parse_backup_meta keeps this aligned
    # with the --list/restore filtering above.
    parsed_fw, parsed_name = _parse_backup_meta(zip_path.stem)
    if not framework:
        if parsed_fw in FRAMEWORK_REGISTRY:
            framework = parsed_fw
        else:
            return _fail(
                'cannot infer framework. Pass --framework explicitly.')

    # Determine the restore SCOPE (which agent directory the backup belongs to).
    # An all-scope backup is named ``{fw}_{date}_{time}`` (no name segment), so
    # ``parsed_name`` is empty -> restore into the all-root.  A single-agent
    # backup is ``{fw}{delim}{name}_...`` -> restore into that agent only.
    # A hardcoded "all" here would lift root-per-agent frameworks to the shared
    # workspaces/ parent and, because a single-agent zip stores bare (unprefixed)
    # paths, wrongly treat every sibling agent's files as "extra" and delete them.
    restore_name = name or parsed_name or ALL_AGENT_NAME

    spec = build_spec(framework, restore_name, local_dir)
    root = spec.workspace_root

    # Backup current local files. The label must follow the shared backup
    # naming convention ``{fw}_{name}_{date}_{time}`` (all-scope: ``{fw}_...``)
    # used by convert and watch -- ``backups -f <fw>`` parses the framework
    # from the filename, so an unprefixed name would make this safety backup
    # invisible under the framework filter (and unusable to undo a restore).
    from ._sync import backup_local
    current_resources = spec.collect()
    if current_resources:
        backup_label = (
            framework if restore_name == ALL_AGENT_NAME else
            f'{framework}_{restore_name}')
        pre_restore_backup = backup_local(spec, backup_label)
        print(f'Pre-restore backup: {pre_restore_backup.name}')
    else:
        print('No existing files to backup.')

    # Determine which files are in the zip (strip legacy wrapper prefix).
    # Restore takes the SAME inbound rules as download: a zip can come from
    # anywhere (--from-backup accepts arbitrary paths), so entries outside
    # the workspace spec patterns (executable scripts, hidden credential
    # files...) are rejected instead of written verbatim into the workspace.
    spec_patterns = spec.resolved_patterns()
    with zipfile.ZipFile(zip_path, 'r') as zf:
        all_entries = {
            _strip_backup_wrapper(info.filename)
            for info in zf.infolist() if not info.is_dir()
        }
    zip_entries = {
        rel
        for rel in all_entries if spec.matches(rel, spec_patterns)
    }
    skipped_spec = sorted(all_entries - zip_entries)
    for rel in skipped_spec:
        print(f'  Skipped (not in {framework} workspace spec): {rel}')

    # Delete local files not in the zip
    deleted = 0
    for rel in sorted(current_resources.keys()):
        if rel not in zip_entries:
            target_file = root / rel
            if target_file.exists():
                target_file.unlink()
                print(f'  Removed: {rel}')
                deleted += 1

    # Extract zip
    resolved_root = root.resolve()
    print(f'Restoring {zip_path.name} -> {resolved_root}')
    restored = 0
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = _strip_backup_wrapper(info.filename)
            if rel not in zip_entries:
                continue  # outside the workspace spec (already reported)
            file_target = (resolved_root / rel).resolve()
            if not file_target.is_relative_to(resolved_root):
                print(f'  Skipped (path traversal): {info.filename}')
                continue
            file_target.parent.mkdir(parents=True, exist_ok=True)
            # Same inbound sanitize download uses: a foreign zip's config may
            # carry plaintext keys -- never write them to disk unscrubbed.
            file_target.write_bytes(
                spec.sanitize_inbound_file(rel, zf.read(info.filename)))
            print(f'  Restored: {rel}')
            restored += 1

    print(f'\nRestored {restored} file(s), removed {deleted} extra file(s).')
    return 0


# Aliases: cmd_restore = cmd_recover, cmd_backups extracted from list_backups mode.


def cmd_restore(
    target: str | None = None,
    framework: str | None = None,
    name: str | None = None,
    local_dir=None,
) -> int:
    """Restore agent files from a backup zip (alias for cmd_recover without list mode)."""
    return cmd_recover(
        target=target,
        framework=framework,
        name=name,
        local_dir=local_dir,
        list_backups=False)


def cmd_backups(
    framework: str | None = None,
    name: str | None = None,
    local_dir=None,
) -> int:
    """List available backups."""
    return cmd_recover(
        target=None,
        framework=framework,
        name=name,
        local_dir=local_dir,
        list_backups=True)


def cmd_list(
    owner: str | None = None,
    page_number: int = 1,
    page_size: int = 10,
    *,
    endpoint: str | None = None,
    token: str | None = None,
) -> int:
    """List remote agent repositories."""
    if not endpoint:
        return _fail('not logged in. Provide endpoint.')
    if not token:
        token = ''

    client = AgentApi(endpoint=endpoint, token=token)
    try:
        result = client.list_agents(
            owner=owner, page_number=page_number, page_size=page_size)
    except APIError as e:
        return _fail(api_error_message(e, 'list'))
    except Exception as e:
        return _fail(f'list failed: {e}')

    items = result.get('items') or []
    total = result.get('total_count', len(items))

    if not items:
        print('(no agent repositories found)')
        return 0

    headers = ['repo_id', 'framework', 'visibility', 'updated']
    rows = []
    for item in items:
        owner_name = item.get('Path') or item.get('path') or ''
        repo_name = item.get('Name') or item.get('name') or ''
        repo_id = f'{owner_name}/{repo_name}' if owner_name else repo_name
        fw = item.get('Framework') or item.get('framework') or '-'
        vis = agent_visibility_label(item)
        updated = agent_last_modified(item)
        if isinstance(updated, str) and 'T' in updated:
            updated = updated.split('T')[0]
        rows.append((repo_id, fw, vis, updated))

    from ._format import tabulate
    print(tabulate(rows, headers))

    print(f'\npage {page_number} / total {total} (page_size={page_size})')
    return 0
