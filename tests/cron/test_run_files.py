"""Preserve every cron result when runs finish in the same second."""
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from ms_agent.cron.executor import JobExecutor
from ms_agent.cron.manager import JobManager
from ms_agent.cron.types import CronJobSpec


class EchoEngine:

    async def run(self, prompt):
        await asyncio.sleep(0)
        return prompt


@pytest.mark.asyncio
@pytest.mark.parametrize('concurrent', [False, True])
async def test_same_second_runs_keep_both_outputs(tmp_path, monkeypatch,
                                                concurrent):
    monkeypatch.setattr('ms_agent.cron.executor.time.strftime',
                        lambda *args: '2026-09-22_12-00-00')
    executor = JobExecutor(output_dir=tmp_path / 'output')
    monkeypatch.setattr(executor, '_build_engine', lambda *args: EchoEngine())
    jobs = [
        CronJobSpec(id='report', prompt=prompt, concurrency=2)
        for prompt in ['first result', '第二份结果']
    ]

    if concurrent:
        results = await asyncio.gather(
            *(executor.execute(job, config=None) for job in jobs))
    else:
        results = [await executor.execute(job, config=None) for job in jobs]

    assert all(result.success for result in results)
    files = list((tmp_path / 'output' / 'report').glob('*.md'))
    assert len(files) == 2
    assert {path.read_text(encoding='utf-8') for path in files} == {
        job.prompt for job in jobs
    }
    if not concurrent:
        manager = JobManager(tmp_path)
        assert manager.get_output('report', 0) == jobs[0].prompt
        assert manager.get_output('report') == jobs[1].prompt


def test_multiple_executors_preserve_existing_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr('ms_agent.cron.executor.time.strftime',
                        lambda *args: '2026-09-22_12-00-00')
    monkeypatch.setattr('ms_agent.cron.executor.time.time_ns',
                        lambda: 1_790_035_200_000_000_000)
    job_dir = tmp_path / 'report'
    job_dir.mkdir()
    old_output = job_dir / '2026-09-22_12-00-00.md'
    old_output.write_text('existing result', encoding='utf-8')
    outputs = [f'result {index}' for index in range(8)]

    def write(output):
        JobExecutor(output_dir=tmp_path)._write_output('report', output)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, outputs))

    assert old_output.read_text(encoding='utf-8') == 'existing result'
    files = list(job_dir.glob('*.md'))
    assert len(files) == 9
    assert {path.read_text(encoding='utf-8') for path in files} == {
        'existing result', *outputs
    }
