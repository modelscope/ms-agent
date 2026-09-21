# Copyright (c) ModelScope Contributors. All rights reserved.
import os
import shutil
from typing import Any

from ms_agent.capabilities.descriptor import CapabilityDescriptor
from ms_agent.capabilities.registry import CapabilityRegistry

# Maps each supported language to the executable that must be on ``$PATH`` and
# an actionable install hint. The descriptor-level ``requires`` mechanism is
# static, but the actual LSP backend depends on the runtime ``language``
# argument, so we validate here and surface a clear, install-ready message
# instead of an opaque "Failed to start LSP server" string.
_LANGUAGE_BACKENDS: dict[str, dict[str, str]] = {
    'typescript': {
        # 后端通过 npx 解析项目本地、全局或缓存安装，不要求全局语言服务器。
        'bin':
        'npx',
        'hint': ('install Node.js with npm; install typescript and '
                 'typescript-language-server in your project or globally'),
    },
    'python': {
        'bin': 'pyright-langserver',
        'hint': 'pip install pyright  (or: npm install -g pyright)',
    },
    'java': {
        'bin':
        'jdtls',
        'hint': ('brew install jdtls  '
                 '(or download the Eclipse JDT Language Server)'),
    },
}


def _check_language_backend(language: str) -> dict[str, Any] | None:
    """Return an actionable error dict when the LSP backend for *language* is
    unavailable, otherwise ``None``."""
    spec = _LANGUAGE_BACKENDS.get(language)
    if spec is None:
        return {
            'error':
            (f'Unsupported language {language!r}. '
             f'Supported languages: {", ".join(sorted(_LANGUAGE_BACKENDS))}.')
        }
    available = shutil.which(spec['bin'])
    if language == 'java' and not available:
        # JavaLanguageServer also supports these locations outside PATH.
        available = any(
            os.path.isfile(os.path.expanduser(path))
            for path in ('/usr/local/bin/jdtls', '/opt/homebrew/bin/jdtls',
                         '~/.local/bin/jdtls'))
    if not available:
        return {
            'error': (f'LSP backend for {language!r} is unavailable: '
                      f'executable "{spec["bin"]}" was not found on $PATH. '
                      f'Install it with: {spec["hint"]}')
        }
    return None


CHECK_DIRECTORY_DESCRIPTOR = CapabilityDescriptor(
    name='lsp_check_directory',
    version='0.1.0',
    granularity='component',
    summary=('Index code files in a directory with an LSP backend. '
             'Supports TypeScript/JavaScript, Python, and Java.'),
    description=(
        'Starts the appropriate Language Server Protocol backend '
        '(typescript-language-server, pyright, or jdtls) and opens matching '
        'files for indexing. Returns indexing status and file counts. '
        'Directory-wide diagnostic collection is currently disabled; '
        'use lsp_update_and_check for incremental diagnostics.'),
    input_schema={
        'type': 'object',
        'properties': {
            'directory': {
                'type':
                'string',
                'description':
                'Path to the directory to check (relative to workspace or absolute)',
            },
            'language': {
                'type':
                'string',
                'enum': ['typescript', 'python', 'java'],
                'description':
                ('Programming language to check. '
                 'typescript covers .ts/.tsx/.js/.jsx/.mjs/.cjs files'),
            },
        },
        'required': ['directory', 'language'],
    },
    output_schema={
        'type': 'object',
        'properties': {
            'result': {
                'type': 'string',
                'description': 'JSON-encoded indexing summary'
            },
        },
    },
    tags=[
        'code', 'lsp', 'diagnostics', 'validation', 'typescript', 'python',
        'java'
    ],
    estimated_duration='minutes',
    parent='lsp_code_server',
)

UPDATE_AND_CHECK_DESCRIPTOR = CapabilityDescriptor(
    name='lsp_update_and_check',
    version='0.1.0',
    granularity='tool',
    summary=(
        'Incrementally update a file and check for LSP errors. '
        'More efficient than a full directory check for single-file edits.'),
    description=(
        'Updates a file with new content and runs LSP diagnostics on it. '
        'The LSP server is reused across calls, making repeated checks on '
        'the same project very efficient.'),
    input_schema={
        'type': 'object',
        'properties': {
            'file_path': {
                'type':
                'string',
                'description':
                'Path to the file (relative to workspace or absolute)',
            },
            'content': {
                'type': 'string',
                'description': 'Updated file content to validate',
            },
            'language': {
                'type': 'string',
                'enum': ['typescript', 'python', 'java'],
                'description': 'Programming language of the file',
            },
        },
        'required': ['file_path', 'content', 'language'],
    },
    output_schema={
        'type': 'object',
        'properties': {
            'result': {
                'type': 'string',
                'description': 'Diagnostic output'
            },
        },
    },
    tags=['code', 'lsp', 'diagnostics', 'validation'],
    estimated_duration='seconds',
    parent='lsp_code_server',
)

LSP_SERVER_DESCRIPTOR = CapabilityDescriptor(
    name='lsp_code_server',
    version='0.1.0',
    granularity='component',
    summary=
    ('LSP-based code validation server supporting TypeScript, Python, and Java. '
     'Provides directory-wide and incremental file-level diagnostics.'),
    description=(
        'A component that wraps Language Server Protocol backends to provide '
        'code diagnostics without requiring an IDE. Sub-capabilities: '
        'lsp_check_directory (full project scan) and lsp_update_and_check '
        '(incremental single-file validation).'),
    input_schema={
        'type': 'object',
        'properties': {}
    },
    tags=['code', 'lsp', 'diagnostics', 'validation'],
    estimated_duration='minutes',
    sub_capabilities=['lsp_check_directory', 'lsp_update_and_check'],
)

_lsp_instances: dict[str, Any] = {}


def _get_lsp_server(workspace: str) -> Any:
    """Return an LSPCodeServer rooted at *workspace*.

    Instances are cached per workspace path so that repeated checks on
    the same project reuse the LSP server.
    """
    key = os.path.realpath(workspace)
    if key in _lsp_instances:
        return _lsp_instances[key]

    from types import SimpleNamespace

    from ms_agent.tools.code_server.lsp_code_server import LSPCodeServer

    config = SimpleNamespace(output_dir=workspace, tools=SimpleNamespace())
    lsp = LSPCodeServer(config)
    _lsp_instances[key] = lsp
    return lsp


def _resolve_workspace(directory: str, fallback: str) -> str:
    """Determine the LSP workspace root for *directory*.

    If *directory* is an absolute path, it becomes its own workspace root
    so pyright's rootUri encompasses the files being checked.
    """
    if os.path.isabs(directory):
        return directory
    return fallback


async def _handle_check_directory(args: dict[str, Any],
                                  **kwargs: Any) -> dict[str, Any]:
    backend_error = _check_language_backend(args.get('language', ''))
    if backend_error is not None:
        return backend_error

    fallback = kwargs.get('workspace') or os.environ.get(
        'MS_AGENT_OUTPUT_DIR', os.getcwd())
    directory = args['directory']
    workspace = _resolve_workspace(directory, fallback)
    lsp = _get_lsp_server(workspace)

    rel_dir = os.path.relpath(
        directory, workspace) if os.path.isabs(directory) else directory

    result = await lsp.call_tool(
        'lsp_code_server',
        tool_name='check_directory',
        tool_args={
            'directory': rel_dir,
            'language': args['language'],
        },
    )
    return {'result': result}


async def _handle_lsp_info(args: dict[str, Any],
                           **kwargs: Any) -> dict[str, Any]:
    """Handler for the parent ``lsp_code_server`` descriptor.

    The parent descriptor has no input parameters, so it must not be wired to
    the directory-check handler (which would raise ``KeyError('directory')``).
    Instead it describes the component and its callable sub-capabilities.
    """
    return {
        'component': 'lsp_code_server',
        'summary': LSP_SERVER_DESCRIPTOR.summary,
        'sub_capabilities': list(LSP_SERVER_DESCRIPTOR.sub_capabilities),
        'supported_languages': sorted(_LANGUAGE_BACKENDS),
    }


async def _handle_update_and_check(args: dict[str, Any],
                                   **kwargs: Any) -> dict[str, Any]:
    backend_error = _check_language_backend(args.get('language', ''))
    if backend_error is not None:
        return backend_error

    fallback = kwargs.get('workspace') or os.environ.get(
        'MS_AGENT_OUTPUT_DIR', os.getcwd())
    file_path = args['file_path']
    workspace = _resolve_workspace(
        os.path.dirname(file_path),
        fallback) if os.path.isabs(file_path) else fallback
    lsp = _get_lsp_server(workspace)

    rel_path = os.path.relpath(
        file_path, workspace) if os.path.isabs(file_path) else file_path

    result = await lsp.call_tool(
        'lsp_code_server',
        tool_name='update_and_check',
        tool_args={
            'file_path': rel_path,
            'content': args['content'],
            'language': args['language'],
        },
    )
    return {'result': result}


def register_all(registry: CapabilityRegistry, config: Any = None) -> None:
    """Register LSP code server capabilities into the registry."""
    # Parent component descriptor: describes sub-capabilities, does not run
    # diagnostics (it has no ``directory``/``language`` input).
    registry.register(LSP_SERVER_DESCRIPTOR, _handle_lsp_info)
    registry.register(CHECK_DIRECTORY_DESCRIPTOR, _handle_check_directory)
    registry.register(UPDATE_AND_CHECK_DESCRIPTOR, _handle_update_and_check)
