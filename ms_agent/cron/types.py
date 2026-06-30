from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass
class CronSchedule:
    kind: Literal['cron', 'interval', 'once'] = 'once'
    expr: Optional[str] = None
    interval_seconds: Optional[int] = None
    run_at: Optional[str] = None
    timezone: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CronSchedule':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class RepeatSpec:
    times: Optional[int] = None
    completed: int = 0

    def is_exhausted(self) -> bool:
        return self.times is not None and self.completed >= self.times

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RepeatSpec':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class NotifySpec:
    on_error: bool = True
    on_success: bool = False
    hooks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NotifySpec':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CronJobSpec:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ''
    enabled: bool = True
    schedule: CronSchedule = field(default_factory=lambda: CronSchedule(kind='once'))
    source: Literal['dynamic', 'declarative'] = 'dynamic'

    prompt: Optional[str] = None
    project: Optional[str] = None
    workflow: Optional[str] = None

    session_mode: Literal['isolated', 'persistent'] = 'isolated'
    overrides: Optional[Dict[str, Any]] = None
    timeout: Optional[int] = None
    max_retries: int = 0
    trust_remote_code: bool = False

    repeat: Optional[RepeatSpec] = None
    concurrency: int = 1

    notify: Optional[NotifySpec] = None
    silent_on_success: bool = True

    created_at: str = field(default_factory=lambda: time.strftime('%Y-%m-%dT%H:%M:%S'))

    def to_dict(self) -> Dict[str, Any]:
        d = {}
        for k, v in asdict(self).items():
            if v is not None:
                d[k] = v
            elif k in ('prompt', 'project', 'workflow', 'overrides', 'timeout',
                       'repeat', 'notify'):
                continue
            else:
                d[k] = v
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CronJobSpec':
        d = dict(data)
        if 'schedule' in d and isinstance(d['schedule'], dict):
            d['schedule'] = CronSchedule.from_dict(d['schedule'])
        if 'repeat' in d and isinstance(d['repeat'], dict):
            d['repeat'] = RepeatSpec.from_dict(d['repeat'])
        if 'notify' in d and isinstance(d['notify'], dict):
            d['notify'] = NotifySpec.from_dict(d['notify'])
        valid_fields = set(cls.__dataclass_fields__.keys())
        d = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**d)


@dataclass
class RunRecord:
    run_at: str = ''
    duration_ms: int = 0
    status: Literal['ok', 'error'] = 'ok'
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d['error'] is None:
            del d['error']
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RunRecord':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CronJobState:
    status: Literal['scheduled', 'running', 'paused', 'completed', 'error'] = 'scheduled'
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    last_status: Optional[Literal['ok', 'error']] = None
    last_error: Optional[str] = None
    last_duration_ms: Optional[int] = None
    run_count: int = 0
    error_count: int = 0
    run_history: List[RunRecord] = field(default_factory=list)

    MAX_HISTORY: int = field(default=20, repr=False)

    def record_run(self, record: RunRecord) -> None:
        self.run_history.append(record)
        if len(self.run_history) > self.MAX_HISTORY:
            self.run_history = self.run_history[-self.MAX_HISTORY:]
        self.last_run_at = record.run_at
        self.last_duration_ms = record.duration_ms
        self.last_status = record.status
        self.last_error = record.error
        self.run_count += 1
        if record.status == 'error':
            self.error_count += 1

    def to_dict(self) -> Dict[str, Any]:
        d = {
            'status': self.status,
            'next_run_at': self.next_run_at,
            'last_run_at': self.last_run_at,
            'last_status': self.last_status,
            'last_error': self.last_error,
            'last_duration_ms': self.last_duration_ms,
            'run_count': self.run_count,
            'error_count': self.error_count,
            'run_history': [r.to_dict() for r in self.run_history],
        }
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CronJobState':
        d = dict(data)
        if 'run_history' in d:
            d['run_history'] = [
                RunRecord.from_dict(r) if isinstance(r, dict) else r
                for r in d['run_history']
            ]
        valid_fields = set(cls.__dataclass_fields__.keys())
        d = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**d)


@dataclass
class ExecutionResult:
    success: bool = False
    output: str = ''
    error: Optional[str] = None
    duration_ms: int = 0
