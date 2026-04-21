# Copyright (c) ModelScope Contributors. All rights reserved.
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

from ms_agent.capabilities.async_task import AsyncTask, get_default_manager
from ms_agent.capabilities.descriptor import CapabilityDescriptor
from ms_agent.capabilities.registry import CapabilityRegistry

_manager = get_default_manager()

_CODE_GENESIS_INPUT_PROPERTIES: dict[str, Any] = {
    'query': {
        'type':
        'string',
        'description':
        ('Natural language description of the software project to generate. '
         'e.g. "make a demo website with login page and dashboard"'),
    },
    'config_path': {
        'type':
        'string',
        'description':
        ('Path to the code_genesis config directory or workflow YAML. '
         'Defaults to the bundled projects/code_genesis.'),
    },
    'output_dir': {
        'type':
        'string',
        'description':
        'Directory for generated code output (auto-generated if omitted)',
    },
    'workflow': {
        'type':
        'string',
        'enum': ['standard', 'simple'],
        'description':
        ('Workflow mode: "standard" (7-stage) or "simple" (4-stage). '
         'Default: standard'),
        'default':
        'standard',
    },
}

SUBMIT_DESCRIPTOR = CapabilityDescriptor(
    name='submit_code_genesis_task',
    version='0.1.0',
    granularity='project',
    summary=(
        'Submit a code generation task that runs in the background. '
        'Returns a task_id immediately -- use check_code_genesis_progress '
        'and get_code_genesis_result to poll results.'),
    description=(
        'Launches the code_genesis multi-agent pipeline as a background '
        'subprocess. The pipeline generates production-ready software '
        'projects from natural language requirements through a 7-stage '
        '(or 4-stage simple) workflow including user story analysis, '
        'architecture design, code generation with LSP validation, and '
        'runtime refinement.'),
    input_schema={
        'type': 'object',
        'properties': _CODE_GENESIS_INPUT_PROPERTIES,
        'required': ['query'],
    },
    output_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type': 'string'
            },
            'status': {
                'type': 'string'
            },
            'output_dir': {
                'type': 'string'
            },
        },
    },
    tags=['code', 'generation', 'codegen', 'async', 'submit'],
    estimated_duration='seconds',
    requires={'env': ['OPENAI_API_KEY']},
)

CHECK_PROGRESS_DESCRIPTOR = CapabilityDescriptor(
    name='check_code_genesis_progress',
    version='0.1.0',
    granularity='tool',
    summary=('Check the progress of a running code generation task. '
             'Returns status and generated file counts.'),
    description=(
        'Polls the status of a code_genesis task previously submitted via '
        'submit_code_genesis_task. Inspects the output directory to report '
        'how many files have been generated so far.'),
    input_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type': 'string',
                'description':
                'The task_id returned by submit_code_genesis_task',
            },
        },
        'required': ['task_id'],
    },
    tags=['code', 'generation', 'async', 'progress'],
    estimated_duration='seconds',
)

GET_RESULT_DESCRIPTOR = CapabilityDescriptor(
    name='get_code_genesis_result',
    version='0.1.0',
    granularity='tool',
    summary=('Retrieve the result from a completed code generation task. '
             'Returns the generated file tree and key file contents.'),
    description=(
        'Reads the output directory from a completed code_genesis task '
        'and returns a file tree listing plus content of key files '
        '(README, package.json, main entry points).'),
    input_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type': 'string',
                'description':
                'The task_id returned by submit_code_genesis_task',
            },
            'max_chars': {
                'type': 'integer',
                'description': 'Maximum characters to return (default: 50000)',
                'default': 50000,
            },
        },
        'required': ['task_id'],
    },
    tags=['code', 'generation', 'async', 'result'],
    estimated_duration='seconds',
)

SYNC_DESCRIPTOR = CapabilityDescriptor(
    name='code_genesis',
    version='0.1.0',
    granularity='project',
    summary=(
        'Run code generation synchronously (BLOCKS until complete, 10-30 min). '
        'Prefer submit_code_genesis_task for non-blocking usage.'),
    description=(
        'Synchronous version that blocks until code generation is complete. '
        'WARNING: This can take 10-30 minutes. Use '
        'submit_code_genesis_task + check_code_genesis_progress + '
        'get_code_genesis_result for non-blocking async operation.'),
    input_schema={
        'type': 'object',
        'properties': _CODE_GENESIS_INPUT_PROPERTIES,
        'required': ['query'],
    },
    tags=['code', 'generation', 'codegen', 'sync'],
    estimated_duration='hours',
    requires={'env': ['OPENAI_API_KEY']},
)


def _find_default_config() -> str | None:
    """Locate the bundled code_genesis project directory."""
    candidates = [
        os.path.join(
            os.path.dirname(__file__), '..', '..', '..', 'projects',
            'code_genesis'),
    ]
    try:
        from importlib import resources as importlib_resources
        trav = importlib_resources.files('ms_agent').joinpath(
            'projects', 'code_genesis')
        candidates.insert(0, str(trav))
    except Exception:
        pass

    for p in candidates:
        if os.path.isdir(p):
            return os.path.abspath(p)
    return None


def _build_cmd(config_path: str,
               query: str,
               output_dir: str,
               workflow: str = 'standard') -> list[str]:
    config_target = config_path
    if workflow == 'simple':
        simple_wf = os.path.join(config_path, 'simple_workflow.yaml')
        if os.path.isfile(simple_wf):
            config_target = simple_wf

    return [
        sys.executable,
        '-m',
        'ms_agent.cli.cli',
        'run',
        '--config',
        config_target,
        '--query',
        query,
        '--output_dir',
        output_dir,
        '--trust_remote_code',
        'true',
    ]


def _count_generated_files(output_dir: str) -> dict[str, Any]:
    if not os.path.isdir(output_dir):
        return {'total_files': 0, 'file_types': {}}

    type_counts: dict[str, int] = {}
    total = 0
    for root, _dirs, files in os.walk(output_dir):
        if 'node_modules' in root or '.git' in root:
            continue
        for f in files:
            total += 1
            ext = os.path.splitext(f)[1] or '(no ext)'
            type_counts[ext] = type_counts.get(ext, 0) + 1

    return {'total_files': total, 'file_types': type_counts}


def _build_file_tree(output_dir: str, max_depth: int = 4) -> str:
    """Build a human-readable tree representation of the output directory."""
    if not os.path.isdir(output_dir):
        return '(empty)'

    lines: list[str] = []
    skip = ('node_modules', '.git', '__pycache__')

    def _walk(path: str, prefix: str, depth: int) -> None:
        if depth > max_depth:
            lines.append(f'{prefix}...')
            return
        try:
            entries = sorted(os.listdir(path))
        except PermissionError:
            return
        entries = [e for e in entries if e not in skip]
        for i, entry in enumerate(entries):
            is_last = (i == len(entries) - 1)
            connector = '└── ' if is_last else '├── '
            full = os.path.join(path, entry)
            lines.append(f'{prefix}{connector}{entry}')
            if os.path.isdir(full):
                ext = '    ' if is_last else '│   '
                _walk(full, prefix + ext, depth + 1)

    _walk(output_dir, '', 0)
    return '\n'.join(lines[:200])


def _read_log_tail(log_path: str, max_lines: int = 5) -> str:
    if not log_path or not os.path.isfile(log_path):
        return ''
    try:
        with open(log_path, 'r', errors='replace') as f:
            lines = f.readlines()
        return '\n'.join(line.rstrip() for line in lines[-max_lines:])
    except Exception:
        return ''


def _progress_fn(task: AsyncTask) -> dict[str, Any]:
    output_dir = task.metadata.get('output_dir', '')
    file_info = _count_generated_files(output_dir)
    result = {
        'query': task.metadata.get('query', ''),
        'output_dir': output_dir,
        'workflow': task.metadata.get('workflow', 'standard'),
        **file_info,
    }
    log_tail = _read_log_tail(task.metadata.get('log_path', ''))
    if log_tail:
        result['log_tail'] = log_tail
    return result


async def _background_code_genesis(task: AsyncTask) -> dict[str, Any]:
    """Run the code_genesis pipeline as a background subprocess.

    stdout is sent to DEVNULL because inner LLMAgents write streaming
    content via sys.stdout.write(). stderr is written to a log file in
    the output directory for live monitoring.
    """
    query = task.metadata['query']
    config_path = task.metadata['config_path']
    output_dir = task.metadata['output_dir']
    workflow = task.metadata.get('workflow', 'standard')

    log_path = os.path.join(output_dir, 'ms_agent.log')
    task.metadata['log_path'] = log_path

    cmd = _build_cmd(config_path, query, output_dir, workflow)
    log_file = open(log_path, 'w')
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=log_file,
            cwd=config_path,
        )
        task._process = proc
        task.metadata['pid'] = proc.pid

        await proc.wait()
    finally:
        log_file.close()

    if proc.returncode == 0:
        file_info = _count_generated_files(output_dir)
        return {'output_dir': output_dir, **file_info}
    else:
        with open(log_path, 'r', errors='replace') as f:
            stderr_tail = f.read()[-2000:]
        raise RuntimeError(stderr_tail)


async def _handle_submit(args: dict[str, Any],
                         **kwargs: Any) -> dict[str, Any]:
    """Submit a code generation task to run in the background."""
    query: str = args['query']
    config_path = args.get('config_path', '') or _find_default_config() or ''
    output_dir = args.get('output_dir', '')
    workflow = args.get('workflow', 'standard')

    if not config_path or not os.path.isdir(config_path):
        return {'error': f'Config directory not found: {config_path}'}

    if not output_dir:
        ts = time.strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.abspath(f'output/code_genesis_{ts}')
    os.makedirs(output_dir, exist_ok=True)

    task = _manager.submit(
        task_type='code_genesis',
        coroutine_fn=_background_code_genesis,
        metadata={
            'query': query,
            'config_path': config_path,
            'output_dir': output_dir,
            'workflow': workflow,
        },
    )

    return {
        'task_id':
        task.task_id,
        'status':
        'running',
        'output_dir':
        output_dir,
        'message':
        (f'Code genesis task {task.task_id} started. '
         f'Use check_code_genesis_progress(task_id="{task.task_id}") '
         f'to poll status.'),
    }


async def _handle_check_progress(args: dict[str, Any],
                                 **kwargs: Any) -> dict[str, Any]:
    """Check the progress of a running code generation task."""
    return _manager.check(args['task_id'], progress_fn=_progress_fn)


async def _handle_get_result(args: dict[str, Any],
                             **kwargs: Any) -> dict[str, Any]:
    """Retrieve the result from a completed code generation task."""
    task_id: str = args['task_id']
    max_chars: int = args.get('max_chars', 50000)
    task = _manager.get(task_id)

    if task is None:
        return {'error': f'Unknown task_id: {task_id}'}

    if task.status == 'running':
        file_info = _count_generated_files(task.metadata.get('output_dir', ''))
        return {
            'task_id':
            task_id,
            'status':
            'running',
            'message':
            ('Code generation is still in progress. '
             f'Files generated so far: {file_info["total_files"]}.'),
        }

    if task.status == 'failed':
        return {'task_id': task_id, 'status': 'failed', 'error': task.error}

    output_dir = task.metadata.get('output_dir', '')
    file_tree = _build_file_tree(output_dir)
    file_info = _count_generated_files(output_dir)

    key_files_content: list[dict[str, str]] = []
    key_names = [
        'README.md',
        'package.json',
        'requirements.txt',
        'index.html',
        'main.py',
        'app.py',
    ]
    chars_used = len(file_tree)
    for root, _dirs, files in os.walk(output_dir):
        if 'node_modules' in root:
            continue
        for fname in files:
            if fname in key_names and chars_used < max_chars:
                fpath = os.path.join(root, fname)
                try:
                    with open(
                            fpath, 'r', encoding='utf-8',
                            errors='replace') as f:
                        content = f.read()
                    remaining = max_chars - chars_used
                    if len(content) > remaining:
                        content = content[:remaining] + '\n... [truncated]'
                    key_files_content.append({
                        'path':
                        os.path.relpath(fpath, output_dir),
                        'content':
                        content,
                    })
                    chars_used += len(content)
                except Exception:
                    pass

    return {
        'task_id': task_id,
        'status': 'completed',
        'output_dir': output_dir,
        'file_tree': file_tree,
        **file_info,
        'key_files': key_files_content,
    }


async def _handle_sync(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Run code generation synchronously (blocks until complete)."""
    query: str = args['query']
    config_path = args.get('config_path', '') or _find_default_config() or ''
    output_dir = args.get('output_dir', '')
    workflow = args.get('workflow', 'standard')

    if not config_path or not os.path.isdir(config_path):
        return {
            'status': 'failed',
            'error': f'Config not found: {config_path}'
        }

    if not output_dir:
        ts = time.strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.abspath(f'output/code_genesis_{ts}')
    os.makedirs(output_dir, exist_ok=True)

    cmd = _build_cmd(config_path, query, output_dir, workflow)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            cwd=config_path,
        )
        stderr = await proc.stderr.read()
        await proc.wait()
        file_info = _count_generated_files(output_dir)
        if proc.returncode == 0:
            return {
                'status': 'completed',
                'output_dir': output_dir,
                **file_info,
            }
        else:
            return {
                'status': 'failed',
                'output_dir': output_dir,
                'error': stderr.decode('utf-8', errors='replace')[-2000:],
            }
    except Exception as e:
        return {'status': 'failed', 'error': str(e)}


def register_all(registry: CapabilityRegistry, config: Any = None) -> None:
    """Register code_genesis capabilities into the registry."""
    registry.register(SUBMIT_DESCRIPTOR, _handle_submit)
    registry.register(CHECK_PROGRESS_DESCRIPTOR, _handle_check_progress)
    registry.register(GET_RESULT_DESCRIPTOR, _handle_get_result)
    registry.register(SYNC_DESCRIPTOR, _handle_sync)
