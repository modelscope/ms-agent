# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import os
import time
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

import json
from ms_agent.llm.utils import Message

from .logger import get_logger

logger = get_logger()

_STATS_LOCKS: Dict[str, asyncio.Lock] = {}


def _get_lock(path: str) -> asyncio.Lock:
    lock = _STATS_LOCKS.get(path)
    if lock is None:
        lock = asyncio.Lock()
        _STATS_LOCKS[path] = lock
    return lock


def get_stats_path(config: Any,
                   default_filename: str = 'workflow_stats.json') -> str:
    stats_file = getattr(config, 'stats_file', None)
    output_dir = getattr(config, 'output_dir', './output')
    if stats_file:
        if os.path.isabs(stats_file):
            return stats_file
        return os.path.join(output_dir, stats_file)
    return os.path.join(output_dir, default_filename)


def summarize_usage(messages: Optional[Iterable[Message]]) -> Dict[str, int]:
    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0
    cache_creation_input_tokens = 0
    api_calls = 0
    if messages:
        for msg in messages:
            if getattr(msg, 'role', None) != 'assistant':
                continue
            prompt_tokens += int(getattr(msg, 'prompt_tokens', 0) or 0)
            completion_tokens += int(getattr(msg, 'completion_tokens', 0) or 0)
            cached_tokens += int(getattr(msg, 'cached_tokens', 0) or 0)
            cache_creation_input_tokens += int(
                getattr(msg, 'cache_creation_input_tokens', 0) or 0)
            api_calls += int(getattr(msg, 'api_calls', 0) or 0)
    return {
        'prompt_tokens': prompt_tokens,
        'completion_tokens': completion_tokens,
        'total_tokens': prompt_tokens + completion_tokens,
        'cached_tokens': cached_tokens,
        'cache_creation_input_tokens': cache_creation_input_tokens,
        'api_calls': api_calls,
    }


async def append_stats(path: str, record: Dict[str, Any]) -> None:
    if not path:
        return
    lock = _get_lock(path)
    async with lock:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        data: list = []
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f) or []
            except Exception as exc:
                logger.warning(
                    f'Failed to read stats file {path}, resetting: {exc}')
                data = []
        if not isinstance(data, list):
            data = []

        record.setdefault('created_at', datetime.utcnow().isoformat())
        data.append(record)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=True, indent=2)


def build_timing_record(
        *,
        event: str,
        agent_tag: Optional[str],
        agent_type: Optional[str],
        started_at: str,
        ended_at: str,
        duration_s: float,
        status: str,
        usage: Optional[Dict[str, int]] = None,
        extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    record = {
        'event': event,
        'agent_tag': agent_tag,
        'agent_type': agent_type,
        'started_at': started_at,
        'ended_at': ended_at,
        'duration_s': round(duration_s, 6),
        'status': status,
        'usage': usage or {},
    }
    if extra:
        record.update(extra)
    return record


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def monotonic() -> float:
    return time.monotonic()
