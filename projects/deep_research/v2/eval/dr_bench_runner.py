"""
DeepResearch Bench (dr_bench) batch runner for ms-agent deep research v2.

Goal:
- Read DeepResearch Bench queries from a JSONL file.
- For each item, run ms-agent CLI with v2 config to produce a report.
- Extract the final report markdown and dump outputs to dr_bench raw jsonl format:
    {"id": "...", "prompt": "...", "article": "..."}

Why this exists:
- dr_bench evaluation expects a raw_data/<model>.jsonl file with per-task "article".
- We want per-task isolated workdirs (resume-friendly) and minimal wiring.

Notes:
- This runner relies on ms-agent Config.parse_args() behavior:
  unknown CLI args like `--output_dir` will override YAML config fields.
"""

from __future__ import annotations
import argparse
import os
import subprocess
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import json

try:
    # Auto-load environment variables from a nearby `.env` (if present).
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(), override=False)
except Exception:  # pragma: no cover
    pass

try:
    import select  # Unix-only; dr_bench_runner is used on mac/linux
except Exception:  # pragma: no cover
    select = None  # type: ignore


def _read_jsonl(path: str) -> List[Dict]:
    items: List[Dict] = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def _append_jsonl(path: str,
                  obj: Dict,
                  *,
                  lock: Optional[threading.Lock] = None) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    if lock is None:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(obj, ensure_ascii=False) + '\n')
        return
    with lock:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(obj, ensure_ascii=False) + '\n')


def _load_existing_ids(output_jsonl: str) -> Set[str]:
    if not os.path.exists(output_jsonl):
        return set()
    ids: Set[str] = set()
    with open(output_jsonl, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                _id = str(obj.get('id', '')).strip()
                if _id:
                    ids.add(_id)
            except Exception:
                continue
    return ids


def _find_report_md(workdir: str) -> Optional[str]:
    """
    Heuristic report locator:
    - v2 reporter tool: <workdir>/reports/report.md
    - legacy workflows: <workdir>/report.md
    - fallback: <workdir>/reports/draft.md (if exists)
    """
    candidates = [
        os.path.join(workdir, 'final_report.md'),
        os.path.join(workdir, 'report.md'),
        # os.path.join(workdir, 'reports', 'report.md'),
        # os.path.join(workdir, 'reports', 'draft.md'),
    ]
    for p in candidates:
        if os.path.exists(p) and os.path.isfile(p):
            return p
    return None


def _is_direct_final_report_path(workdir: str, report_path: str) -> bool:
    """
    Only accept top-level final report files in `workdir`:
    - <workdir>/final_report.md
    - <workdir>/report.md

    We intentionally ignore files under <workdir>/reports/ (e.g. reports/report.md),
    because those are intermediate artifacts and the user explicitly asked to
    not backfill from the reports subdir.
    """
    try:
        wd = os.path.abspath(workdir)
        rp = os.path.abspath(report_path)
        if os.path.dirname(rp) != wd:
            return False
        base = os.path.basename(rp)
        return base in ('final_report.md', 'report.md')
    except Exception:
        return False


def _try_backfill_from_existing_workdir(
    task: Task,
    *,
    model_name: str,
    work_root: str,
    output_jsonl: str,
    write_lock: Optional[threading.Lock] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Try to backfill a missing jsonl entry from an existing workdir on disk.

    Returns:
        (backfilled, error)
    """
    workdir = os.path.join(work_root, model_name, task.task_id)
    if not os.path.exists(workdir) or not os.path.isdir(workdir):
        return False, None

    report_path = _find_report_md(workdir)
    if not report_path:
        return False, None
    if not _is_direct_final_report_path(workdir, report_path):
        return False, None

    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            article = f.read()
    except Exception as e:
        return False, f'failed to read report for backfill: {e} (path={report_path})'

    if not article.strip():
        return False, f'empty report content for backfill (path={report_path})'

    _append_jsonl(
        output_jsonl,
        {
            'id': task.task_id,
            'prompt': task.prompt,
            'article': article,
        },
        lock=write_lock,
    )
    return True, None


def _tail_text_from_file(path: str, *, max_chars: int = 20000) -> str:
    try:
        if not os.path.exists(path) or not os.path.isfile(path):
            return ''
        with open(path, 'rb') as f:
            try:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - max_chars), os.SEEK_SET)
            except Exception:
                # Fallback for non-seekable files (unlikely here)
                pass
            data = f.read()
        return data.decode('utf-8', errors='replace')
    except Exception:
        return ''


@dataclass(frozen=True)
class Task:
    task_id: str
    prompt: str


def _terminate_process(
    proc: subprocess.Popen,
    *,
    terminate_timeout_s: float = 5.0,
    kill_timeout_s: float = 2.0,
) -> None:
    """
    Best-effort terminate/kill a subprocess without raising.

    We intentionally keep this conservative: first SIGTERM, then SIGKILL if needed.
    """
    try:
        if proc.poll() is not None:
            return
    except Exception:
        # If poll fails, still try to terminate/kill.
        pass

    try:
        proc.terminate()
    except Exception:
        pass

    try:
        proc.wait(timeout=max(0.0, terminate_timeout_s))
        return
    except Exception:
        pass

    try:
        proc.kill()
    except Exception:
        pass

    try:
        proc.wait(timeout=max(0.0, kill_timeout_s))
    except Exception:
        pass


def _report_is_stable(
    report_path: str,
    *,
    stable_window_s: float,
    last_sig: Optional[Tuple[float, int]],
    stable_since: Optional[float],
    now_s: float,
) -> Tuple[bool, Optional[Tuple[float, int]], Optional[float]]:
    """
    Track whether a report file has been stable (mtime,size) for stable_window_s.
    Returns: (is_stable, new_last_sig, new_stable_since)
    """
    try:
        st = os.stat(report_path)
        if st.st_size <= 0:
            return False, last_sig, None
        sig = (float(st.st_mtime), int(st.st_size))
    except Exception:
        return False, last_sig, None

    if last_sig is None or sig != last_sig:
        return False, sig, None

    if stable_since is None:
        stable_since = now_s
        return False, sig, stable_since

    return (now_s - stable_since) >= max(0.0,
                                         stable_window_s), sig, stable_since


def _run_one_task(
    task: Task,
    *,
    model_name: str,
    config_path: str,
    work_root: str,
    ms_agent_repo_root: str,
    python_executable: str,
    trust_remote_code: bool,
    extra_args: List[str],
    stream_subprocess_output: bool,
    print_lock: Optional[threading.Lock] = None,
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Returns: (task_id, article, error)
    """
    workdir = os.path.join(work_root, model_name, task.task_id)
    os.makedirs(workdir, exist_ok=True)

    log_path = os.path.join(workdir, 'ms_agent.log')

    cmd = [
        python_executable,
        os.path.join(ms_agent_repo_root, 'ms_agent', 'cli', 'cli.py'),
        'run',
        '--config',
        config_path,
        '--query',
        task.prompt,
        '--trust_remote_code',
        'true' if trust_remote_code else 'false',
        '--output_dir',
        workdir,
    ]
    cmd.extend(extra_args or [])

    try:
        # Ensure logs flush promptly even if subprocess is buffered.
        env = dict(os.environ)
        env.setdefault('PYTHONUNBUFFERED', '1')

        # Safety net for rare "subprocess produced final_report.md but never exits".
        # This happens when the child Python process is stuck at shutdown (e.g. a
        # non-daemon thread blocked in I/O). If the final report is already stable
        # on disk, force-reap the child so the batch runner can continue.
        post_report_exit_grace_s = float(
            os.getenv('DR_BENCH_POST_REPORT_EXIT_GRACE_S', '15') or 15.0)
        report_stable_window_s = float(
            os.getenv('DR_BENCH_REPORT_STABLE_WINDOW_S', '2') or 2.0)
        poll_interval_s = float(
            os.getenv('DR_BENCH_SUBPROCESS_POLL_INTERVAL_S', '0.5') or 0.5)
        terminate_timeout_s = float(
            os.getenv('DR_BENCH_SUBPROCESS_TERMINATE_TIMEOUT_S', '5') or 5.0)
        kill_timeout_s = float(
            os.getenv('DR_BENCH_SUBPROCESS_KILL_TIMEOUT_S', '2') or 2.0)

        # We consider a task "already done" if it produced a top-level
        # final report file (final_report.md or report.md) with non-empty content.
        report_seen_stable_at: Optional[float] = None
        report_last_sig: Optional[Tuple[float, int]] = None
        report_stable_since: Optional[float] = None
        force_reaped = False

        if stream_subprocess_output:
            tail_lines: deque[str] = deque(maxlen=2000)
            with open(log_path, 'w', encoding='utf-8') as logf:
                proc = subprocess.Popen(
                    cmd,
                    cwd=ms_agent_repo_root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                )
                assert proc.stdout is not None
                # Avoid `for line in proc.stdout`: it blocks forever if the child
                # is hung but keeps stdout open. Use select+poll instead.
                while True:
                    now_s = time.time()

                    # If final report exists and is stable, start a grace timer.
                    report_path_hint = _find_report_md(workdir)
                    if report_path_hint and _is_direct_final_report_path(
                            workdir, report_path_hint):
                        stable, report_last_sig, report_stable_since = _report_is_stable(
                            report_path_hint,
                            stable_window_s=report_stable_window_s,
                            last_sig=report_last_sig,
                            stable_since=report_stable_since,
                            now_s=now_s,
                        )
                        if stable and report_seen_stable_at is None:
                            report_seen_stable_at = now_s
                        if (report_seen_stable_at is not None
                                and proc.poll() is None
                                and (now_s - report_seen_stable_at) >= max(
                                    0.0, post_report_exit_grace_s)):
                            _terminate_process(
                                proc,
                                terminate_timeout_s=terminate_timeout_s,
                                kill_timeout_s=kill_timeout_s,
                            )
                            force_reaped = True
                            break

                    # Drain available stdout without blocking.
                    if select is not None:
                        try:
                            r, _, _ = select.select([proc.stdout], [], [],
                                                    poll_interval_s)
                        except Exception:
                            r = []
                        if r:
                            try:
                                line = proc.stdout.readline()
                            except Exception:
                                line = ''
                            if line:
                                logf.write(line)
                                tail_lines.append(line)
                                if print_lock is None:
                                    print(f'[{task.task_id}] {line}', end='')
                                else:
                                    with print_lock:
                                        print(
                                            f'[{task.task_id}] {line}', end='')
                                continue
                    else:
                        # No select available; degrade to polling only.
                        time.sleep(max(0.0, poll_interval_s))

                    if proc.poll() is not None:
                        # Best-effort drain remainder to log
                        try:
                            rest = proc.stdout.read()
                            if rest:
                                logf.write(rest)
                                tail_lines.append(rest)
                        except Exception:
                            pass
                        break

                # Ensure a return code is available
                try:
                    returncode = proc.wait(timeout=1.0)
                except Exception:
                    returncode = proc.returncode if proc.returncode is not None else 0
                if force_reaped:
                    returncode = 0
            if returncode != 0:
                tail = ''.join(tail_lines)[-20000:]
                return task.task_id, None, (
                    f'ms-agent exited with code={returncode}. '
                    f'log={log_path}. output tail:\n{tail}')
        else:
            with open(log_path, 'w', encoding='utf-8') as logf:
                # Use Popen+poll so we can force-reap hung-at-exit children once
                # a stable final report is already on disk.
                proc2 = subprocess.Popen(
                    cmd,
                    cwd=ms_agent_repo_root,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                )
                while True:
                    now_s = time.time()

                    report_path_hint = _find_report_md(workdir)
                    if report_path_hint and _is_direct_final_report_path(
                            workdir, report_path_hint):
                        stable, report_last_sig, report_stable_since = _report_is_stable(
                            report_path_hint,
                            stable_window_s=report_stable_window_s,
                            last_sig=report_last_sig,
                            stable_since=report_stable_since,
                            now_s=now_s,
                        )
                        if stable and report_seen_stable_at is None:
                            report_seen_stable_at = now_s
                        if (report_seen_stable_at is not None
                                and proc2.poll() is None
                                and (now_s - report_seen_stable_at) >= max(
                                    0.0, post_report_exit_grace_s)):
                            _terminate_process(
                                proc2,
                                terminate_timeout_s=terminate_timeout_s,
                                kill_timeout_s=kill_timeout_s,
                            )
                            force_reaped = True
                            break

                    if proc2.poll() is not None:
                        break
                    time.sleep(max(0.0, poll_interval_s))

            returncode = proc2.returncode if proc2.returncode is not None else 0
            if force_reaped:
                returncode = 0
            if returncode != 0:
                tail = _tail_text_from_file(log_path, max_chars=20000)
                return task.task_id, None, (
                    f'ms-agent exited with code={returncode}. '
                    f'log={log_path}. output tail:\n{tail}')
    except Exception as e:
        return task.task_id, None, f'subprocess failed: {e}'

    report_path = _find_report_md(workdir)
    if not report_path:
        return task.task_id, None, (
            f'final_report.md not found in workdir={workdir}. '
            f'log={log_path}. ms-agent output tail:\n{_tail_text_from_file(log_path, max_chars=20000)}'
        )

    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            article = f.read()
    except Exception as e:
        return task.task_id, None, f'failed to read report: {e} (path={report_path})'

    if not article.strip():
        return task.task_id, None, (
            f'empty report content (path={report_path}). log={log_path}. '
            f'ms-agent output tail:\n{_tail_text_from_file(log_path, max_chars=20000)}'
        )

    return task.task_id, article, None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=
        'Run ms-agent v2 on dr_bench queries and dump raw_data jsonl.')
    parser.add_argument(
        '--query_file', required=True, help='Path to dr_bench query.jsonl')
    parser.add_argument(
        '--output_jsonl',
        required=True,
        help='Output path for dr_bench raw_data/<model>.jsonl')
    parser.add_argument(
        '--model_name',
        default='ms_deepresearch',
        help='Model/agent name used in output file naming')
    parser.add_argument(
        '--config',
        default='projects/deep_research/v2/researcher.yaml',
        help='ms-agent config path (v2 researcher.yaml by default)',
    )
    parser.add_argument(
        '--work_root',
        default='eval/dr_bench/results/runs',
        help=
        'Root dir to store per-task workdirs. Will create <work_root>/<model>/<id>/',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=0,
        help='Limit number of tasks (0 means all)')
    parser.add_argument(
        '--workers',
        type=int,
        default=1,
        help='Concurrency level (subprocess-based)')
    parser.add_argument(
        '--python',
        default=sys.executable,
        help=
        'Python executable to run ms-agent (defaults to current interpreter)',
    )
    parser.add_argument(
        '--trust_remote_code',
        action='store_true',
        help='Pass --trust_remote_code true to ms-agent')
    parser.add_argument(
        '--ms_agent_root',
        default='.',
        help=
        'Path to ms-agent repo root (contains ms_agent/). Defaults to current working directory.',
    )
    parser.add_argument(
        '--stream_subprocess_output',
        action='store_true',
        help=
        'Stream ms-agent stdout/stderr to console (also written to <workdir>/ms_agent.log).',
    )
    parser.add_argument(
        '--extra',
        nargs=argparse.REMAINDER,
        default=[],
        help=
        'Extra args passed through to ms-agent (e.g. --llm.model xxx --generation_config.stream false)',
    )
    args = parser.parse_args()

    ms_agent_root = os.path.abspath(args.ms_agent_root)
    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(ms_agent_root, config_path)

    query_file = args.query_file
    if not os.path.isabs(query_file):
        query_file = os.path.join(ms_agent_root, query_file)

    output_jsonl = args.output_jsonl
    if not os.path.isabs(output_jsonl):
        output_jsonl = os.path.join(ms_agent_root, output_jsonl)

    work_root = args.work_root
    if not os.path.isabs(work_root):
        work_root = os.path.join(ms_agent_root, work_root)

    items = _read_jsonl(query_file)
    tasks: List[Task] = []
    for item in items:
        task_id = str(item.get('id', '')).strip()
        # IMPORTANT: keep prompt EXACTLY as in query.jsonl.
        # Official evaluation scripts often use `prompt` as a join-key across files.
        prompt_raw = item.get('prompt', '')
        prompt = prompt_raw if isinstance(prompt_raw, str) else str(prompt_raw)
        if not task_id or not prompt:
            continue
        tasks.append(Task(task_id=task_id, prompt=prompt))

    if args.limit and args.limit > 0:
        tasks = tasks[:args.limit]

    done_ids = _load_existing_ids(output_jsonl)
    # Backfill: if a workdir already has a top-level final report file but the
    # jsonl doesn't have this id (e.g. previous run hung during process exit),
    # append it now and skip re-running the task.
    write_lock = threading.Lock()
    backfilled = 0
    for t in tasks:
        if t.task_id in done_ids:
            continue
        ok, err = _try_backfill_from_existing_workdir(
            t,
            model_name=args.model_name,
            work_root=work_root,
            output_jsonl=output_jsonl,
            write_lock=write_lock,
        )
        if err:
            print(f'[{t.task_id}] BACKFILL ERROR: {err}', file=sys.stderr)
            continue
        if ok:
            done_ids.add(t.task_id)
            backfilled += 1
            print(f'[{t.task_id}] BACKFILL OK')

    tasks = [t for t in tasks if t.task_id not in done_ids]

    if not tasks:
        msg = f'Nothing to do. output already contains all requested tasks: {output_jsonl}'
        if backfilled:
            msg += f' (backfilled={backfilled})'
        print(msg)
        return

    print(
        f'Will run {len(tasks)} tasks (workers={args.workers}). Output: {output_jsonl}'
    )
    os.makedirs(os.path.dirname(output_jsonl) or '.', exist_ok=True)

    # Ensure ms-agent is importable at runtime for subprocess (best-effort check)
    if not os.path.exists(os.path.join(ms_agent_root, 'ms_agent')):
        raise FileNotFoundError(
            f'ms_agent_root seems wrong: {ms_agent_root} (missing ms_agent/)')

    extra_args = args.extra or []
    print_lock = threading.Lock()

    if args.workers <= 1:
        for t in tasks:
            tid, article, err = _run_one_task(
                t,
                model_name=args.model_name,
                config_path=config_path,
                work_root=work_root,
                ms_agent_repo_root=ms_agent_root,
                python_executable=args.python,
                trust_remote_code=bool(args.trust_remote_code),
                extra_args=extra_args,
                stream_subprocess_output=bool(args.stream_subprocess_output),
                print_lock=print_lock,
            )
            if err:
                print(f'[{tid}] ERROR: {err}', file=sys.stderr)
                continue
            _append_jsonl(
                output_jsonl, {
                    'id': tid,
                    'prompt': t.prompt,
                    'article': article
                },
                lock=write_lock)
            print(f'[{tid}] OK')
        return

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        future_map = {
            ex.submit(
                _run_one_task,
                t,
                model_name=args.model_name,
                config_path=config_path,
                work_root=work_root,
                ms_agent_repo_root=ms_agent_root,
                python_executable=args.python,
                trust_remote_code=bool(args.trust_remote_code),
                extra_args=extra_args,
                stream_subprocess_output=bool(args.stream_subprocess_output),
                print_lock=print_lock,
            ): t
            for t in tasks
        }

        for fut in as_completed(future_map):
            t = future_map[fut]
            try:
                tid, article, err = fut.result()
            except Exception as e:
                print(
                    f'[{t.task_id}] ERROR: future failed: {e}',
                    file=sys.stderr)
                continue
            if err:
                print(f'[{tid}] ERROR: {err}', file=sys.stderr)
                continue
            _append_jsonl(
                output_jsonl, {
                    'id': tid,
                    'prompt': t.prompt,
                    'article': article
                },
                lock=write_lock)
            print(f'[{tid}] OK')


if __name__ == '__main__':
    main()
