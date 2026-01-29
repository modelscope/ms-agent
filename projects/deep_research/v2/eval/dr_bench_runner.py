"""
DeepResearch Bench (dr_bench) batch runner for ms-agent v2.

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
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import json


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
        os.path.join(workdir, 'reports', 'report.md'),
        os.path.join(workdir, 'reports', 'draft.md'),
    ]
    for p in candidates:
        if os.path.exists(p) and os.path.isfile(p):
            return p
    return None


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
                for line in proc.stdout:
                    logf.write(line)
                    tail_lines.append(line)
                    if print_lock is None:
                        print(f'[{task.task_id}] {line}', end='')
                    else:
                        with print_lock:
                            print(f'[{task.task_id}] {line}', end='')
                returncode = proc.wait()
            if returncode != 0:
                tail = ''.join(tail_lines)[-20000:]
                return task.task_id, None, (
                    f'ms-agent exited with code={returncode}. '
                    f'log={log_path}. output tail:\n{tail}')
        else:
            with open(log_path, 'w', encoding='utf-8') as logf:
                proc2 = subprocess.run(
                    cmd,
                    cwd=ms_agent_repo_root,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                    env=env,
                )
            if proc2.returncode != 0:
                tail = _tail_text_from_file(log_path, max_chars=20000)
                return task.task_id, None, (
                    f'ms-agent exited with code={proc2.returncode}. '
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
    tasks = [t for t in tasks if t.task_id not in done_ids]

    if not tasks:
        print(
            f'Nothing to do. output already contains all requested tasks: {output_jsonl}'
        )
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
    write_lock = threading.Lock()
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
