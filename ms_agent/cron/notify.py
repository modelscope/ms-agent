"""Notification hooks for cron job completion (Phase 2).

Supports:
  - CallbackHook: in-process async callback
  - WebhookHook: HTTP POST to external URL
  - LogHook: simple logging notification
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ms_agent.cron.types import CronJobSpec, ExecutionResult, NotifySpec

logger = logging.getLogger(__name__)


class NotifyHook(ABC):
    """Abstract base for notification hooks."""

    @abstractmethod
    async def notify(self, job: CronJobSpec, result: ExecutionResult) -> None:
        ...


class CallbackHook(NotifyHook):
    """In-process callback hook."""

    def __init__(self, callback):
        self._callback = callback

    async def notify(self, job: CronJobSpec, result: ExecutionResult) -> None:
        await self._callback(job, result)


class WebhookHook(NotifyHook):
    """HTTP webhook notification.

    Sends a JSON POST with job info and result to the configured URL.
    """

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None):
        self._url = url
        self._headers = headers or {}

    async def notify(self, job: CronJobSpec, result: ExecutionResult) -> None:
        payload = {
            'job_id': job.id,
            'job_name': job.name,
            'success': result.success,
            'duration_ms': result.duration_ms,
            'error': result.error,
            'output_preview': result.output[:500] if result.output else None,
        }
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                headers = {'Content-Type': 'application/json'}
                headers.update(self._headers)
                async with session.post(
                    self._url,
                    data=json.dumps(payload, ensure_ascii=False),
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status >= 400:
                        logger.warning(
                            f'Webhook to {self._url} returned status {resp.status}'
                        )
        except ImportError:
            logger.warning(
                'aiohttp not installed; webhook notifications unavailable. '
                'Install with: pip install aiohttp'
            )
        except Exception as e:
            logger.warning(f'Webhook notification failed: {e}')


class LogHook(NotifyHook):
    """Simple logging notification — always available."""

    async def notify(self, job: CronJobSpec, result: ExecutionResult) -> None:
        status = 'OK' if result.success else 'ERROR'
        msg = f'[Cron] Job {job.id} ({job.name}) completed: {status} ({result.duration_ms}ms)'
        if result.error:
            msg += f' — {result.error}'
        logger.info(msg)


def build_hooks_from_spec(spec: Optional[NotifySpec]) -> List[NotifyHook]:
    """Build NotifyHook instances from a job's NotifySpec."""
    if spec is None:
        return []
    hooks: List[NotifyHook] = []
    for h in spec.hooks:
        kind = h.get('type', '')
        if kind == 'webhook':
            url = h.get('url', '')
            if url:
                hooks.append(WebhookHook(url=url, headers=h.get('headers')))
        elif kind == 'log':
            hooks.append(LogHook())
    return hooks
