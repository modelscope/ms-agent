"""Tests for ms_agent.cron.parser."""
import pytest

from ms_agent.cron.parser import parse_schedule, compute_next_run, advance_next_run
from ms_agent.cron.types import CronSchedule


class TestParseScheduleCron:
    def test_standard_five_field(self):
        result = parse_schedule('0 9 * * *')
        assert result.kind == 'cron'
        assert result.expr == '0 9 * * *'

    def test_every_minute(self):
        result = parse_schedule('* * * * *')
        assert result.kind == 'cron'
        assert result.expr == '* * * * *'

    def test_complex_cron(self):
        result = parse_schedule('*/5 9-17 * * 1-5')
        assert result.kind == 'cron'

    def test_cron_with_timezone(self):
        result = parse_schedule('0 9 * * * Asia/Shanghai')
        assert result.kind == 'cron'
        assert result.expr == '0 9 * * *'
        assert result.timezone == 'Asia/Shanghai'

    def test_default_timezone(self):
        result = parse_schedule('0 9 * * *', default_timezone='US/Eastern')
        assert result.timezone == 'US/Eastern'


class TestParseScheduleInterval:
    def test_every_seconds(self):
        result = parse_schedule('every 60s')
        assert result.kind == 'interval'
        assert result.interval_seconds == 60

    def test_every_minutes(self):
        result = parse_schedule('every 30m')
        assert result.kind == 'interval'
        assert result.interval_seconds == 1800

    def test_every_hours(self):
        result = parse_schedule('every 2h')
        assert result.kind == 'interval'
        assert result.interval_seconds == 7200

    def test_every_days(self):
        result = parse_schedule('every 1d')
        assert result.kind == 'interval'
        assert result.interval_seconds == 86400

    def test_verbose_units(self):
        result = parse_schedule('every 5 minutes')
        assert result.kind == 'interval'
        assert result.interval_seconds == 300

    def test_case_insensitive(self):
        result = parse_schedule('Every 10M')
        assert result.kind == 'interval'
        assert result.interval_seconds == 600


class TestParseScheduleOnce:
    def test_iso_timestamp(self):
        result = parse_schedule('2025-06-01T09:00:00')
        assert result.kind == 'once'
        assert result.run_at == '2025-06-01T09:00:00'

    def test_iso_with_space(self):
        result = parse_schedule('2025-06-01 09:00:00')
        assert result.kind == 'once'


class TestParseScheduleErrors:
    def test_empty_string(self):
        with pytest.raises(ValueError, match='Empty'):
            parse_schedule('')

    def test_invalid_expression(self):
        with pytest.raises(ValueError):
            parse_schedule('not a schedule')

    def test_too_few_cron_fields(self):
        with pytest.raises(ValueError):
            parse_schedule('0 9 *')

    def test_invalid_cron_expression(self):
        with pytest.raises(ValueError):
            parse_schedule('99 99 99 99 99')


class TestComputeNextRun:
    def test_interval_returns_future(self):
        sched = CronSchedule(kind='interval', interval_seconds=60)
        result = compute_next_run(sched)
        assert result is not None
        assert '+00:00' in result

    def test_once_returns_run_at(self):
        sched = CronSchedule(kind='once', run_at='2099-01-01T00:00:00')
        result = compute_next_run(sched)
        assert result == '2099-01-01T00:00:00'

    def test_cron_returns_future(self):
        sched = CronSchedule(kind='cron', expr='* * * * *')
        result = compute_next_run(sched)
        assert result is not None


class TestAdvanceNextRun:
    def test_once_returns_none(self):
        sched = CronSchedule(kind='once', run_at='2025-01-01T00:00:00')
        assert advance_next_run(sched, '2025-01-01T00:00:00') is None

    def test_interval_advances(self):
        sched = CronSchedule(kind='interval', interval_seconds=3600)
        result = advance_next_run(sched, '2020-01-01T00:00:00+00:00')
        assert result is not None

    def test_cron_advances(self):
        sched = CronSchedule(kind='cron', expr='0 * * * *')
        result = advance_next_run(sched, '2020-01-01T00:00:00+00:00')
        assert result is not None
