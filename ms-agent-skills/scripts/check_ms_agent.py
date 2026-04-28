# Copyright (c) ModelScope Contributors. All rights reserved.
import json
import subprocess
import sys


def check_import() -> dict:
    """Check that ms_agent is importable."""
    try:
        import ms_agent  # noqa: F401
        version = getattr(ms_agent, '__version__', 'unknown')
        return {'importable': True, 'version': version}
    except ImportError as e:
        return {'importable': False, 'error': str(e)}


def check_capabilities() -> dict:
    """Check that the capability registry can be created.

    Tries in-process import first; falls back to the MCP server --check
    subprocess (which handles module resolution via ``python -m``).
    """
    try:
        from ms_agent.capabilities import create_registry
        registry = create_registry()
        caps = registry.list_all()
        return {
            'registry_ok':
            True,
            'count':
            len(caps),
            'capabilities': [{
                'name': c.name,
                'granularity': c.granularity,
                'summary': c.summary,
                'tags': c.tags,
            } for c in caps],
        }
    except ImportError:
        # ms_agent may not be on sys.path (e.g. dev mode without pip install).
        # Fall back to subprocess check which uses ``-m`` resolution.
        try:
            result = subprocess.run(
                [
                    sys.executable, '-m', 'ms_agent.capabilities.mcp_server',
                    '--check'
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return {
                    'registry_ok': True,
                    'count': len(data.get('capabilities', [])),
                    'capabilities': data.get('capabilities', []),
                    'note':
                    'verified via subprocess (package not on sys.path)',
                }
        except Exception:
            pass
        return {
            'registry_ok': False,
            'error': 'ms_agent.capabilities not importable'
        }
    except Exception as e:
        return {'registry_ok': False, 'error': str(e)}


def check_mcp_server() -> dict:
    """Check that the MCP server can start in --check mode."""
    try:
        result = subprocess.run(
            [
                sys.executable, '-m', 'ms_agent.capabilities.mcp_server',
                '--check'
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return {'mcp_server_ok': True, 'details': data}
        else:
            return {'mcp_server_ok': False, 'error': result.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {
            'mcp_server_ok': False,
            'error': 'MCP server --check timed out'
        }
    except Exception as e:
        return {'mcp_server_ok': False, 'error': str(e)}


def check_mcp_package() -> dict:
    """Check that the mcp Python package is installed."""
    try:
        import mcp  # noqa: F401
        version = getattr(mcp, '__version__', 'unknown')
        return {'installed': True, 'version': version}
    except ImportError:
        return {
            'installed': False,
            'hint': 'Install with: pip install mcp',
        }


def main() -> None:
    report = {
        'ms_agent': check_import(),
        'mcp_package': check_mcp_package(),
        'capabilities': check_capabilities(),
        'mcp_server': check_mcp_server(),
    }

    all_ok = (
        report['ms_agent'].get('importable', False)
        and report['capabilities'].get('registry_ok', False)
        and report['mcp_server'].get('mcp_server_ok', False))
    report['overall_status'] = 'ok' if all_ok else 'issues_found'

    print(json.dumps(report, indent=2, ensure_ascii=False))

    if not all_ok:
        print('\n--- Issues ---', file=sys.stderr)
        if not report['ms_agent'].get('importable'):
            print(
                '  ms-agent is not installed. Run: pip install ms-agent',
                file=sys.stderr)
        if not report['mcp_package'].get('installed'):
            print(
                '  mcp package is not installed. Run: pip install mcp',
                file=sys.stderr)
        if not report['capabilities'].get('registry_ok'):
            print(
                f"  Registry error: {report['capabilities'].get('error')}",
                file=sys.stderr)
        if not report['mcp_server'].get('mcp_server_ok'):
            print(
                f"  MCP server error: {report['mcp_server'].get('error')}",
                file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
