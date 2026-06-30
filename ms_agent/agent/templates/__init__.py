# Copyright (c) Alibaba, Inc. and its affiliates.
"""Built-in template agents (general / plan / explore / build / research).

Importing this package also registers the built-in harness callbacks
(``stop_gate``, ``round_reminder``, ``model_quality_check``) into
``ms_agent.callbacks.callbacks_mapping`` so templates can reference them in
``callbacks:`` without ``trust_remote_code``. The import is best-effort: a
failure here must never break config loading.
"""
from .registry import (get_when_to_use, list_templates, load_manifest,
                       resolve_template_dir, resolve_template_source)

try:  # best-effort harness registration; see templates/harness/__init__.py
    from . import harness  # noqa: F401
except Exception:  # pragma: no cover - harness is optional
    pass

__all__ = [
    'resolve_template_source',
    'resolve_template_dir',
    'load_manifest',
    'list_templates',
    'get_when_to_use',
]
