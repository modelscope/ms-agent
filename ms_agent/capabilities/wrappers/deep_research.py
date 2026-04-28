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

# Shared task manager instance
_manager = get_default_manager()

# Capability descriptors
SUBMIT_DESCRIPTOR = CapabilityDescriptor(
    name='submit_research_task',
    version='0.1.0',
    granularity='project',
    summary=('Submit a deep research task that runs in the background. '
             'Returns a task_id immediately -- use check_research_progress '
             'and get_research_report to poll results.'),
    description=(
        'Launches the deep_research v2 pipeline as a background subprocess. '
        'The calling agent is NOT blocked and can continue other work. '
        'Use check_research_progress(task_id) to poll status, and '
        'get_research_report(task_id) to retrieve the final report.'),
    input_schema={
        'type': 'object',
        'properties': {
            'query': {
                'type': 'string',
                'description': 'The research question or topic to investigate',
            },
            'config_path': {
                'type':
                'string',
                'description': ('Path to researcher.yaml config. '
                                'Defaults to the bundled v2 config.'),
            },
            'output_dir': {
                'type':
                'string',
                'description':
                'Directory for research outputs (auto-generated if omitted)',
            },
        },
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
    tags=['research', 'search', 'report', 'async', 'submit'],
    estimated_duration='seconds',
)

CHECK_PROGRESS_DESCRIPTOR = CapabilityDescriptor(
    name='check_research_progress',
    version='0.1.0',
    granularity='tool',
    summary=('Check the progress of a running deep research task. '
             'Returns status, evidence count, and latest activity.'),
    description=(
        'Polls the status of a research task previously submitted via '
        'submit_research_task.  Inspects the output directory to report '
        'how many evidence notes and analyses have been collected so far.'),
    input_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type': 'string',
                'description': 'The task_id returned by submit_research_task',
            },
        },
        'required': ['task_id'],
    },
    tags=['research', 'async', 'progress'],
    estimated_duration='seconds',
)

GET_REPORT_DESCRIPTOR = CapabilityDescriptor(
    name='get_research_report',
    version='0.1.0',
    granularity='tool',
    summary=('Retrieve the final report from a completed deep research task. '
             'Returns the report content or an error if not yet complete.'),
    description=(
        'Reads the final research report produced by a completed task. '
        'If the task is still running, returns a message to wait. '
        'If completed, returns the full report markdown content.'),
    input_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type': 'string',
                'description': 'The task_id returned by submit_research_task',
            },
            'max_chars': {
                'type': 'integer',
                'description': 'Maximum characters to return (default: 50000)',
                'default': 50000,
            },
        },
        'required': ['task_id'],
    },
    tags=['research', 'async', 'report'],
    estimated_duration='seconds',
)

# Keep the synchronous descriptor for direct invocation
DEEP_RESEARCH_SYNC_DESCRIPTOR = CapabilityDescriptor(
    name='deep_research',
    version='0.1.0',
    granularity='project',
    summary=(
        'Run deep research synchronously (BLOCKS until complete, 20-60 min). '
        'Prefer submit_research_task for non-blocking usage.'),
    description=(
        'Synchronous version that blocks until the research is complete. '
        'WARNING: This can take 20-60 minutes. Most MCP clients will '
        'timeout. Use submit_research_task + check_research_progress + '
        'get_research_report for non-blocking async operation.'),
    input_schema={
        'type': 'object',
        'properties': {
            'query': {
                'type': 'string',
                'description': 'The research question or topic to investigate',
            },
            'config_path': {
                'type': 'string',
                'description': 'Path to researcher.yaml'
            },
            'output_dir': {
                'type': 'string',
                'description': 'Output directory'
            },
        },
        'required': ['query'],
    },
    tags=['research', 'search', 'report', 'sync'],
    estimated_duration='hours',
    requires={'env': ['OPENAI_API_KEY']},
)


def _find_default_config() -> str | None:
    """Locate the bundled deep_research v2 researcher.yaml."""
    candidates = [
        os.path.join(
            os.path.dirname(__file__), '..', '..', '..', 'projects',
            'deep_research', 'v2', 'researcher.yaml'),
    ]
    try:
        from importlib import resources as importlib_resources
        trav = importlib_resources.files('ms_agent').joinpath(
            'projects', 'deep_research', 'v2', 'researcher.yaml')
        candidates.insert(0, str(trav))
    except Exception:
        pass

    for p in candidates:
        if os.path.isfile(p):
            return os.path.abspath(p)
    return None


def _build_cmd(config_path: str, query: str, output_dir: str) -> list[str]:
    return [
        sys.executable,
        '-m',
        'ms_agent.cli.cli',
        'run',
        '--config',
        config_path,
        '--query',
        query,
        '--output_dir',
        output_dir,
        '--trust_remote_code',
        'true',
    ]


def _find_report(output_dir: str) -> str:
    report_path = os.path.join(output_dir, 'final_report.md')
    if os.path.isfile(report_path):
        return report_path
    candidates = list(Path(output_dir).rglob('report.md'))
    return str(candidates[0]) if candidates else ''


def _count_evidence(output_dir: str) -> dict[str, int]:
    """Count evidence files in the output directory."""
    evidence_dir = os.path.join(output_dir, 'evidence')
    notes_dir = os.path.join(evidence_dir, 'notes')
    analyses_dir = os.path.join(evidence_dir, 'analyses')
    return {
        'notes':
        len(list(Path(notes_dir).glob('*.md')))
        if os.path.isdir(notes_dir) else 0,
        'analyses':
        len(list(Path(analyses_dir).glob('*.md')))
        if os.path.isdir(analyses_dir) else 0,
    }


def _research_progress_fn(task: AsyncTask) -> dict[str, Any]:
    """Progress callback for research tasks -- counts evidence files."""
    output_dir = task.metadata.get('output_dir', '')
    evidence = _count_evidence(output_dir)
    report_path = _find_report(output_dir)
    info: dict[str, Any] = {
        'query': task.metadata.get('query', ''),
        'output_dir': output_dir,
        'evidence_notes': evidence['notes'],
        'evidence_analyses': evidence['analyses'],
        'report_available': bool(report_path),
    }
    if task.status == 'completed':
        info['report_path'] = task.metadata.get('report_path',
                                                '') or report_path
    return info


async def _background_research(task: AsyncTask) -> dict[str, Any]:
    """Run the research subprocess in the background.

    Returns a result dict on success; raises on failure (the
    AsyncTaskManager wrapper handles status transitions).

    stdout is sent to DEVNULL because the inner LLMAgent writes streaming
    content via ``sys.stdout.write()`` which causes BrokenPipeError when
    connected to a pipe.  All meaningful output goes to the ms_agent.log
    file inside the working directory; the final report is read from disk.
    """
    query = task.metadata['query']
    config_path = task.metadata['config_path']
    output_dir = task.metadata['output_dir']

    cmd = _build_cmd(config_path, query, output_dir)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        cwd=os.path.dirname(config_path),
    )
    task._process = proc
    task.metadata['pid'] = proc.pid

    stderr = await proc.stderr.read()
    await proc.wait()

    if proc.returncode == 0:
        report_path = _find_report(output_dir)
        task.metadata['report_path'] = report_path
        return {'report_path': report_path, 'output_dir': output_dir}
    else:
        raise RuntimeError(stderr.decode('utf-8', errors='replace')[-2000:])


async def _handle_submit(args: dict[str, Any],
                         **kwargs: Any) -> dict[str, Any]:
    """Submit a research task to run in the background."""
    query: str = args['query']
    config_path = args.get('config_path', '') or _find_default_config() or ''
    output_dir = args.get('output_dir', '')

    if not config_path or not os.path.isfile(config_path):
        return {'error': f'Config not found: {config_path}'}

    if not output_dir:
        ts = time.strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.abspath(f'output/deep_research_{ts}')
    os.makedirs(output_dir, exist_ok=True)

    task = _manager.submit(
        task_type='research',
        coroutine_fn=_background_research,
        metadata={
            'query': query,
            'config_path': config_path,
            'output_dir': output_dir,
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
        (f'Research task {task.task_id} started. '
         f'Use check_research_progress(task_id="{task.task_id}") to poll status.'
         ),
    }


async def _handle_check_progress(args: dict[str, Any],
                                 **kwargs: Any) -> dict[str, Any]:
    """Check the progress of a running research task."""
    task_id: str = args['task_id']
    return _manager.check(task_id, progress_fn=_research_progress_fn)


async def _handle_get_report(args: dict[str, Any],
                             **kwargs: Any) -> dict[str, Any]:
    """Retrieve the final report from a completed task."""
    task_id: str = args['task_id']
    max_chars: int = args.get('max_chars', 50000)
    task = _manager.get(task_id)

    if task is None:
        return {'error': f'Unknown task_id: {task_id}'}

    if task.status == 'running':
        evidence = _count_evidence(task.metadata.get('output_dir', ''))
        return {
            'task_id':
            task_id,
            'status':
            'running',
            'message':
            ('Research is still in progress. '
             f'Evidence collected so far: {evidence["notes"]} notes, '
             f'{evidence["analyses"]} analyses. '
             'Please check again later.'),
        }

    if task.status == 'failed':
        return {
            'task_id': task_id,
            'status': 'failed',
            'error': task.error,
        }

    output_dir = task.metadata.get('output_dir', '')
    report_path = task.metadata.get('report_path',
                                    '') or _find_report(output_dir)
    if not report_path or not os.path.isfile(report_path):
        return {
            'task_id': task_id,
            'status': 'completed',
            'error': 'Report file not found in output directory',
            'output_dir': output_dir,
        }

    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()

    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars] + '\n\n... [truncated, use a larger max_chars or read the file directly]'

    return {
        'task_id': task_id,
        'status': 'completed',
        'report_path': report_path,
        'report_content': content,
        'truncated': truncated,
    }


async def _handle_deep_research_sync(args: dict[str, Any],
                                     **kwargs: Any) -> dict[str, Any]:
    """Launch deep_research synchronously (blocks until complete)."""
    query: str = args['query']
    config_path = args.get('config_path', '') or _find_default_config() or ''
    output_dir = args.get('output_dir', '')

    if not config_path or not os.path.isfile(config_path):
        return {
            'status': 'failed',
            'error': f'Config not found: {config_path}'
        }

    if not output_dir:
        ts = time.strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.abspath(f'output/deep_research_{ts}')
    os.makedirs(output_dir, exist_ok=True)

    cmd = _build_cmd(config_path, query, output_dir)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.path.dirname(config_path),
        )
        stderr = await proc.stderr.read()
        await proc.wait()
        report_path = _find_report(output_dir)
        if proc.returncode == 0:
            return {
                'status': 'completed',
                'output_dir': output_dir,
                'report_path': report_path
            }
        else:
            return {
                'status': 'failed',
                'output_dir': output_dir,
                'error': stderr.decode('utf-8', errors='replace')[-2000:]
            }
    except Exception as e:
        return {'status': 'failed', 'error': str(e)}


def register_all(registry: CapabilityRegistry, config: Any = None) -> None:
    """Register all deep_research capabilities into the registry."""
    # Async trio (recommended for MCP / external agents)
    registry.register(SUBMIT_DESCRIPTOR, _handle_submit)
    registry.register(CHECK_PROGRESS_DESCRIPTOR, _handle_check_progress)
    registry.register(GET_REPORT_DESCRIPTOR, _handle_get_report)
    # Sync (for direct Python API or long-timeout scenarios)
    registry.register(DEEP_RESEARCH_SYNC_DESCRIPTOR,
                      _handle_deep_research_sync)
