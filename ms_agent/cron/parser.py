"""Unified schedule string parser.

Supported formats:
  - cron: standard 5-field cron expression, e.g. "0 9 * * *"
  - interval: "every <N><unit>" where unit is s/m/h/d, e.g. "every 30m"
  - once: ISO 8601 timestamp, e.g. "2025-01-01T09:00:00"

Optional timezone suffix: "0 9 * * * Asia/Shanghai"
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from ms_agent.cron.types import CronSchedule

_INTERVAL_RE = re.compile(
    r'^every\s+(\d+)\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)$',
    re.IGNORECASE,
)

_UNIT_TO_SECONDS = {
    's': 1, 'sec': 1, 'secs': 1, 'second': 1, 'seconds': 1,
    'm': 60, 'min': 60, 'mins': 60, 'minute': 60, 'minutes': 60,
    'h': 3600, 'hr': 3600, 'hrs': 3600, 'hour': 3600, 'hours': 3600,
    'd': 86400, 'day': 86400, 'days': 86400,
}

_ISO_RE = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}')


def _try_import_croniter():
    try:
        from croniter import croniter
        return croniter
    except ImportError:
        raise ImportError(
            'croniter is required for cron expressions. '
            'Install it with: pip install croniter>=1.3.0'
        )


def _validate_cron_expr(expr: str) -> None:
    croniter_cls = _try_import_croniter()
    if not croniter_cls.is_valid(expr):
        raise ValueError(f'Invalid cron expression: {expr!r}')


def parse_schedule(schedule_str: str, default_timezone: Optional[str] = None) -> CronSchedule:
    """Parse a schedule string into a CronSchedule.

    Args:
        schedule_str: The schedule expression.
        default_timezone: Fallback IANA timezone if none in the expression.

    Returns:
        CronSchedule instance.

    Raises:
        ValueError: If the expression cannot be parsed.
    """
    raw = schedule_str.strip()
    if not raw:
        raise ValueError('Empty schedule string')

    # 1. Try interval: "every 30m", "every 1h", etc.
    m = _INTERVAL_RE.match(raw)
    if m:
        count = int(m.group(1))
        unit = m.group(2).lower()
        seconds = count * _UNIT_TO_SECONDS[unit]
        if seconds <= 0:
            raise ValueError(f'Interval must be positive, got {count}{unit}')
        return CronSchedule(
            kind='interval',
            interval_seconds=seconds,
            timezone=default_timezone,
        )

    # 2. Try ISO timestamp for one-shot: "2025-01-01T09:00:00"
    if _ISO_RE.match(raw):
        return CronSchedule(
            kind='once',
            run_at=raw,
            timezone=default_timezone,
        )

    # 3. Try cron expression (possibly with trailing timezone)
    parts = raw.split()
    tz = None

    if len(parts) == 6:
        tz = parts[5]
        expr = ' '.join(parts[:5])
    elif len(parts) == 5:
        expr = raw
    else:
        raise ValueError(
            f'Cannot parse schedule: {raw!r}. '
            f'Expected cron (5 fields), "every <N><unit>", or ISO timestamp.'
        )

    _validate_cron_expr(expr)
    return CronSchedule(
        kind='cron',
        expr=expr,
        timezone=tz or default_timezone,
    )


def compute_next_run(schedule: CronSchedule, base_time: Optional[datetime] = None) -> Optional[str]:
    """Compute the next run time as ISO 8601 string.

    Args:
        schedule: The CronSchedule to compute from.
        base_time: Reference time (defaults to now).

    Returns:
        ISO 8601 string, or None if no next run (e.g. expired once).
    """
    if base_time is None:
        base_time = datetime.now(timezone.utc)

    if schedule.kind == 'cron':
        croniter_cls = _try_import_croniter()
        import pytz
        tz = pytz.timezone(schedule.timezone) if schedule.timezone else timezone.utc
        local_base = base_time.astimezone(tz)
        cron = croniter_cls(schedule.expr, local_base)
        next_dt = cron.get_next(datetime)
        return next_dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')

    elif schedule.kind == 'interval':
        from datetime import timedelta
        next_dt = base_time + timedelta(seconds=schedule.interval_seconds)
        return next_dt.strftime('%Y-%m-%dT%H:%M:%S+00:00')

    elif schedule.kind == 'once':
        return schedule.run_at

    return None


def advance_next_run(schedule: CronSchedule, current_next: str) -> Optional[str]:
    """Advance past the current next_run to compute the subsequent one.

    For cron/interval schedules, computes the run *after* current_next.
    For once, returns None (no repeat).

    Handles expired schedules by fast-forwarding past ``now``.
    """
    if schedule.kind == 'once':
        return None

    try:
        base = datetime.fromisoformat(current_next.replace('+00:00', '+00:00'))
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        base = datetime.now(timezone.utc)

    now = datetime.now(timezone.utc)

    if schedule.kind == 'cron':
        croniter_cls = _try_import_croniter()
        import pytz
        tz = pytz.timezone(schedule.timezone) if schedule.timezone else timezone.utc
        local_base = base.astimezone(tz)
        cron = croniter_cls(schedule.expr, local_base)
        next_dt = cron.get_next(datetime)
        while next_dt.astimezone(timezone.utc) <= now:
            next_dt = cron.get_next(datetime)
        return next_dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')

    elif schedule.kind == 'interval':
        from datetime import timedelta
        step = timedelta(seconds=schedule.interval_seconds)
        candidate = base + step
        while candidate <= now:
            candidate += step
        return candidate.strftime('%Y-%m-%dT%H:%M:%S+00:00')

    return None
