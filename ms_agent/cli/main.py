# Copyright (c) Alibaba, Inc. and its affiliates.
import importlib.util
import subprocess
import sys
from typing import Dict, Optional

ROUTE_MAPPING: Dict[str, str] = {
    'run': 'ms_agent.cli.run',
}


def cli_main(route_mapping: Optional[Dict[str, str]] = None) -> None:
    """Entry point for the CLI application."""
    route_mapping = route_mapping or ROUTE_MAPPING
    argv = sys.argv[1:]
    method_name = argv[0].replace('_', '-')
    argv = argv[1:]
    file_path = importlib.util.find_spec(route_mapping[method_name]).origin
    python_cmd = sys.executable
    args = [python_cmd, file_path, *argv]
    print(f"run sh: `{' '.join(args)}`", flush=True)
    result = subprocess.run(args)
    if result.returncode != 0:
        sys.exit(result.returncode)


if __name__ == '__main__':
    cli_main()
