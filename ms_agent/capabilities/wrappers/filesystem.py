# Copyright (c) ModelScope Contributors. All rights reserved.
import os
from typing import Any

from ms_agent.capabilities.descriptor import CapabilityDescriptor
from ms_agent.capabilities.registry import CapabilityRegistry

REPLACE_CONTENTS_DESCRIPTOR = CapabilityDescriptor(
    name='replace_file_contents',
    version='0.1.0',
    granularity='tool',
    summary=('Replace exact content in a file without line numbers. '
             'Concurrent-safe: matches by content instead of line numbers, '
             'so parallel edits on the same file do not conflict.'),
    description=
    ('Performs an exact-string replacement inside a file.  The caller supplies '
     'the verbatim `source` text to find and the `target` text to replace it with.  '
     'An `occurrence` parameter controls which match to replace (1-based) or '
     '-1 for all.  Because it relies on content matching rather than line numbers, '
     'it is safe to use from multiple agents editing the same file concurrently.'
     ),
    input_schema={
        'type': 'object',
        'properties': {
            'path': {
                'type':
                'string',
                'description':
                'Path to the file to modify (relative to workspace or absolute)',
            },
            'source': {
                'type':
                'string',
                'description':
                ('Exact content to find. Must match the file content verbatim '
                 'including whitespace, punctuation, and line breaks.'),
            },
            'target': {
                'type': 'string',
                'description': 'New content to replace the source with',
            },
            'occurrence': {
                'type':
                'integer',
                'description':
                ('Which occurrence to replace (1-based). '
                 'Use -1 to replace all occurrences. Default: 1'),
                'default':
                1,
            },
        },
        'required': ['path', 'source', 'target'],
    },
    output_schema={
        'type': 'object',
        'properties': {
            'result': {
                'type': 'string'
            },
        },
    },
    tags=['filesystem', 'edit', 'replace', 'diff', 'concurrent-safe'],
    estimated_duration='seconds',
)

REPLACE_LINES_DESCRIPTOR = CapabilityDescriptor(
    name='replace_file_lines',
    version='0.1.0',
    granularity='tool',
    summary=
    ('Replace, insert, or append content by line range. '
     'Supports insert-at-beginning (start_line=0) and append-at-end (start_line=-1).'
     ),
    description=(
        'Replaces a range of lines in a file with new content.  '
        'Special modes: start_line=0 inserts at the beginning, '
        'start_line=-1 appends at the end.  Line numbers are 1-based inclusive.'
    ),
    input_schema={
        'type': 'object',
        'properties': {
            'path': {
                'type': 'string',
                'description': 'Path to the file to modify',
            },
            'content': {
                'type': 'string',
                'description': 'New content to insert or replace with',
            },
            'start_line': {
                'type':
                'integer',
                'description':
                ('Start line (1-based inclusive). '
                 '0 = insert at beginning, -1 = append at end.'),
            },
            'end_line': {
                'type':
                'integer',
                'description':
                'End line (1-based inclusive). Required unless start_line is 0 or -1.',
            },
        },
        'required': ['path', 'content', 'start_line'],
    },
    output_schema={
        'type': 'object',
        'properties': {
            'result': {
                'type': 'string'
            },
        },
    },
    tags=['filesystem', 'edit', 'replace', 'lines'],
    estimated_duration='seconds',
)


def _resolve_path(path: str, workspace: str | None) -> str:
    """Resolve *path* against an optional workspace root."""
    if os.path.isabs(path):
        return path
    if workspace:
        return os.path.join(workspace, path)
    return os.path.abspath(path)


async def _handle_replace_contents(args: dict[str, Any],
                                   **kwargs: Any) -> dict[str, Any]:
    workspace = kwargs.get('workspace') or os.environ.get(
        'MS_AGENT_OUTPUT_DIR', '')
    path = _resolve_path(args['path'], workspace)
    source: str = args['source']
    target: str = args['target']
    occurrence: int = args.get('occurrence', 1)

    if not source:
        return {'error': '`source` must be a non-empty string'}
    if target is None:
        return {'error': '`target` is required'}
    if not os.path.isfile(path):
        return {'error': f'File not found: {path}'}

    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    if source not in content:
        return {
            'error': f'Could not find the exact content to replace in {path}'
        }

    count = content.count(source)

    if occurrence == -1:
        updated = content.replace(source, target)
        msg = f'Replaced all {count} occurrence(s)'
    elif occurrence < 1:
        return {'error': f'occurrence must be >= 1 or -1, got {occurrence}'}
    elif occurrence > count:
        return {'error': f'occurrence {occurrence} exceeds total ({count})'}
    else:
        parts = content.split(source, occurrence)
        updated = source.join(parts[:occurrence]) + target + source.join(
            parts[occurrence:])
        msg = f'Replaced occurrence {occurrence} of {count}'

    with open(path, 'w', encoding='utf-8') as f:
        f.write(updated)

    return {'result': f'{msg} in {path}'}


async def _handle_replace_lines(args: dict[str, Any],
                                **kwargs: Any) -> dict[str, Any]:
    workspace = kwargs.get('workspace') or os.environ.get(
        'MS_AGENT_OUTPUT_DIR', '')
    path = _resolve_path(args['path'], workspace)
    new_content: str = args['content']
    start_line: int = args['start_line']
    end_line: int | None = args.get('end_line')

    if os.path.isfile(path):
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    else:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        lines = []

    if new_content and not new_content.endswith('\n'):
        new_content += '\n'

    if start_line == 0:
        new_lines = [new_content] + lines
        operation = 'Inserted at beginning'
    elif start_line == -1:
        new_lines = lines + [new_content]
        operation = 'Appended at end'
    else:
        if end_line is None:
            return {'error': 'end_line is required when start_line > 0'}
        s = max(0, start_line - 1)
        e = min(len(lines), end_line)
        new_lines = lines[:s] + [new_content] + lines[e:]
        operation = f'Replaced lines {start_line}-{end_line}'

    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    return {'result': f'{operation} in {path}'}


def register_all(registry: CapabilityRegistry, config: Any = None) -> None:
    """Register filesystem capabilities into the registry."""
    registry.register(REPLACE_CONTENTS_DESCRIPTOR, _handle_replace_contents)
    registry.register(REPLACE_LINES_DESCRIPTOR, _handle_replace_lines)
