"""Small owned async operation registry; persisted receipts survive restarts."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path

from ms_agent.utils.atomic_file import atomic_write_json

from .models import SkillManagementError, management_error


def serializable(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [serializable(item) for item in value]
    return value


class SkillOperations:

    def __init__(self, root: Path, on_complete=None):
        self.root = root
        self.tasks = {}
        self.records = {}
        self.on_complete = on_complete
        self.semaphore = asyncio.Semaphore(4)

    def submit(self, kind, scope, work, *, recovery_result=None):
        self.cleanup()
        identity = uuid.uuid4().hex
        row = {
            'id': identity,
            'kind': kind,
            'scope': scope,
            'status': 'queued',
            'phase': kind,
            'result': None,
            'error': None,
            'created_at': time.time(),
            'completed': 0,
            'total': None
        }
        self.records[identity] = row
        self._save(row)

        async def run():
            try:
                async with self.semaphore:
                    row['status'] = 'running'
                    result = serializable(await work())
                    row['result'] = result
                    if isinstance(result, list):
                        failed = sum(
                            x.get('status') == 'failed'
                            or x.get('remote_status') == 'failed'
                            for x in result)
                        row['status'] = ('failed' if failed == len(result)
                                         and failed else
                                         'partial' if failed else 'succeeded')
                        row['completed'] = row['total'] = len(result)
                    else:
                        row['status'] = 'succeeded'
            except asyncio.CancelledError:
                row['status'] = 'cancelled'
                if recovery_result:
                    row['result'] = recovery_result()
            except Exception as exc:
                row['status'] = 'failed'
                row['error'] = management_error(exc)
            finally:
                self._save(row)

        def finished(task):
            # A task cancelled before its first step never enters run/finally.
            if row['status'] in ('queued', 'running'):
                row['status'] = 'cancelled' if task.cancelled() else 'failed'
                self._save(row)
            self.tasks.pop(identity, None)
            if self.on_complete:
                self.on_complete(scope, kind)

        task = asyncio.create_task(run())
        self.tasks[identity] = task
        task.add_done_callback(finished)
        return dict(row)

    def progress(self, identity, results, total):
        row = self.records[identity]
        row.update(
            result=serializable(results), completed=len(results), total=total)
        self._save(row)

    def _save(self, row):
        atomic_write_json(self.root / (row['id'] + '.json'), row)

    def get(self, identity):
        if identity in self.records:
            return dict(self.records[identity])
        if len(identity) != 32 or any(c not in '0123456789abcdef'
                                      for c in identity):
            raise SkillManagementError('OPERATION_NOT_FOUND',
                                       'Operation not found.')
        try:
            row = json.loads((self.root /
                              (identity + '.json')).read_text('utf-8'))
        except (OSError, ValueError):
            raise SkillManagementError('OPERATION_NOT_FOUND',
                                       'Operation not found.') from None
        if row['status'] in ('running', 'queued'):
            row['status'] = 'interrupted'
            row['error'] = {
                'code': 'INTERRUPTED',
                'message': 'The service restarted.'
            }
        return row

    async def cancel(self, identity):
        self.get(identity)
        task = self.tasks.get(identity)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return self.get(identity)

    async def aclose(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def cleanup(self):
        cutoff = time.time() - 86400
        for path in self.root.glob('*.json'):
            if path.stem not in self.tasks and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                self.records.pop(path.stem, None)
