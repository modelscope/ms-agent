# Copyright (c) ModelScope Contributors. All rights reserved.
"""File watcher (polling) and daemon management for agent sync."""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from modelscope_hub.errors import APIError

from ms_agent.utils.logger import get_logger
from ._cache import (load_sync_state, log_file, pid_file, save_sync_state,
                     stop_file)
from ._sync import (backup_local, detect_local_changes,
                    drop_unchanged_defaults, pull_incremental,
                    push_incremental, push_resources, sanitize_outbound,
                    sha256_content)

__all__ = ['watch_loop', 'daemonize', 'stop_daemon']

_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    _logger = get_logger()
    _logger.setLevel(logging.INFO)
    fh = RotatingFileHandler(
        str(log_file()),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8')
    fh.setFormatter(
        logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
    _logger.addHandler(fh)
    return _logger


def watch_loop(spec,
               client,
               username: str,
               repo: str,
               framework: str,
               interval: int = 120,
               *,
               push_only: bool = True):
    """Sync loop: push local changes, optionally pull remote changes.

    Args:
        repo: Remote repository name (used as the API path component).
        push_only: True (default) = only pushes, never modifies local files.
                   False = full bidirectional sync (remote wins on conflict).
    """
    logger = _get_logger()

    # The daemon runs in a freshly exec'd interpreter, but watch_loop may also
    # be invoked directly (tests / foreground).  Rebuild the client so we always
    # start with a clean requests.Session connection pool.
    from modelscope_hub.agent import AgentApi
    client = AgentApi(
        endpoint=client.server, token=client.token, timeout=client.timeout)

    logger.info(
        'Watch started for %s/%s (root=%s, interval=%ds, push_only=%s)',
        username, repo, spec.workspace_root, interval, push_only)

    state = load_sync_state(repo)
    running = True
    stop_event = threading.Event()
    sf = stop_file()

    def _handle_term(signum, frame):
        nonlocal running
        running = False
        stop_event.set()

    if threading.current_thread() is threading.main_thread():
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, _handle_term)
        signal.signal(signal.SIGINT, _handle_term)

    sf.unlink(missing_ok=True)

    while running:
        elapsed = 0
        poll_interval = min(interval, 5)
        while elapsed < interval and running:
            stop_event.wait(timeout=poll_interval)
            if stop_event.is_set():
                running = False
                break
            if sf.exists():
                running = False
                break
            elapsed += poll_interval
        if not running:
            break

        # One poll iteration. Guard the whole body so any unexpected error
        # (network read timeout, connection reset, JSON/parse error, ...) is
        # logged WITH a traceback and the loop survives to retry next cycle --
        # instead of a single fragile call silently wedging the daemon or an
        # uncaught non-APIError killing the loop while the process lingers.
        try:
            _poll_once(client, username, repo, framework, spec, push_only,
                       state, logger)
        except Exception:
            logger.exception('Sync poll failed (will retry next cycle)')

    logger.info('Watch stopped (signal received).')
    pf = pid_file()
    if pf.exists():
        try:
            if pf.read_text(encoding='utf-8').strip() == str(os.getpid()):
                pf.unlink(missing_ok=True)
        except Exception:
            pass
    sf.unlink(missing_ok=True)


def _poll_once(client, username, repo, framework, spec, push_only, state,
               logger) -> None:
    """Run one sync poll: list remote, detect changes, sync, refresh baseline.

    Raised exceptions propagate to :func:`watch_loop`, which logs them with a
    traceback and keeps the daemon alive.  Only the *expected* empty-repo
    ``APIError`` states are handled inline; everything else is intentionally
    allowed to surface so a real failure is visible rather than silent.
    """
    # ---- Fetch remote file list ----
    try:
        remote_files = client.list_repo_files_detail(username, repo)
    except APIError as e:
        # A non-existent remote repo returns 400 (code 10025801016), and
        # 404/500 cover transient/unreadable states.  Treat all as an empty
        # baseline so the first push can create the repo instead of looping
        # forever (an empty-but-created repo returns 200 with a tree).
        if e.status_code in (400, 404, 500):
            remote_files = []
        else:
            logger.error('Failed to list remote files: %s', e)
            return

    # ---- Collect local resources & detect changes ----
    # Track only the user's customized files: unchanged framework defaults
    # are not synced (same rule as upload/convert), so they are neither
    # pushed nor counted when mirror-deleting local files on pull.
    # Sanitize first so a secret left in a local config is never pushed, and
    # never enters the sync baseline as pushable content (which would
    # otherwise re-push it every cycle).
    local_resources = drop_unchanged_defaults(
        sanitize_outbound(spec.collect_bytes(), spec), framework, spec)
    baseline = state.get('remote_files', {})
    # A remote file counts toward change detection if it was in our baseline
    # (so edits/deletions are seen) OR it is a workspace file the collect
    # patterns would pick up (so a file *added* on the remote gets pulled).
    # Incidental files the server auto-creates (README.md, .gitattributes)
    # and framework-bundled assets match neither, so they never trigger a
    # spurious pull.
    patterns = spec.resolved_patterns()
    remote_sha_map = {
        f.path: f.sha256
        for f in remote_files
        if f.path in baseline or (spec.matches(f.path, patterns)
                                  and not spec._is_excluded_asset(f.path))
    }

    remote_changed = (remote_sha_map != baseline)
    local_changed = bool(
        detect_local_changes(local_resources, state['remote_files']))
    logger.debug('poll: local=%d remote=%d remote_changed=%s local_changed=%s',
                 len(local_resources), len(remote_files), remote_changed,
                 local_changed)

    # ---- Sync decision ----
    did_sync = _sync_action(
        push_only,
        remote_changed,
        local_changed,
        client,
        username,
        repo,
        framework,
        spec,
        remote_files,
        local_resources,
        logger,
        state,
    )

    # ---- Update baseline on successful sync ----
    if did_sync:
        if not push_only:
            local_resources = drop_unchanged_defaults(
                sanitize_outbound(spec.collect_bytes(), spec), framework, spec)
        _refresh_baseline(local_resources, state)
        save_sync_state(repo, state['remote_files'])


def _push_local(client,
                username,
                name,
                framework,
                local_resources,
                state,
                logger,
                *,
                remote_paths=None,
                remote_lfs_paths=None,
                prune_patterns=None) -> bool:
    """Push local changes: full upload on first time, incremental thereafter."""
    if not local_resources:
        logger.debug('No local resources to push -- skipping.')
        return False
    if not state.get('remote_files'):
        push_resources(
            client,
            username,
            name,
            framework,
            local_resources,
            prune_patterns=prune_patterns)
        logger.info('Pushed local changes (full upload -- first time).')
        return True
    else:
        changed = detect_local_changes(local_resources, state['remote_files'])
        if changed:
            # Filter stale DELETEs: only delete files that actually exist on
            # the remote.  The baseline may be stale if the remote was
            # modified outside watch (e.g. via upload or manual deletion).
            if remote_paths is not None:
                stale = {
                    p
                    for p, c in changed.items()
                    if c is None and p not in remote_paths
                }
                for p in sorted(stale):
                    logger.warning(
                        '  SKIP DELETE: %s (not on remote, stale baseline)', p)
                    del changed[p]
            if not changed:
                logger.info(
                    'No real changes to push after filtering stale deletes.')
                return False
            # Use actual remote paths (not stale baseline) for CREATE vs UPDATE.
            actual = remote_paths if remote_paths is not None else set(
                state['remote_files'].keys())
            push_incremental(
                client,
                username,
                name,
                changed,
                actual,
                remote_lfs_paths=remote_lfs_paths)
            logger.info('Pushed local changes (incremental commit).')
            return True
        return False


def _sync_action(
    push_only,
    remote_changed,
    local_changed,
    client,
    username,
    name,
    framework,
    spec,
    remote_files,
    local_resources,
    logger,
    state,
) -> bool:
    """Execute the appropriate sync action. Returns True if something changed."""
    # Backup naming convention: {framework}_{agent_name} so that
    # ``cmd_recover --framework`` can filter watch-created backups.
    backup_label = f'{framework}_{spec.agent_name}'
    remote_paths = {f.path for f in remote_files}
    remote_lfs_paths = {
        f.path
        for f in remote_files if getattr(f, 'is_lfs', False)
    }

    if push_only:
        if not local_changed:
            return False
        return _push_local(
            client,
            username,
            name,
            framework,
            local_resources,
            state,
            logger,
            remote_paths=remote_paths,
            remote_lfs_paths=remote_lfs_paths,
            prune_patterns=spec.resolved_patterns())

    if remote_changed and local_changed:
        backup_path = backup_local(spec, backup_label)
        pull_incremental(client, username, name, spec, remote_files,
                         local_resources)
        logger.warning('Conflict: remote wins. Local backup: %s', backup_path)
    elif remote_changed:
        backup_path = backup_local(spec, backup_label)
        pull_incremental(client, username, name, spec, remote_files,
                         local_resources)
        logger.info('Pulled remote changes (backup: %s).', backup_path)
    elif local_changed:
        _push_local(
            client,
            username,
            name,
            framework,
            local_resources,
            state,
            logger,
            remote_paths=remote_paths,
            remote_lfs_paths=remote_lfs_paths,
            prune_patterns=spec.resolved_patterns())
    else:
        return False
    return True


def _refresh_baseline(local_resources: dict, state: dict) -> None:
    """Update the sha256 sync baseline in-place after a successful sync.

    A successful sync leaves the remote and local in agreement on the managed
    scope, so the baseline is simply the sha256 of the current local files.
    Deriving it locally avoids re-listing the remote tree -- whose listing can
    be momentarily inconsistent right after a commit -- and keeps change
    detection purely sha256-based.
    """
    state['remote_files'] = {
        rel: sha256_content(content)
        for rel, content in local_resources.items()
    }


def daemonize(target, *args, **kwargs):
    """Launch the watch loop as a fresh background process (fork + exec).

    Spawns a brand-new Python interpreter running the ``_daemon`` entry point
    on ALL platforms.  Using exec (rather than a bare ``os.fork()``) guarantees
    the daemon starts from a clean process image.  This is essential on macOS,
    where calling into system frameworks (e.g. ``_scproxy`` /
    ``SystemConfiguration`` for proxy detection during an HTTPS request) inside
    a fork-without-exec child crashes with SIGSEGV.  It also avoids stale file
    descriptors inherited from the parent's connection pool.
    """
    import json
    import tempfile

    spec_obj = args[0] if len(args) > 0 else None
    client_obj = args[1] if len(args) > 1 else None
    local_dir = getattr(spec_obj, '_local_dir', None) if spec_obj else None
    payload = {
        'username': args[2] if len(args) > 2 else kwargs.get('username', ''),
        'repo': args[3] if len(args) > 3 else kwargs.get('repo', ''),
        'framework': args[4] if len(args) > 4 else kwargs.get('framework', ''),
        'interval': args[5] if len(args) > 5 else kwargs.get('interval', 120),
        'push_only': kwargs.get('push_only', True),
        'local_name': getattr(spec_obj, 'agent_name', '') if spec_obj else '',
        'local_dir': str(local_dir) if local_dir else '',
        'server': getattr(client_obj, 'server', '') if client_obj else '',
        'token': getattr(client_obj, 'token', '') if client_obj else '',
    }
    fd, param_path = tempfile.mkstemp(suffix='.json', prefix='ms_agent_watch_')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)

    cmd = [
        sys.executable, '-m', 'ms_agent.agent_hub._watcher', '_daemon',
        param_path
    ]
    pf = pid_file()

    if hasattr(os, 'fork'):
        # Unix: detach into a new session (setsid equivalent) and redirect the
        # daemon's stdio to the log file so tracebacks are never lost.
        lf = log_file()
        lf.parent.mkdir(parents=True, exist_ok=True)
        log_fd = os.open(
            str(lf), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            proc = subprocess.Popen(
                cmd,
                start_new_session=True,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=log_fd,
                stderr=log_fd,
            )
        finally:
            os.close(log_fd)
    else:
        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008
        proc = subprocess.Popen(
            cmd,
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )

    pf.write_text(str(proc.pid), encoding='utf-8')


# Process-discovery pattern for OUR daemon only.  ``daemonize`` starts the
# daemon as ``<python> -m ms_agent.agent_hub._watcher _daemon <params.json>``,
# so this exact argv marker uniquely identifies it.  Broad substrings like
# ``'agent watch'`` must NEVER be used here: they match any unrelated process
# whose command line happens to contain the text (a user's script, an editor
# session...) and ``stop_daemon`` would SIGTERM it (BUG-014) -- while never
# matching the real daemon, whose argv contains no such text.
_DEFAULT_WATCH_PATTERNS = [
    'ms_agent.agent_hub._watcher _daemon',
]


def stop_daemon(extra_patterns: list[str] | None = None) -> bool:
    """Stop ALL running watch daemon processes (cross-platform).

    Primary mechanism: write a stop-file that the watch loop polls.
    Secondary: send SIGTERM (Unix) or taskkill (Windows) as a backup.
    """
    stopped = False
    pf = pid_file()
    sf = stop_file()

    sf.write_text('stop', encoding='utf-8')

    tracked_pid = None
    if pf.exists():
        try:
            tracked_pid = int(pf.read_text(encoding='utf-8').strip())
            # A pid file can go stale (daemon died, OS reused the pid for an
            # unrelated process) -- verify the process identity before
            # signalling it.  If it is not our daemon, never signal it: the
            # stop-file above is the primary mechanism anyway, so skipping
            # the signal can at worst delay a real daemon's exit, while a
            # wrong SIGTERM would kill a user's unrelated process.
            if not _pid_is_watch_daemon(tracked_pid):
                tracked_pid = None
            else:
                if hasattr(os, 'fork'):
                    os.kill(tracked_pid, signal.SIGTERM)
                stopped = True
        except (ValueError, OSError, ProcessLookupError):
            tracked_pid = None

    if hasattr(os, 'fork'):
        my_pid = os.getpid()
        for found_pid in _find_watch_pids(extra_patterns):
            if found_pid in (my_pid, tracked_pid):
                continue
            try:
                os.kill(found_pid, signal.SIGTERM)
                stopped = True
            except (ProcessLookupError, PermissionError):
                pass
    else:
        for found_pid in _find_watch_pids_windows(extra_patterns):
            if found_pid == tracked_pid:
                continue
            _terminate_pid_windows(found_pid)
            stopped = True

    if stopped or tracked_pid:
        _wait_for_exit(tracked_pid, timeout=8)

    if tracked_pid and _is_alive(tracked_pid):
        _force_kill(tracked_pid)

    pf.unlink(missing_ok=True)
    sf.unlink(missing_ok=True)

    return stopped or tracked_pid is not None


def _pid_is_watch_daemon(pid: int) -> bool:
    """Return True only if *pid*'s command line is OUR watch daemon.

    Guards every signal sent to a pid-file pid: pids get recycled by the OS,
    so an unverified kill could hit an unrelated user process. Any lookup
    failure returns False (fail-safe: the stop-file still makes a real
    daemon exit on its next poll).
    """
    marker = _DEFAULT_WATCH_PATTERNS[0]
    try:
        if hasattr(os, 'fork'):
            result = subprocess.run(
                ['ps', '-p', str(pid), '-o', 'command='],
                capture_output=True,
                text=True,
                timeout=5)
        else:
            result = subprocess.run(
                [
                    'wmic', 'process', 'where', f'processid={int(pid)}', 'get',
                    'commandline'
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        return result.returncode == 0 and marker in result.stdout
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def _find_watch_pids(extra_patterns: list[str] | None = None) -> list[int]:
    """Find PIDs of running watch daemon processes via pgrep (Unix only)."""
    patterns = list(
        dict.fromkeys(_DEFAULT_WATCH_PATTERNS + (extra_patterns or [])))
    pids: set = set()
    for pattern in patterns:
        try:
            result = subprocess.run(
                ['pgrep', '-f', '--', pattern],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for p in result.stdout.strip().split('\n'):
                    if p.strip().isdigit():
                        pids.add(int(p.strip()))
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    return list(pids)


def _find_watch_pids_windows(
        extra_patterns: list[str] | None = None) -> list[int]:
    """Find PIDs of running watch daemon processes on Windows via wmic."""
    patterns = list(
        dict.fromkeys(_DEFAULT_WATCH_PATTERNS + (extra_patterns or [])))
    pids: set = set()
    try:
        result = subprocess.run(
            [
                'wmic', 'process', 'where', "name like '%python%'", 'get',
                'processid,commandline'
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        for line in result.stdout.splitlines():
            line_lower = line.lower()
            for pattern in patterns:
                if pattern.lower() in line_lower:
                    parts = line.strip().split()
                    if parts and parts[-1].isdigit():
                        pids.add(int(parts[-1]))
                    break
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return list(pids)


def _terminate_pid_windows(pid: int) -> None:
    """Terminate a process on Windows using taskkill."""
    try:
        subprocess.run(
            ['taskkill', '/PID', str(pid), '/F'],
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _is_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _wait_for_exit(pid: int | None, timeout: int = 8) -> None:
    """Wait up to *timeout* seconds for a process to exit."""
    if pid is None:
        time.sleep(2)
        return
    for _i in range(timeout * 2):
        if not _is_alive(pid):
            return
        time.sleep(0.5)


def _force_kill(pid: int) -> None:
    """Force-kill a process (SIGKILL on Unix, taskkill /F on Windows)."""
    if hasattr(os, 'fork'):
        try:
            os.kill(pid, getattr(signal, 'SIGKILL', signal.SIGTERM))
        except (ProcessLookupError, PermissionError, OSError):
            pass
    else:
        _terminate_pid_windows(pid)


# ---------------------------------------------------------------------------
# Windows daemon entry point
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    import json

    if len(sys.argv) >= 3 and sys.argv[1] == '_daemon':
        param_path = sys.argv[2]
        with open(param_path, 'r', encoding='utf-8') as _f:
            _params = json.load(_f)
        os.unlink(param_path)

        from modelscope_hub.agent import AgentApi

        from . import frameworks as _  # noqa: F401 — trigger registration
        from ._workspace import FRAMEWORK_REGISTRY

        _fw = _params['framework']
        _spec_cls = FRAMEWORK_REGISTRY[_fw]
        _spec = _spec_cls(
            agent_name=_params.get('local_name', 'all'),
            local_dir=_params.get('local_dir') or None)
        _client = AgentApi(endpoint=_params['server'], token=_params['token'])

        _pf = pid_file()
        _pf.write_text(str(os.getpid()), encoding='utf-8')

        watch_loop(
            _spec,
            _client,
            username=_params['username'],
            repo=_params['repo'],
            framework=_fw,
            interval=_params.get('interval', 120),
            push_only=_params.get('push_only', True),
        )
