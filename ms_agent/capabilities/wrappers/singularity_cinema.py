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

_CINEMA_INPUT_PROPERTIES: dict[str, Any] = {
    'query': {
        'type':
        'string',
        'description':
        ('Description of the short video to generate. May include a local '
         'text file path for reference material. '
         'e.g. "Create a short video about GDP economics, about 3 minutes"'),
    },
    'config_path': {
        'type':
        'string',
        'description':
        ('Path to the singularity_cinema config directory. '
         'Defaults to the bundled projects/singularity_cinema.'),
    },
    'output_dir': {
        'type':
        'string',
        'description':
        ('Directory for video outputs (defaults to output_video/ '
         'in current directory if omitted)'),
    },
    'llm_model': {
        'type': 'string',
        'description': 'LLM model name for script generation (optional)',
    },
    'llm_api_key': {
        'type': 'string',
        'description': 'API key for the LLM provider (optional)',
    },
    'llm_base_url': {
        'type': 'string',
        'description': 'OpenAI-compatible base URL for LLM (optional)',
    },
    'image_generator_type': {
        'type': 'string',
        'enum': ['modelscope', 'dashscope', 'google'],
        'description': 'Image generator provider type (optional)',
    },
    'image_generator_model': {
        'type': 'string',
        'description': 'Image generation model name (optional)',
    },
    'image_generator_api_key': {
        'type': 'string',
        'description': 'API key for the image generator (optional)',
    },
}

SUBMIT_DESCRIPTOR = CapabilityDescriptor(
    name='submit_video_generation_task',
    version='0.1.0',
    granularity='project',
    summary=(
        'Submit a short video generation task that runs in the background. '
        'Returns a task_id immediately -- use check_video_generation_progress '
        'and get_video_generation_result to poll results.'),
    description=(
        'Launches the SingularityCinema pipeline as a background subprocess. '
        'The pipeline generates short videos from natural language '
        'descriptions through a multi-step workflow: script generation, '
        'segmentation, audio synthesis, image generation, animation '
        'rendering, and final video composition. Output is an MP4 file.'),
    input_schema={
        'type': 'object',
        'properties': _CINEMA_INPUT_PROPERTIES,
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
    tags=['video', 'generation', 'cinema', 'multimedia', 'async', 'submit'],
    estimated_duration='seconds',
    requires={'env': ['OPENAI_API_KEY']},
)

CHECK_PROGRESS_DESCRIPTOR = CapabilityDescriptor(
    name='check_video_generation_progress',
    version='0.1.0',
    granularity='tool',
    summary=('Check the progress of a running video generation task. '
             'Returns status and pipeline step completion info.'),
    description=(
        'Polls the status of a video generation task previously submitted '
        'via submit_video_generation_task. Inspects the output directory '
        'to report which pipeline steps have completed.'),
    input_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type':
                'string',
                'description':
                'The task_id returned by submit_video_generation_task',
            },
        },
        'required': ['task_id'],
    },
    tags=['video', 'generation', 'async', 'progress'],
    estimated_duration='seconds',
)

GET_RESULT_DESCRIPTOR = CapabilityDescriptor(
    name='get_video_generation_result',
    version='0.1.0',
    granularity='tool',
    summary=('Retrieve the result from a completed video generation task. '
             'Returns the video file path and pipeline artifacts.'),
    description=(
        'Returns the path to the final MP4 video and information about '
        'intermediate artifacts (script, segments, images, audio).'),
    input_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type':
                'string',
                'description':
                'The task_id returned by submit_video_generation_task',
            },
        },
        'required': ['task_id'],
    },
    tags=['video', 'generation', 'async', 'result'],
    estimated_duration='seconds',
)

SYNC_DESCRIPTOR = CapabilityDescriptor(
    name='video_generation',
    version='0.1.0',
    granularity='project',
    summary=
    ('Generate a short video synchronously (BLOCKS until complete, ~20 min). '
     'Prefer submit_video_generation_task for non-blocking usage.'),
    description=(
        'Synchronous version that blocks until video generation is complete. '
        'WARNING: This typically takes ~20 minutes. Use '
        'submit_video_generation_task + check_video_generation_progress + '
        'get_video_generation_result for non-blocking async operation.'),
    input_schema={
        'type': 'object',
        'properties': _CINEMA_INPUT_PROPERTIES,
        'required': ['query'],
    },
    tags=['video', 'generation', 'cinema', 'multimedia', 'sync'],
    estimated_duration='hours',
    requires={'env': ['OPENAI_API_KEY']},
)


def _find_default_config() -> str | None:
    candidates = [
        os.path.join(
            os.path.dirname(__file__), '..', '..', '..', 'projects',
            'singularity_cinema'),
    ]
    try:
        from importlib import resources as importlib_resources
        trav = importlib_resources.files('ms_agent').joinpath(
            'projects', 'singularity_cinema')
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
               extra_args: dict[str, str] | None = None) -> list[str]:
    cmd = [
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
    if extra_args:
        for k, v in extra_args.items():
            if v:
                cmd.extend([f'--{k}', str(v)])
    return cmd


def _extract_extra_args(args: dict[str, Any]) -> dict[str, str]:
    mapping = {
        'llm_model': 'llm.model',
        'llm_api_key': 'openai_api_key',
        'llm_base_url': 'openai_base_url',
        'image_generator_type': 'image_generator.type',
        'image_generator_model': 'image_generator.model',
        'image_generator_api_key': 'image_generator.api_key',
    }
    extra: dict[str, str] = {}
    for param_key, cli_key in mapping.items():
        val = args.get(param_key)
        if val:
            extra[cli_key] = str(val)
    return extra


def _check_pipeline_steps(output_dir: str) -> dict[str, Any]:
    """Inspect output_dir to determine which pipeline steps have completed."""
    if not os.path.isdir(output_dir):
        return {'completed_steps': [], 'total_steps': 9}

    steps: list[str] = []
    if os.path.isfile(os.path.join(output_dir, 'script.txt')):
        steps.append('generate_script')
    if os.path.isfile(os.path.join(output_dir, 'segments.txt')):
        steps.append('segment')

    audio_dir = os.path.join(output_dir, 'audio')
    if os.path.isdir(audio_dir) and list(Path(audio_dir).glob('*.mp3')):
        steps.append('generate_audio')

    prompts_dir = os.path.join(output_dir, 'illustration_prompts')
    if os.path.isdir(prompts_dir) and list(Path(prompts_dir).glob('*.txt')):
        steps.append('generate_prompts')

    images_dir = os.path.join(output_dir, 'images')
    if os.path.isdir(images_dir) and list(Path(images_dir).glob('*.png')):
        steps.append('generate_images')

    remotion_dir = os.path.join(output_dir, 'remotion_code')
    if os.path.isdir(remotion_dir) and list(Path(remotion_dir).glob('*.tsx')):
        steps.append('generate_animation')

    render_dir = os.path.join(output_dir, 'remotion_render')
    if os.path.isdir(render_dir) and list(Path(render_dir).rglob('*.mov')):
        steps.append('render_animation')

    if os.path.isfile(os.path.join(output_dir, 'background.jpg')):
        steps.append('create_background')

    final_video = os.path.join(output_dir, 'final_video.mp4')
    if os.path.isfile(final_video):
        steps.append('compose_video')

    images_count = (
        len(list(Path(images_dir).glob('*.png')))
        if os.path.isdir(images_dir) else 0)
    audio_count = (
        len(list(Path(audio_dir).glob('*.mp3')))
        if os.path.isdir(audio_dir) else 0)

    return {
        'completed_steps': steps,
        'total_steps': 9,
        'images_generated': images_count,
        'audio_segments': audio_count,
        'final_video_ready': os.path.isfile(final_video),
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
    pipeline = _check_pipeline_steps(output_dir)
    result = {
        'query': task.metadata.get('query', ''),
        'output_dir': output_dir,
        **pipeline,
    }
    log_tail = _read_log_tail(task.metadata.get('log_path', ''))
    if log_tail:
        result['log_tail'] = log_tail
    return result


async def _background_video_gen(task: AsyncTask) -> dict[str, Any]:
    query = task.metadata['query']
    config_path = task.metadata['config_path']
    output_dir = task.metadata['output_dir']
    extra_args = task.metadata.get('extra_args', {})

    log_path = os.path.join(output_dir, 'ms_agent.log')
    task.metadata['log_path'] = log_path

    cmd = _build_cmd(config_path, query, output_dir, extra_args)
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
        final_video = os.path.join(output_dir, 'final_video.mp4')
        pipeline = _check_pipeline_steps(output_dir)
        return {
            'video_path': final_video if os.path.isfile(final_video) else '',
            'output_dir': output_dir,
            **pipeline,
        }
    else:
        with open(log_path, 'r', errors='replace') as f:
            stderr_tail = f.read()[-2000:]
        raise RuntimeError(stderr_tail)


async def _handle_submit(args: dict[str, Any],
                         **kwargs: Any) -> dict[str, Any]:
    query: str = args['query']
    config_path = args.get('config_path', '') or _find_default_config() or ''
    output_dir = args.get('output_dir', '')
    extra_args = _extract_extra_args(args)

    if not config_path or not os.path.isdir(config_path):
        return {'error': f'Config directory not found: {config_path}'}

    if not output_dir:
        ts = time.strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.abspath(f'output/video_generation_{ts}')
    os.makedirs(output_dir, exist_ok=True)

    task = _manager.submit(
        task_type='video_generation',
        coroutine_fn=_background_video_gen,
        metadata={
            'query': query,
            'config_path': config_path,
            'output_dir': output_dir,
            'extra_args': extra_args,
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
        (f'Video generation task {task.task_id} started. '
         f'Use check_video_generation_progress(task_id="{task.task_id}") '
         f'to poll status.'),
    }


async def _handle_check_progress(args: dict[str, Any],
                                 **kwargs: Any) -> dict[str, Any]:
    return _manager.check(args['task_id'], progress_fn=_progress_fn)


async def _handle_get_result(args: dict[str, Any],
                             **kwargs: Any) -> dict[str, Any]:
    task_id: str = args['task_id']
    task = _manager.get(task_id)

    if task is None:
        return {'error': f'Unknown task_id: {task_id}'}

    if task.status == 'running':
        pipeline = _check_pipeline_steps(task.metadata.get('output_dir', ''))
        return {
            'task_id':
            task_id,
            'status':
            'running',
            'message':
            ('Video generation is still in progress. '
             f'Steps completed: {len(pipeline["completed_steps"])}/9 '
             f'({", ".join(pipeline["completed_steps"]) or "starting..."}).'),
        }

    if task.status == 'failed':
        return {'task_id': task_id, 'status': 'failed', 'error': task.error}

    output_dir = task.metadata.get('output_dir', '')
    final_video = os.path.join(output_dir, 'final_video.mp4')
    pipeline = _check_pipeline_steps(output_dir)

    result: dict[str, Any] = {
        'task_id': task_id,
        'status': 'completed',
        'output_dir': output_dir,
        **pipeline,
    }

    if os.path.isfile(final_video):
        result['video_path'] = final_video
        result['video_size_mb'] = round(
            os.path.getsize(final_video) / (1024 * 1024), 2)
    else:
        result['video_path'] = ''
        result['warning'] = 'final_video.mp4 not found in output directory'

    script_path = os.path.join(output_dir, 'script.txt')
    if os.path.isfile(script_path):
        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                result['script'] = f.read()[:5000]
        except Exception:
            pass

    return result


async def _handle_sync(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    query: str = args['query']
    config_path = args.get('config_path', '') or _find_default_config() or ''
    output_dir = args.get('output_dir', '')
    extra_args = _extract_extra_args(args)

    if not config_path or not os.path.isdir(config_path):
        return {
            'status': 'failed',
            'error': f'Config not found: {config_path}'
        }

    if not output_dir:
        ts = time.strftime('%Y%m%d_%H%M%S')
        output_dir = os.path.abspath(f'output/video_generation_{ts}')
    os.makedirs(output_dir, exist_ok=True)

    cmd = _build_cmd(config_path, query, output_dir, extra_args)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            cwd=config_path,
        )
        stderr = await proc.stderr.read()
        await proc.wait()
        final_video = os.path.join(output_dir, 'final_video.mp4')
        if proc.returncode == 0:
            return {
                'status': 'completed',
                'output_dir': output_dir,
                'video_path':
                final_video if os.path.isfile(final_video) else '',
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
    registry.register(GET_RESULT_DESCRIPTOR, _handle_get_result)
    registry.register(SYNC_DESCRIPTOR, _handle_sync)
