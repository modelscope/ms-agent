# Copyright (c) ModelScope Contributors. All rights reserved.
"""Fingerprint of the LLM settings a live client was built from."""
from __future__ import annotations

import json

from omegaconf import OmegaConf


def llm_runtime_token(config) -> str:
    """Stable token for ``llm`` plus ``generation_config``.

    A change means the next turn should rebuild the client in place. The
    token stays in memory; it is not written to disk.
    """
    llm = OmegaConf.select(config, 'llm', default=None)
    gen = OmegaConf.select(config, 'generation_config', default=None)
    payload = {
        'llm':
        OmegaConf.to_container(llm, resolve=True) if llm is not None else None,
        'generation':
        OmegaConf.to_container(gen, resolve=True) if gen is not None else None,
    }
    return json.dumps(payload, sort_keys=True, default=str)
