# Copyright (c) ModelScope Contributors. All rights reserved.
"""Load default workspace templates for each framework."""

from pathlib import Path
from typing import Dict

from ms_agent.utils.logger import get_logger

logger = get_logger()

_DEFAULTS_DIR = Path(__file__).parent / 'default_configs'


def get_defaults(framework: str) -> Dict[str, str]:
    """Read all files under ``defaults/{framework}/`` and return {rel_path: content}.

    Returns an empty dict if the framework directory doesn't exist or is empty.
    """
    framework_dir = _DEFAULTS_DIR / framework
    if not framework_dir.is_dir():
        return {}
    result: Dict[str, str] = {}
    for f in sorted(framework_dir.rglob('*')):
        if not f.is_file():
            continue
        try:
            rel = str(f.relative_to(framework_dir))
            result[rel] = f.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as e:
            logger.debug('Skip default file %s: %s', f, e)
    return result
