# Copyright (c) ModelScope Contributors. All rights reserved.
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from ms_agent.capabilities.async_task import AsyncTask, get_default_manager
from ms_agent.capabilities.descriptor import CapabilityDescriptor
from ms_agent.capabilities.registry import CapabilityRegistry

logger = logging.getLogger(__name__)

_manager = get_default_manager()

_DOC_RESEARCH_INPUT_PROPERTIES: dict[str, Any] = {
    'query': {
        'type':
        'string',
        'description':
        ('Research prompt or question about the documents. '
         'e.g. "Deeply analyze and summarize the following document"'),
    },
    'urls': {
        'type':
        'string',
        'description':
        ('Newline-separated or comma-separated URLs to research. '
         'Supports PDF, web pages, arxiv links. '
         'e.g. "https://arxiv.org/pdf/2504.17432"'),
    },
    'file_paths': {
        'type':
        'string',
        'description': ('Comma-separated local file paths to analyze. '
                        'Supports PDF, TXT, PPT, DOCX. '
                        'e.g. "/path/to/paper.pdf,/path/to/notes.txt"'),
    },
    'output_dir': {
        'type':
        'string',
        'description':
        'Directory for research outputs (auto-generated if omitted)',
    },
}

SUBMIT_DESCRIPTOR = CapabilityDescriptor(
    name='submit_doc_research_task',
    version='0.1.0',
    granularity='project',
    summary=(
        'Submit a document research task that runs in the background. '
        'Analyzes documents/URLs and produces a multimodal markdown report.'),
    description=(
        'Launches a document research workflow that deeply analyzes '
        'provided documents (PDF, TXT, PPT, DOCX) or URLs and produces '
        'a structured markdown report with extracted images, tables, '
        'and key insights. Supports multi-file and multi-URL inputs.'),
    input_schema={
        'type': 'object',
        'properties': _DOC_RESEARCH_INPUT_PROPERTIES,
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
    tags=['document', 'research', 'analysis', 'report', 'async', 'submit'],
    estimated_duration='seconds',
    requires={'env': ['OPENAI_API_KEY']},
)

CHECK_PROGRESS_DESCRIPTOR = CapabilityDescriptor(
    name='check_doc_research_progress',
    version='0.1.0',
    granularity='tool',
    summary=('Check the progress of a running document research task.'),
    description=(
        'Polls the status of a doc_research task previously submitted via '
        'submit_doc_research_task.'),
    input_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type': 'string',
                'description':
                'The task_id returned by submit_doc_research_task',
            },
        },
        'required': ['task_id'],
    },
    tags=['document', 'research', 'async', 'progress'],
    estimated_duration='seconds',
)

GET_REPORT_DESCRIPTOR = CapabilityDescriptor(
    name='get_doc_research_report',
    version='0.1.0',
    granularity='tool',
    summary=(
        'Retrieve the final report from a completed document research task.'),
    description=(
        'Reads the markdown report produced by a completed doc_research task. '
        'The report includes text analysis, extracted images, tables, '
        'and key findings following the MECE principle.'),
    input_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type': 'string',
                'description':
                'The task_id returned by submit_doc_research_task',
            },
            'max_chars': {
                'type': 'integer',
                'description': 'Maximum characters to return (default: 50000)',
                'default': 50000,
            },
        },
        'required': ['task_id'],
    },
    tags=['document', 'research', 'async', 'report'],
    estimated_duration='seconds',
)

SYNC_DESCRIPTOR = CapabilityDescriptor(
    name='doc_research',
    version='0.1.0',
    granularity='project',
    summary=
    ('Analyze documents/URLs and generate a research report (BLOCKS, 1-20 min). '
     'Prefer submit_doc_research_task for non-blocking usage.'),
    description=(
        'Synchronous version that blocks until document research is complete. '
        'Analyzes documents/URLs and produces a structured markdown report. '
        'WARNING: May take 5-20 minutes depending on document count/size.'),
    input_schema={
        'type': 'object',
        'properties': _DOC_RESEARCH_INPUT_PROPERTIES,
        'required': ['query'],
    },
    tags=['document', 'research', 'analysis', 'report', 'sync'],
    estimated_duration='minutes',
    requires={'env': ['OPENAI_API_KEY']},
)


def _parse_urls_and_files(
    urls: str | None,
    file_paths: str | None,
) -> list[str] | None:
    """Parse URL and file path strings into a combined list."""
    items: list[str] = []
    if urls:
        for sep in ['\n', ',']:
            if sep in urls:
                items.extend(u.strip() for u in urls.split(sep) if u.strip())
                break
        else:
            items.append(urls.strip())
    if file_paths:
        items.extend(p.strip() for p in file_paths.split(',') if p.strip())
    return items if items else None


def _find_report(output_dir: str) -> str:
    report_path = os.path.join(output_dir, 'report.md')
    if os.path.isfile(report_path):
        return report_path
    candidates = list(Path(output_dir).rglob('report.md'))
    return str(candidates[0]) if candidates else ''


def _count_resources(output_dir: str) -> dict[str, int]:
    resources_dir = os.path.join(output_dir, 'resources')
    if not os.path.isdir(resources_dir):
        return {'images': 0}
    images = len([
        f for f in os.listdir(resources_dir)
        if f.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))
    ])
    return {'images': images}


def _progress_fn(task: AsyncTask) -> dict[str, Any]:
    output_dir = task.metadata.get('output_dir', '')
    report_path = _find_report(output_dir)
    resources = _count_resources(output_dir)
    return {
        'query': task.metadata.get('query', ''),
        'output_dir': output_dir,
        'report_available': bool(report_path),
        **resources,
    }


def _create_workflow(workdir: str) -> Any:
    """Create a ResearchWorkflow instance using env-configured LLM."""
    from ms_agent.llm.openai import OpenAIChat

    api_key = os.environ.get('OPENAI_API_KEY', '')
    base_url = os.environ.get(
        'OPENAI_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
    model = os.environ.get('OPENAI_MODEL_ID', 'qwen3-max')

    client = OpenAIChat(
        model=model,
        api_key=api_key,
        base_url=base_url,
    )

    from ms_agent.workflow.deep_research.research_workflow import ResearchWorkflow
    return ResearchWorkflow(
        client=client,
        workdir=workdir,
        verbose=True,
    )


async def _run_doc_research(
    query: str,
    urls_or_files: list[str] | None,
    output_dir: str,
) -> str:
    """Run doc research in a thread executor (the workflow is synchronous)."""
    workflow = _create_workflow(output_dir)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: workflow.run(
            user_prompt=query,
            urls_or_files=urls_or_files,
        ),
    )

    return _find_report(output_dir)


async def _background_doc_research(task: AsyncTask) -> dict[str, Any]:
    query = task.metadata['query']
    urls_or_files = task.metadata.get('urls_or_files')
    output_dir = task.metadata['output_dir']

    report_path = await _run_doc_research(query, urls_or_files, output_dir)
    task.metadata['report_path'] = report_path
    return {'report_path': report_path, 'output_dir': output_dir}


async def _handle_submit(args: dict[str, Any],
                         **kwargs: Any) -> dict[str, Any]:
    query: str = (args.get('query') or '').strip()
    if not query:
        return {'error': 'query is required'}

    urls_or_files = _parse_urls_and_files(
        args.get('urls'), args.get('file_paths'))

    output_dir = args.get('output_dir', '')
    if not output_dir:
        ts = time.strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.abspath(f'output/doc_research_{ts}')
    os.makedirs(output_dir, exist_ok=True)

    task = _manager.submit(
        task_type='doc_research',
        coroutine_fn=_background_doc_research,
        metadata={
            'query': query,
            'urls_or_files': urls_or_files,
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
        (f'Document research task {task.task_id} started. '
         f'Use check_doc_research_progress(task_id="{task.task_id}") '
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
        return {
            'task_id': task_id,
            'status': 'running',
            'message': 'Document research is still in progress.',
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

    resources = _count_resources(output_dir)

    return {
        'task_id': task_id,
        'status': 'completed',
        'report_path': report_path,
        'report_content': content,
        'truncated': truncated,
        'output_dir': output_dir,
        **resources,
    }


async def _handle_sync(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    query: str = (args.get('query') or '').strip()
    if not query:
        return {'error': 'query is required'}

    urls_or_files = _parse_urls_and_files(
        args.get('urls'), args.get('file_paths'))

    output_dir = args.get('output_dir', '')
    if not output_dir:
        ts = time.strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.abspath(f'output/doc_research_{ts}')
    os.makedirs(output_dir, exist_ok=True)

    try:
        report_path = await _run_doc_research(query, urls_or_files, output_dir)
        return {
            'status': 'completed',
            'output_dir': output_dir,
            'report_path': report_path,
        }
    except Exception as e:
        return {'status': 'failed', 'error': str(e)}


def register_all(registry: CapabilityRegistry, config: Any = None) -> None:
    registry.register(SUBMIT_DESCRIPTOR, _handle_submit)
    registry.register(CHECK_PROGRESS_DESCRIPTOR, _handle_check_progress)
    registry.register(GET_REPORT_DESCRIPTOR, _handle_get_report)
    registry.register(SYNC_DESCRIPTOR, _handle_sync)
