# Copyright (c) ModelScope Contributors. All rights reserved.
"""Whether a search engine can be imported, and the sentence to show when not.

The pip name is the thing a person can run. It is not always the import name
(``exa-py`` imports as ``exa_py``, ``google-search-results`` as ``serpapi``).
Tavily has no third-party package. A missing key is reported by the key
column, not by this sentence.
"""
from __future__ import annotations

import importlib
from typing import Iterable, Mapping, Optional

# engine id -> distribution name on PyPI
_PIP_NAME = {
    'arxiv': 'arxiv',
    'exa': 'exa-py',
    'serpapi': 'google-search-results',
}
# engine id -> module importlib should load
_IMPORT_NAME = {
    'arxiv': 'arxiv',
    'exa': 'exa_py',
    'serpapi': 'serpapi',
}


def _missing_pip(engine: str) -> Optional[str]:
    pip_name = _PIP_NAME.get(engine)
    import_name = _IMPORT_NAME.get(engine)
    if not pip_name or not import_name:
        return None
    try:
        importlib.import_module(import_name)
    except ModuleNotFoundError:
        return pip_name
    return None


def unavailable_notice(engine: str, *, has_key: bool,
                       requires_key: bool) -> Optional[str]:
    """One operable sentence, or None when this engine is not blocked on a package.

    ``requires_key and not has_key`` stays on the key line. Installing a
    package would not make that engine run.
    """
    if requires_key and not has_key:
        return None
    pip_name = _missing_pip(engine)
    if not pip_name:
        return None
    return (f'UNAVAILABLE: Package `{pip_name}` is not installed. '
            f'Run: pip install {pip_name}, then restart ms-agent.')


def notices_for_engines(engines: Iterable[str],
                        api_keys: Mapping[str, object],
                        requires_key) -> Optional[str]:
    """Join per-engine package sentences for a live web-search tool.

    ``requires_key`` is ``search_settings.requires_key``. One engine keeps its
    sentence intact. Several missing packages share a single UNAVAILABLE label.
    """
    lines = []
    for engine in engines:
        line = unavailable_notice(
            engine,
            has_key=bool(api_keys.get(engine)),
            requires_key=requires_key(engine),
        )
        if line:
            lines.append(line)
    if not lines:
        return None
    if len(lines) == 1:
        return lines[0]
    bodies = [line.split(': ', 1)[1] for line in lines]
    return 'UNAVAILABLE: ' + ' '.join(bodies)
