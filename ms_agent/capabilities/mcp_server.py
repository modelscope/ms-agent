# Copyright (c) ModelScope Contributors. All rights reserved.
import argparse
import json
import logging
import os
import sys

from dotenv import find_dotenv, load_dotenv

from ms_agent.capabilities import create_registry

logger = logging.getLogger(__name__)


def _protect_stdout() -> None:
    """Replace sys.stdout with stderr so stray prints never corrupt the
    MCP stdio JSONRPC channel.

    FastMCP's stdio transport writes to the *original* stdout file
    descriptor, so replacing the Python-level ``sys.stdout`` object is
    safe: library code that accidentally does ``print()`` or
    ``sys.stdout.write()`` will be routed to stderr instead.
    """
    sys.stdout = sys.stderr


def _load_env(env_file: str | None = None) -> None:
    """Load environment variables from a ``.env`` file.

    *Existing* environment variables are **not** overwritten (``override=False``),
    so values set via the MCP client's ``env`` block or ``export`` always win.
    """
    if env_file:
        if not os.path.isfile(env_file):
            logger.warning('--env-file %s does not exist, skipping', env_file)
            return
        loaded_path = env_file
    else:
        loaded_path = find_dotenv(usecwd=True)

    if loaded_path:
        load_dotenv(loaded_path, override=False)
        logger.debug('Loaded env from %s', loaded_path)
    else:
        logger.debug('No .env file found')


def _print_check() -> None:
    """Quick health check: print available capabilities and exit."""
    registry = create_registry()
    caps = registry.list_all()
    info = {
        'status': 'ok',
        'capabilities': [
            {
                'name': c.name,
                'granularity': c.granularity,
                'summary': c.summary,
            }
            for c in caps
        ],
    }
    print(json.dumps(info, indent=2))


def main() -> None:
    """MCP Server adapter for the ms-agent Capability Gateway.

    Exposes registered capabilities over the Model Context Protocol so that any
    MCP-compatible client (nanobot, CoPaw, Cursor, Claude Desktop, ...) can
    discover and invoke ms-agent tools.

    Environment & API Keys
    ----------------------
    On startup the server loads environment variables from a ``.env`` file so that
    API keys (``OPENAI_API_KEY``, ``EXA_API_KEY``, ``SERPAPI_API_KEY``, etc.) are
    available to all capabilities and their subprocesses.  The lookup order is:

    1. Variables already set in the process environment (e.g. via the MCP
    client's ``env`` config block) — **highest priority**.
    2. An explicit ``--env-file /path/to/.env`` argument.
    3. Auto-discovered ``.env`` by walking up from the current directory.

    Usage
    -----
    Start as a stdio MCP server (the most common transport for local tools)::

        python -m ms_agent.capabilities.mcp_server

    With a specific env file::

        python -m ms_agent.capabilities.mcp_server --env-file /path/to/project/.env

    Or with a custom workspace directory::

        MS_AGENT_OUTPUT_DIR=/path/to/workspace python -m ms_agent.capabilities.mcp_server

    Configure in nanobot ``config.json``::

        {
            "tools": {
                "mcpServers": {
                    "ms-agent": {
                        "command": "python",
                        "args": ["-m", "ms_agent.capabilities.mcp_server"],
                        "env": {"MS_AGENT_OUTPUT_DIR": "/path/to/workspace"}
                    }
                }
            }
        }

    Configure in CoPaw MCP settings::

        {
            "transport": "stdio",
            "command": "python",
            "args": ["-m", "ms_agent.capabilities.mcp_server"]
        }
    """

    parser = argparse.ArgumentParser(
        description='ms-agent MCP Capability Server',
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Print available capabilities as JSON and exit',
    )
    parser.add_argument(
        '--transport',
        choices=['stdio', 'streamable-http'],
        default='stdio',
        help='MCP transport to use (default: stdio)',
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8765,
        help='Port for streamable-http transport (default: 8765)',
    )
    parser.add_argument(
        '--env-file',
        default=None,
        help='Path to .env file (auto-discovered if omitted)',
    )
    args = parser.parse_args()

    _load_env(args.env_file)

    if args.check:
        _print_check()
        return

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            'ERROR: The "mcp" package is required.  Install it with:\n  pip install mcp\n',
            file=sys.stderr,
        )
        sys.exit(1)

    registry = create_registry()
    workspace = os.environ.get('MS_AGENT_OUTPUT_DIR', os.getcwd())

    server = FastMCP(
        'ms-agent-capabilities',
        instructions=(
            'ms-agent Capability Gateway. Provides deep research, LSP code validation, and advanced file-editing tools.'
        ),
    )

    for cap in registry.list_all():
        if cap.granularity == 'project' and cap.sub_capabilities:
            # Project-level: register as a tool but note long duration in description
            _register_cap(server, registry, cap, workspace)
        elif cap.sub_capabilities and not cap.parent:
            # Parent component descriptor -- skip (children are registered individually)
            continue
        else:
            _register_cap(server, registry, cap, workspace)

    server.run(transport=args.transport)


def _build_handler(registry, cap, workspace: str):
    """Build a handler function with a proper signature for FastMCP.

    FastMCP uses ``inspect.signature()`` to discover parameters, so we
    dynamically create a function whose parameter list matches the
    capability's JSON Schema.
    """
    import inspect
    import typing

    properties = cap.input_schema.get('properties', {})
    required_params = set(cap.input_schema.get('required', []))

    type_map = {
        'string': str,
        'integer': int,
        'number': float,
        'boolean': bool,
    }

    params = []
    annotations = {}
    for pname, pschema in properties.items():
        py_type = type_map.get(pschema.get('type', 'string'), str)
        if pname in required_params:
            params.append(inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, annotation=py_type))
        else:
            opt_type = typing.Optional[py_type]
            default = pschema.get('default')
            params.append(
                inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=opt_type)
            )
        annotations[pname] = params[-1].annotation

    cap_name = cap.name

    async def handler(**kw):
        saved = sys.stdout
        sys.stdout = sys.stderr
        try:
            result = await registry.invoke(cap_name, kw, workspace=workspace)
        finally:
            sys.stdout = saved
        return json.dumps(result, ensure_ascii=False)

    handler.__name__ = cap_name
    handler.__qualname__ = cap_name
    handler.__signature__ = inspect.Signature(params)
    handler.__annotations__ = annotations
    return handler


def _register_cap(server, registry, cap, workspace: str) -> None:
    """Register a single capability as an MCP tool on *server*."""
    desc = cap.summary
    if cap.estimated_duration in ('minutes', 'hours'):
        desc += f' [estimated duration: {cap.estimated_duration}]'

    handler = _build_handler(registry, cap, workspace)
    handler.__doc__ = desc
    server.tool(name=cap.name, description=desc)(handler)


if __name__ == '__main__':
    main()
