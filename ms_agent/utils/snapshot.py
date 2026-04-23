# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Lightweight snapshot utility for ms-agent output directories.

Uses a dedicated git repo stored at <output_dir>/.ms_agent_snapshots/
so it never touches or conflicts with the user's own .git directory.

All git commands are run with GIT_DIR and GIT_WORK_TREE explicitly set,
so the snapshot repo is fully isolated from any surrounding repository.
"""
import os
import json
import subprocess
from typing import Optional

from ms_agent.utils.logger import get_logger

logger = get_logger()

_SNAPSHOT_DIR_NAME = '.ms_agent_snapshots'
_META_FILE = 'snapshot_meta.json'


def _git(args: list[str], work_tree: str, git_dir: str,
         check: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env['GIT_DIR'] = git_dir
    env['GIT_WORK_TREE'] = work_tree
    # Suppress interactive prompts
    env['GIT_TERMINAL_PROMPT'] = '0'
    return subprocess.run(
        ['git'] + args,
        env=env,
        cwd=work_tree,
        capture_output=True,
        text=True,
        check=check,
    )


def _snapshot_git_dir(output_dir: str) -> str:
    return os.path.join(output_dir, _SNAPSHOT_DIR_NAME)


def _ensure_repo(output_dir: str) -> str:
    """Initialize the snapshot repo if it doesn't exist. Returns git_dir."""
    git_dir = _snapshot_git_dir(output_dir)
    if not os.path.isdir(git_dir):
        os.makedirs(git_dir, exist_ok=True)
        # Use non-bare init with explicit GIT_DIR — no --bare so work tree is supported.
        # Do NOT pass a path argument; GIT_DIR env var points git at our custom dir.
        _git(['init'], work_tree=output_dir, git_dir=git_dir)
        _git(['config', 'user.email', 'ms-agent@snapshot'],
             work_tree=output_dir, git_dir=git_dir)
        _git(['config', 'user.name', 'ms-agent'],
             work_tree=output_dir, git_dir=git_dir)
        # Exclude the snapshot dir itself from tracking
        info_dir = os.path.join(git_dir, 'info')
        os.makedirs(info_dir, exist_ok=True)
        exclude_file = os.path.join(info_dir, 'exclude')
        with open(exclude_file, 'a', encoding='utf-8') as f:
            f.write(f'\n{_SNAPSHOT_DIR_NAME}/\n')
    return git_dir


def _meta_path(output_dir: str) -> str:
    return os.path.join(_snapshot_git_dir(output_dir), _META_FILE)


def _load_meta(output_dir: str) -> dict:
    path = _meta_path(output_dir)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_meta(output_dir: str, meta: dict) -> None:
    path = _meta_path(output_dir)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2)


def take_snapshot(output_dir: str, message: str,
                  message_count: int = 0) -> Optional[str]:
    """
    Stage all changes in output_dir and create a snapshot commit.

    Args:
        output_dir: The directory to snapshot.
        message: Commit message (truncated to 120 chars).
        message_count: Number of messages in history at snapshot time.
                       Stored in metadata so rollback can truncate history.

    Returns the short commit hash on success, or None if nothing to commit
    or if git is unavailable.
    """
    if not output_dir or not os.path.isdir(output_dir):
        return None

    try:
        git_dir = _ensure_repo(output_dir)

        # Stage everything (excluding .ms_agent_snapshots via info/exclude)
        _git(['add', '-A'], work_tree=output_dir, git_dir=git_dir)

        # Check if there's anything to commit
        status = _git(['status', '--porcelain'],
                      work_tree=output_dir, git_dir=git_dir)
        if not status.stdout.strip():
            return None  # Nothing changed

        # Truncate message to keep commit subject readable
        subject = message.strip().replace('\n', ' ')[:120]
        result = _git(['commit', '-m', subject],
                      work_tree=output_dir, git_dir=git_dir)

        commit_hash = None
        for line in result.stdout.splitlines():
            if line.startswith('['):
                before_bracket = line.split(']')[0]
                commit_hash = before_bracket.split()[-1]
                break
        if commit_hash is None:
            commit_hash = 'ok'

        # Persist message_count so rollback can truncate history
        meta = _load_meta(output_dir)
        meta[commit_hash] = {'message_count': message_count}
        _save_meta(output_dir, meta)

        return commit_hash

    except FileNotFoundError:
        logger.warning_once(
            '[snapshot] git not found — snapshots disabled.')
        return None
    except subprocess.CalledProcessError as e:
        logger.warning(f'[snapshot] git error: {e.stderr.strip()}')
        return None
    except Exception as e:
        logger.warning(f'[snapshot] unexpected error: {e}')
        return None


def list_snapshots(output_dir: str) -> list[dict]:
    """
    Return a list of snapshots as dicts with keys: hash, message, date, message_count.
    Most recent first.
    """
    git_dir = _snapshot_git_dir(output_dir)
    if not os.path.isdir(git_dir):
        return []
    try:
        result = _git(
            ['log', '--pretty=format:%h\t%ai\t%s'],
            work_tree=output_dir,
            git_dir=git_dir,
            check=False,
        )
        if result.returncode != 0:
            return []
        meta = _load_meta(output_dir)
        snapshots = []
        for line in result.stdout.splitlines():
            parts = line.split('\t', 2)
            if len(parts) == 3:
                h = parts[0]
                snapshots.append({
                    'hash': h,
                    'date': parts[1],
                    'message': parts[2],
                    'message_count': meta.get(h, {}).get('message_count', 0),
                })
        return snapshots
    except Exception:
        return []


def restore_snapshot(output_dir: str,
                     commit_hash: str) -> tuple[bool, int]:
    """
    Restore output_dir to the state at commit_hash.

    Returns (success, message_count) where message_count is the number of
    messages in history at snapshot time (0 if unknown).
    """
    git_dir = _snapshot_git_dir(output_dir)
    if not os.path.isdir(git_dir):
        logger.warning('[snapshot] No snapshot repo found.')
        return False, 0
    try:
        _git(['checkout', commit_hash, '--', '.'],
             work_tree=output_dir, git_dir=git_dir)
        logger.info(f'[snapshot] Restored to {commit_hash}')
        meta = _load_meta(output_dir)
        message_count = meta.get(commit_hash, {}).get('message_count', 0)
        return True, message_count
    except subprocess.CalledProcessError as e:
        logger.warning(f'[snapshot] restore failed: {e.stderr.strip()}')
        return False, 0
