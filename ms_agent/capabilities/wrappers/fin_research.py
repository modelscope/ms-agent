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

_FIN_RESEARCH_INPUT_PROPERTIES: dict[str, Any] = {
    'query': {
        'type':
        'string',
        'description':
        ('Financial research question. e.g. "Analyze CATL (300750.SZ) '
         'profitability over the past four quarters and compare with '
         'BYD and Gotion High-Tech."'),
    },
    'config_path': {
        'type':
        'string',
        'description': ('Path to the fin_research config directory. '
                        'Defaults to the bundled projects/fin_research.'),
    },
    'output_dir': {
        'type':
        'string',
        'description':
        'Directory for research outputs (auto-generated if omitted)',
    },
}

SUBMIT_DESCRIPTOR = CapabilityDescriptor(
    name='submit_fin_research_task',
    version='0.1.0',
    granularity='project',
    summary=(
        'Submit a financial research task that runs in the background. '
        'Returns a task_id immediately -- use check_fin_research_progress '
        'and get_fin_research_report to poll results.'),
    description=(
        'Launches the fin_research multi-agent DAG workflow as a background '
        'subprocess. The pipeline orchestrates five specialized agents '
        '(orchestrator, searcher, collector, analyst, aggregator) to produce '
        'a comprehensive financial analysis report with data visualization, '
        'sentiment analysis, and quantitative analysis.'),
    input_schema={
        'type': 'object',
        'properties': _FIN_RESEARCH_INPUT_PROPERTIES,
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
    tags=['finance', 'research', 'report', 'analysis', 'async', 'submit'],
    estimated_duration='seconds',
    requires={'env': ['OPENAI_API_KEY']},
)

CHECK_PROGRESS_DESCRIPTOR = CapabilityDescriptor(
    name='check_fin_research_progress',
    version='0.1.0',
    granularity='tool',
    summary=('Check the progress of a running financial research task. '
             'Returns status, generated chapters, and data file counts.'),
    description=(
        'Polls the status of a fin_research task previously submitted via '
        'submit_fin_research_task. Inspects the output directory to report '
        'progress on data collection, analysis, and report generation.'),
    input_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type': 'string',
                'description':
                'The task_id returned by submit_fin_research_task',
            },
        },
        'required': ['task_id'],
    },
    tags=['finance', 'research', 'async', 'progress'],
    estimated_duration='seconds',
)

GET_REPORT_DESCRIPTOR = CapabilityDescriptor(
    name='get_fin_research_report',
    version='0.1.0',
    granularity='tool',
    summary=(
        'Retrieve the final report from a completed financial research task. '
        'Returns the report content or an error if not yet complete.'),
    description=(
        'Reads the final financial research report produced by a completed '
        'task. The report includes quantitative analysis, sentiment analysis, '
        'data visualizations, and comprehensive chapter-based findings.'),
    input_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type': 'string',
                'description':
                'The task_id returned by submit_fin_research_task',
            },
            'max_chars': {
                'type': 'integer',
                'description': 'Maximum characters to return (default: 50000)',
                'default': 50000,
            },
        },
        'required': ['task_id'],
    },
    tags=['finance', 'research', 'async', 'report'],
    estimated_duration='seconds',
)

SYNC_DESCRIPTOR = CapabilityDescriptor(
    name='fin_research',
    version='0.1.0',
    granularity='project',
    summary=
    ('Run financial research synchronously (BLOCKS until complete, 20-60 min). '
     'Prefer submit_fin_research_task for non-blocking usage.'),
    description=(
        'Synchronous version that blocks until financial research is complete. '
        'WARNING: This can take 20-60 minutes. Use '
        'submit_fin_research_task + check_fin_research_progress + '
        'get_fin_research_report for non-blocking async operation.'),
    input_schema={
        'type': 'object',
        'properties': _FIN_RESEARCH_INPUT_PROPERTIES,
        'required': ['query'],
    },
    tags=['finance', 'research', 'report', 'sync'],
    estimated_duration='hours',
    requires={'env': ['OPENAI_API_KEY']},
)


def _find_default_config() -> str | None:
    candidates = [
        os.path.join(
            os.path.dirname(__file__), '..', '..', '..', 'projects',
            'fin_research'),
    ]
    try:
        from importlib import resources as importlib_resources
        trav = importlib_resources.files('ms_agent').joinpath(
            'projects', 'fin_research')
        candidates.insert(0, str(trav))
    except Exception:
        pass

    for p in candidates:
        if os.path.isdir(p):
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
    report_path = os.path.join(output_dir, 'report.md')
    if os.path.isfile(report_path):
        return report_path
    candidates = list(Path(output_dir).rglob('report.md'))
    return str(candidates[0]) if candidates else ''


def _count_artifacts(output_dir: str) -> dict[str, Any]:
    if not os.path.isdir(output_dir):
        return {'chapters': 0, 'data_files': 0, 'charts': 0}

    chapters = len(list(Path(output_dir).glob('chapter_*.md')))
    data_files = len(list(Path(output_dir).rglob('*.csv')))
    charts = len(list(Path(output_dir).rglob('*.png')))
    has_plan = os.path.isfile(os.path.join(output_dir, 'plan.json'))
    has_analysis = os.path.isfile(
        os.path.join(output_dir, 'analysis_report.md'))
    has_sentiment = os.path.isfile(
        os.path.join(output_dir, 'sentiment_report.md'))

    return {
        'chapters': chapters,
        'data_files': data_files,
        'charts': charts,
        'has_plan': has_plan,
        'has_analysis_report': has_analysis,
        'has_sentiment_report': has_sentiment,
    }


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
    artifacts = _count_artifacts(output_dir)
    report_path = _find_report(output_dir)
    result = {
        'query': task.metadata.get('query', ''),
        'output_dir': output_dir,
        **artifacts,
        'report_available': bool(report_path),
    }
    log_tail = _read_log_tail(task.metadata.get('log_path', ''))
    if log_tail:
        result['log_tail'] = log_tail
    return result


async def _background_fin_research(task: AsyncTask) -> dict[str, Any]:
    query = task.metadata['query']
    config_path = task.metadata['config_path']
    output_dir = task.metadata['output_dir']

    log_path = os.path.join(output_dir, 'ms_agent.log')
    task.metadata['log_path'] = log_path

    cmd = _build_cmd(config_path, query, output_dir)
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
        report_path = _find_report(output_dir)
        task.metadata['report_path'] = report_path
        return {'report_path': report_path, 'output_dir': output_dir}
    else:
        with open(log_path, 'r', errors='replace') as f:
            stderr_tail = f.read()[-2000:]
        raise RuntimeError(stderr_tail)


async def _handle_submit(args: dict[str, Any],
                         **kwargs: Any) -> dict[str, Any]:
    query: str = args['query']
    config_path = args.get('config_path', '') or _find_default_config() or ''
    output_dir = args.get('output_dir', '')

    if not config_path or not os.path.isdir(config_path):
        return {'error': f'Config directory not found: {config_path}'}

    if not output_dir:
        ts = time.strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.abspath(f'output/fin_research_{ts}')
    os.makedirs(output_dir, exist_ok=True)

    task = _manager.submit(
        task_type='fin_research',
        coroutine_fn=_background_fin_research,
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
        (f'Financial research task {task.task_id} started. '
         f'Use check_fin_research_progress(task_id="{task.task_id}") '
         f'to poll status.'),
    }


async def _handle_check_progress(args: dict[str, Any],
                                 **kwargs: Any) -> dict[str, Any]:
    return _manager.check(args['task_id'], progress_fn=_progress_fn)


async def _handle_get_report(args: dict[str, Any],
                             **kwargs: Any) -> dict[str, Any]:
    task_id: str = args['task_id']
    max_chars: int = args.get('max_chars', 50000)
    task = _manager.get(task_id)

    if task is None:
        return {'error': f'Unknown task_id: {task_id}'}

    if task.status == 'running':
        artifacts = _count_artifacts(task.metadata.get('output_dir', ''))
        return {
            'task_id':
            task_id,
            'status':
            'running',
            'message': ('Financial research is still in progress. '
                        f'Progress: {artifacts["chapters"]} chapters, '
                        f'{artifacts["data_files"]} data files, '
                        f'{artifacts["charts"]} charts generated.'),
        }

    if task.status == 'failed':
        return {'task_id': task_id, 'status': 'failed', 'error': task.error}

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
        content = content[:max_chars] + (
            '\n\n... [truncated, use a larger max_chars or read the file directly]'
        )

    artifacts = _count_artifacts(output_dir)

    return {
        'task_id': task_id,
        'status': 'completed',
        'report_path': report_path,
        'report_content': content,
        'truncated': truncated,
        'output_dir': output_dir,
        **artifacts,
    }


async def _handle_sync(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    query: str = args['query']
    config_path = args.get('config_path', '') or _find_default_config() or ''
    output_dir = args.get('output_dir', '')

    if not config_path or not os.path.isdir(config_path):
        return {
            'status': 'failed',
            'error': f'Config not found: {config_path}'
        }

    if not output_dir:
        ts = time.strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.abspath(f'output/fin_research_{ts}')
    os.makedirs(output_dir, exist_ok=True)

    cmd = _build_cmd(config_path, query, output_dir)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            cwd=config_path,
        )
        stderr = await proc.stderr.read()
        await proc.wait()
        report_path = _find_report(output_dir)
        if proc.returncode == 0:
            return {
                'status': 'completed',
                'output_dir': output_dir,
                'report_path': report_path,
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
    registry.register(SUBMIT_DESCRIPTOR, _handle_submit)
    registry.register(CHECK_PROGRESS_DESCRIPTOR, _handle_check_progress)
    registry.register(GET_REPORT_DESCRIPTOR, _handle_get_report)
    registry.register(SYNC_DESCRIPTOR, _handle_sync)
