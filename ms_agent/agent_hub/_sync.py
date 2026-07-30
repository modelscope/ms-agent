# Copyright (c) ModelScope Contributors. All rights reserved.
"""Core sync logic: backup, zip, bidirectional sync helpers."""
from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ms_agent.utils.logger import get_logger
from ._cache import cache_dir
from ._defaults import get_defaults

if TYPE_CHECKING:
    from modelscope_hub.agent import AgentApi, RemoteFileInfo

__all__ = [
    'zip_resources',
    'backup_local',
    'sha256_content',
    'detect_local_changes',
    'sanitize_outbound',
    'push_resources',
    'push_incremental',
    'push_mirror',
    'pull_incremental',
]

logger = get_logger()


def zip_resources(resources: dict[str, str | bytes],
                  wrapper: str = '') -> bytes:
    """Pack resources into a deterministic in-memory zip for local backup.

    Entries are stored with workspace-relative paths (no wrapper directory) so
    that :func:`restore <ms_agent.agent_hub.cmd_restore>` can extract them
    back to the exact locations reported by ``collect``/``apply``.  A non-empty
    *wrapper* prefixes every entry (kept only for backward compatibility).

    Used by :func:`backup_local` to create timestamped backups before
    destructive operations (pull, convert, restore).
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel, value in sorted(resources.items()):
            key = f'{wrapper}/{rel}' if wrapper else rel
            zf.writestr(key, value)
    return buf.getvalue()


def backup_local(spec, name: str) -> Path:
    """Zip all local agent files into a timestamped backup in the cache dir.

    Returns the path to the created zip file.
    """
    resources: dict[str, bytes] = spec.collect_bytes()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    zip_path = cache_dir() / f'{name}_{timestamp}.zip'
    zip_path.write_bytes(zip_resources(resources))
    return zip_path


def sanitize_outbound(resources: dict, spec) -> dict:
    """Strip machine-local secrets from local files before they are pushed.

    Symmetric to the per-file inbound sanitize hook: applies
    ``spec.sanitize_outbound_file`` to every collected file so secrets a user
    left in a local config (e.g. hermes ``config.yaml``, openhuman
    ``config.toml``, qwenpaw ``agent.json``) are never uploaded to the remote
    repo -- and therefore never written into its git history.

    Accepts and returns the same ``{rel_path: bytes}`` mapping
    ``collect_bytes`` produces (``str`` values are encoded as UTF-8, matching
    the push path which uploads bytes).
    """
    out: dict = {}
    for rel, content in resources.items():
        raw = content if isinstance(content,
                                    bytes) else content.encode('utf-8')
        out[rel] = spec.sanitize_outbound_file(rel, raw)
    return out


def drop_unchanged_defaults(resources: dict, framework: str, spec) -> dict:
    """Drop files byte-identical to the framework's default template.

    These carry no user content, so upload, convert AND watch all treat them as
    "not the user's own data": they are never pushed, and for watch pull they
    are not counted when mirror-deleting local files -- so the framework's
    default scaffolding is neither uploaded nor wiped. One shared definition of
    "the user-customized subset of a workspace" for every sync path.

    Handles both text (``collect``) and byte (``collect_bytes``) resources.
    Skills are already filtered by the spec's collect hook and are absent from
    the default-template set, so they are never dropped here.
    """
    defaults = get_defaults(framework)
    if not defaults:
        return resources
    is_all = spec._is_all()
    out: dict = {}
    for path, content in resources.items():
        bare = spec.split_all_path(path)[1] if is_all else path
        default = defaults.get(bare)
        if default is not None:
            default_val = default.encode('utf-8') if isinstance(
                content, bytes) else default
            if content == default_val:
                continue
        out[path] = content
    return out


# ---- Bidirectional sync helpers ----


def sha256_content(content: str | bytes) -> str:
    """Compute sha256 of content (accepts str or bytes)."""
    if isinstance(content, str):
        content = content.encode('utf-8')
    return hashlib.sha256(content).hexdigest()


def detect_local_changes(
    local_resources: dict[str, bytes],
    baseline_sha256: dict[str, str],
) -> dict[str, bytes | None]:
    """Compare local files against the sync baseline sha256 map.

    Returns a dict of files that differ:
      - key present with bytes value: content changed or file is new locally
      - key present with None value: file was deleted locally
    """
    changed: dict[str, bytes | None] = {}
    for rel, content in local_resources.items():
        local_sha = sha256_content(content)
        if baseline_sha256.get(rel) != local_sha:
            changed[rel] = content
    for rel in baseline_sha256:
        if rel not in local_resources:
            changed[rel] = None
    return changed


def _retry_on_master_missing(fn, *, retries: int = 6, delay: float = 1.0):
    """Run *fn*, retrying the create-then-commit race.

    A freshly created repo may not have its ``master`` branch ready when the
    first commit fires, yielding a 400 "branch or revision master not found".
    Wrapping any commit-bearing call (normal commit *and* LFS upload) means
    every first-push path gets the same protection.
    """
    import time
    from modelscope_hub.errors import APIError

    for attempt in range(retries):
        try:
            return fn()
        except APIError as e:
            msg = (getattr(e, 'message', '') or str(e)).lower()
            branch_missing = e.status_code == 400 and ('branch' in msg
                                                       or 'revision' in msg)
            if branch_missing and attempt < retries - 1:
                # Exponential backoff (1, 2, 4, 8, 16s capped -> ~31s total) to
                # outlast slow server-side master-branch initialization on a
                # freshly created bare repo.
                time.sleep(min(delay * (2**attempt), 16.0))
                continue
            raise


def push_resources(
    client: 'AgentApi',
    username: str,
    name: str,
    framework: str,
    resources: dict[str, bytes],
    prune_patterns: list[str] | None = None,
    visibility: str = 'public',
) -> None:
    """Full upload via commit interface (normal + LFS).

    Creates the repo if needed, then commits all files in batches.
    Raises on failure (caller should NOT update baseline on exception).

    Full upload has *mirror* semantics: after create/update, remote files that
    belong to this upload's scope but are absent from *resources* are deleted,
    so a re-used repo does not accumulate stale files across uploads. The
    delete scope is constrained by *prune_patterns* (workspace-relative globs,
    typically ``spec.resolved_patterns()``): only remote paths matching them
    are eligible for deletion, so a single-agent upload never touches other
    sub-agents' files. When *prune_patterns* is ``None`` pruning is skipped
    (backward-compatible create/update-only behavior).
    """
    from modelscope_hub.agent import is_lfs_file

    if not resources:
        logger.warning('push_resources called with empty resources; skipping.')
        return

    # Ensure repo exists (idempotent create).
    try:
        if not client.check_repo(username, name):
            client.create_repo(
                username, name, framework=framework, visibility=visibility)
            logger.info('Created empty agent repo %s/%s (framework=%s, %s).',
                        username, name, framework, visibility)
    except Exception as exc:
        logger.warning('create_repo check failed (%s), proceeding anyway.',
                       exc)

    # Idempotent upsert: skip files whose content already matches the remote.
    # A repeated full upload of unchanged content would otherwise issue
    # zero-delta commits; for an unchanged LFS pointer the server rejects the
    # empty commit with ``commit failed: {"message":""}``.
    remote_sha: dict[str, str] = {}
    try:
        remote_sha = {
            f.path: f.sha256
            for f in client.list_repo_files_detail(username, name)
        }
    except Exception as exc:
        logger.debug(
            'Cannot list remote detail for idempotent skip (%s); uploading all.',
            exc,
        )

    # Split into normal and LFS files.
    normal_actions: list[dict] = []
    lfs_files: list[tuple[str, bytes]] = []
    skipped = 0

    for rel, content in sorted(resources.items()):
        size = len(content)
        if remote_sha.get(rel) == sha256_content(content):
            skipped += 1
            continue
        if is_lfs_file(rel, size):
            lfs_files.append((rel, content))
        else:
            b64 = base64.b64encode(content).decode('ascii')
            normal_actions.append({
                'action': 'create',
                'path': rel,
                'type': 'normal',
                'size': size,
                'sha256': '',
                'content': b64,
                'encoding': 'base64',
            })

    # Commit normal files in one request.
    if normal_actions:
        _retry_on_master_missing(lambda: client.commit_files(
            username,
            name,
            normal_actions,
            commit_message='sync: upload normal files'))
        for a in normal_actions:
            logger.info('  CREATE: %s (%d B)', a['path'], a['size'])

    # Upload LFS files one-by-one (batch verify + PUT + commit).  The commit
    # inside upload_lfs_file hits the same fresh-repo master race, so it needs
    # the retry too (LFS-only first push would otherwise fail).
    for rel, content in lfs_files:
        _retry_on_master_missing(
            lambda rel=rel, content=content: client.upload_lfs_file(
                username,
                name,
                rel,
                content,
                action='create',
                commit_message=f'sync: upload LFS {rel}'))
        logger.info('  CREATE (LFS): %s (%d B)', rel, len(content))

    logger.info('Pushed %d file(s) (%d normal, %d LFS, %d unchanged).',
                len(normal_actions) + len(lfs_files), len(normal_actions),
                len(lfs_files), skipped)

    # Mirror semantics: prune remote files that fall within this upload's
    # scope but are no longer present locally.
    if prune_patterns:
        import fnmatch
        try:
            remote_paths = set(client.list_repo_files(username, name))
        except Exception as exc:
            logger.warning('Cannot list remote for prune (%s); skip prune.',
                           exc)
            remote_paths = set()
        local_paths = set(resources.keys())
        stale = [
            rp for rp in sorted(remote_paths - local_paths) if any(
                fnmatch.fnmatch(rp, pat) for pat in prune_patterns)
        ]
        for fpath in stale:
            logger.info('  DELETE (prune): %s', fpath)
            try:
                client.delete_file(username, name, fpath)
            except Exception as exc:
                logger.warning('  prune delete failed for %s (%s)', fpath, exc)
        if stale:
            logger.info('Pruned %d stale remote file(s).', len(stale))


def push_incremental(
    client: 'AgentApi',
    username: str,
    name: str,
    changed: dict[str, bytes | None],
    remote_paths: set,
    remote_lfs_paths: set | None = None,
) -> None:
    """Incremental push via commit interface.

    Builds create/update/delete actions and commits.  LFS files are
    uploaded via the LFS batch+PUT flow before committing their reference.
    """
    from modelscope_hub.agent import is_lfs_file

    normal_actions: list[dict] = []
    lfs_items: list[tuple[str, bytes,
                          str]] = []  # (path, content, action_type)
    delete_paths: list[str] = []

    for fpath, content in changed.items():
        if content is None:
            delete_paths.append(fpath)
        else:
            action_type = 'update' if fpath in remote_paths else 'create'
            size = len(content)
            # Determine if the file needs LFS: check remote flag or local heuristic.
            use_lfs = False
            if remote_lfs_paths and fpath in remote_lfs_paths:
                use_lfs = True
            elif is_lfs_file(fpath, size):
                use_lfs = True

            if use_lfs:
                lfs_items.append((fpath, content, action_type))
            else:
                b64 = base64.b64encode(content).decode('ascii')
                normal_actions.append({
                    'action': action_type,
                    'path': fpath,
                    'type': 'normal',
                    'size': size,
                    'sha256': '',
                    'content': b64,
                    'encoding': 'base64',
                })

    # Commit normal file actions in one batch.  The commit hits the same
    # fresh-repo master race as push_resources (create_repo is async, so master
    # may not be ready when the first commit fires), hence the same retry.
    if normal_actions:
        for a in normal_actions:
            logger.info('  %s: %s', a['action'].upper(), a['path'])
        _retry_on_master_missing(lambda: client.commit_files(
            username, name, normal_actions, commit_message='watch sync'))

    # Upload LFS files one-by-one (their commit races master too).
    for fpath, content, action_type in lfs_items:
        logger.info('  %s (LFS): %s', action_type.upper(), fpath)
        _retry_on_master_missing(
            lambda fpath=fpath, content=content, action_type=action_type:
            client.upload_lfs_file(
                username,
                name,
                fpath,
                content,
                action=action_type,
                commit_message='watch sync'))

    # Delete files via the DELETE endpoint.
    for fpath in delete_paths:
        logger.info('  DELETE: %s', fpath)
        client.delete_file(username, name, fpath)

    total = len(normal_actions) + len(lfs_items) + len(delete_paths)
    if total:
        logger.info('Committed %d action(s) incrementally.', total)


def pull_incremental(
    client: 'AgentApi',
    username: str,
    name: str,
    spec,
    remote_files: 'list[RemoteFileInfo]',
    local_resources: dict[str, bytes],
) -> int:
    """Incrementally pull remote changes to local workspace.

    Returns the number of files changed.
    """
    root: Path = spec.workspace_root
    resolved_root = root.resolve()
    remote_sha_map = {f.path: f.sha256 for f in remote_files}
    remote_paths = set(remote_sha_map.keys())
    local_paths = set(local_resources.keys())
    changes = 0

    for rfile in remote_files:
        target = (root / rfile.path).resolve()
        if not target.is_relative_to(resolved_root):
            logger.warning('  Skipped (path traversal): %s', rfile.path)
            continue
        local_content = local_resources.get(rfile.path)
        # Fast path: identical raw sha means the local file already matches the
        # remote (only possible when the inbound hook does not rewrite it), so
        # skip the download entirely.
        if local_content is not None and sha256_content(
                local_content) == rfile.sha256:
            continue
        content = client.download_repo_file(
            username, name, rfile.path, binary=True)
        # Every inbound write path funnels through the sanitize hook so secrets
        # (e.g. in QwenPaw agent.json) never reach disk regardless of sync mode.
        content = spec.sanitize_inbound_file(rfile.path, content)
        # Re-compare against the sanitized bytes: if the hook rewrote the file,
        # its raw sha differs from remote but may equal what is already on disk,
        # in which case there is nothing to write.
        if local_content is not None and sha256_content(
                local_content) == sha256_content(content):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        changes += 1
        action = 'UPDATE' if local_content is not None else 'CREATE'
        logger.info('  %s (pull): %s', action, rfile.path)

    for rel in sorted(local_paths - remote_paths):
        target = (root / rel).resolve()
        if not target.is_relative_to(resolved_root):
            continue
        if target.exists():
            target.unlink()
            changes += 1
            logger.info('  DELETE (pull): %s', rel)

    return changes


def push_mirror(
    client: 'AgentApi',
    username: str,
    name: str,
    framework: str,
    resources: dict[str, bytes],
    prune_patterns: list[str] | None = None,
    visibility: str = 'public',
) -> None:
    """Incremental mirror push (local -> remote) with sha256 diffing.

    Lists the remote tree (with per-file sha256), compares against *resources*,
    and only commits files that are new or whose content changed. Mirror
    semantics apply: remote files within *prune_patterns* scope that are absent
    locally are deleted. Falls back to a full :func:`push_resources` when the
    remote is empty / not yet created (first push).

    Unlike the inbound (download) path, no sanitization is applied here: local
    bytes are uploaded as-is and compared by raw sha256, matching the server's
    sha256 so unchanged files are skipped.
    """
    import fnmatch
    from modelscope_hub.errors import APIError

    if not resources:
        logger.warning('push_mirror called with empty resources; skipping.')
        return

    # Fetch remote baseline. A brand-new / missing repo surfaces as 400/404/500
    # (see watcher); treat all of those as an empty remote so we do a full push.
    try:
        remote_files = client.list_repo_files_detail(username, name)
    except APIError as e:
        if e.status_code in (400, 404, 500):
            remote_files = []
        else:
            raise
    except Exception:
        remote_files = []

    if not remote_files:
        logger.info('Remote empty/new; doing full push for %s/%s.', username,
                    name)
        push_resources(
            client,
            username,
            name,
            framework,
            resources,
            prune_patterns=prune_patterns,
            visibility=visibility)
        return

    remote_sha_map = {f.path: f.sha256 for f in remote_files}
    remote_paths = set(remote_sha_map.keys())
    remote_lfs_paths = {f.path for f in remote_files if f.is_lfs}
    local_paths = set(resources.keys())

    changed: dict[str, bytes | None] = {}
    # New or content-changed files -> create/update.
    for rel, content in resources.items():
        if rel not in remote_sha_map or sha256_content(
                content) != remote_sha_map[rel]:
            changed[rel] = content
    # Mirror delete: remote files in scope but absent locally -> delete.
    if prune_patterns:
        for rp in sorted(remote_paths - local_paths):
            if any(fnmatch.fnmatch(rp, pat) for pat in prune_patterns):
                changed[rp] = None

    if not changed:
        logger.info('Remote already up to date for %s/%s (no changes).',
                    username, name)
        return

    n_upsert = sum(1 for v in changed.values() if v is not None)
    n_delete = sum(1 for v in changed.values() if v is None)
    logger.info('Incremental push: %d upsert, %d delete for %s/%s.', n_upsert,
                n_delete, username, name)
    push_incremental(client, username, name, changed, remote_paths,
                     remote_lfs_paths)
