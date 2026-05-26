"""CLI sub-commands for ms-agent cron."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from .base import CLICommand


def subparser_func(args):
    return CronCMD(args)


class CronCMD(CLICommand):
    name = 'cron'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers: argparse.ArgumentParser):
        parser = parsers.add_parser(
            CronCMD.name,
            help='Manage cron (scheduled) tasks.',
        )
        sub = parser.add_subparsers(dest='cron_action', help='Cron sub-commands')

        # start
        p_start = sub.add_parser('start', help='Start the cron daemon.')
        p_start.add_argument('--foreground', action='store_true', help='Run in foreground.')
        p_start.add_argument('--workspace', type=str, default=None, help='Cron workspace path.')
        p_start.add_argument('--env', type=str, default=None, help='Path to .env file.')

        # stop
        sub.add_parser('stop', help='Stop the cron daemon.')

        # status
        sub.add_parser('status', help='Show scheduler status.')

        # tick
        p_tick = sub.add_parser('tick', help='Run a single scheduler tick.')
        p_tick.add_argument('--verbose', action='store_true')

        # list
        p_list = sub.add_parser('list', help='List cron jobs.')
        p_list.add_argument('--all', action='store_true', help='Include disabled jobs.')
        p_list.add_argument('--json', dest='json_output', action='store_true', help='JSON output.')

        # create
        p_create = sub.add_parser('create', help='Create a new cron job.')
        p_create.add_argument('schedule', type=str, help='Schedule expression.')
        p_create.add_argument('prompt', type=str, help='Task prompt.')
        p_create.add_argument('--name', type=str, default='', help='Job name.')
        p_create.add_argument('--project', type=str, default=None, help='Agent project path.')
        p_create.add_argument('--timeout', type=int, default=None, help='Timeout in seconds.')

        # pause
        p_pause = sub.add_parser('pause', help='Pause a job.')
        p_pause.add_argument('job_id', type=str)

        # resume
        p_resume = sub.add_parser('resume', help='Resume a paused job.')
        p_resume.add_argument('job_id', type=str)

        # run
        p_run = sub.add_parser('run', help='Run a job immediately.')
        p_run.add_argument('job_id', type=str)

        # remove
        p_remove = sub.add_parser('remove', help='Remove a job.')
        p_remove.add_argument('job_id', type=str)

        # history
        p_hist = sub.add_parser('history', help='Show job run history.')
        p_hist.add_argument('job_id', type=str)
        p_hist.add_argument('--limit', type=int, default=10)

        # output
        p_out = sub.add_parser('output', help='Show job output.')
        p_out.add_argument('job_id', type=str)
        p_out.add_argument('--last', action='store_true', help='Show latest output.')

        # import (Phase 2: declarative jobs.d/*.yaml)
        sub.add_parser('import', help='Import jobs from jobs.d/*.yaml declarations.')

        parser.set_defaults(func=subparser_func)

    def execute(self):
        action = getattr(self.args, 'cron_action', None)
        if not action:
            print('Usage: ms-agent cron <command>')
            print('Commands: start, stop, status, tick, list, create, pause, resume, run, remove, history, output')
            return

        # 'import' is a Python keyword; map to _cmd_import_jobs
        method_name = f'_cmd_{action}' if action != 'import' else '_cmd_import_jobs'
        handler = getattr(self, method_name, None)
        if handler:
            handler()
        else:
            print(f'Unknown cron command: {action}')
            sys.exit(1)

    def _get_service(self):
        from ms_agent.config.env import Env
        from ms_agent.cron.service import CronService

        env_path = getattr(self.args, 'env', None)
        Env.load_dotenv_into_environ(env_path)

        workspace = getattr(self.args, 'workspace', None)
        return CronService(workspace=workspace)

    def _cmd_start(self):
        service = self._get_service()
        if service.daemon_is_running():
            print(f'Cron daemon already running (PID {service.status().get("pid")}).')
            return

        foreground = getattr(self.args, 'foreground', False)
        if foreground:
            print(f'Starting cron daemon in foreground (workspace: {service.workspace})')
            asyncio.run(service.run_forever())
        else:
            pid = os.fork()
            if pid > 0:
                print(f'Cron daemon started (PID {pid}, workspace: {service.workspace})')
                return
            os.setsid()
            asyncio.run(service.run_forever())

    def _cmd_stop(self):
        service = self._get_service()
        if service.stop_daemon():
            print('Cron daemon stopped.')
        else:
            print('No running cron daemon found.')

    def _cmd_status(self):
        service = self._get_service()
        info = service.status()
        daemon_running = service.daemon_is_running()
        print(f'Daemon running: {daemon_running}')
        print(f'Workspace: {info["workspace"]}')
        print(f'Job count: {info["job_count"]}')
        if daemon_running:
            print(f'PID: {info["pid"]}')

    def _cmd_tick(self):
        service = self._get_service()
        count = asyncio.run(service.manual_tick())
        verbose = getattr(self.args, 'verbose', False)
        if verbose:
            print(f'Tick completed: {count} due job(s) processed.')
        elif count > 0:
            print(f'{count} job(s) executed.')
        else:
            print('No due jobs.')

    def _cmd_list(self):
        service = self._get_service()
        include_all = getattr(self.args, 'all', False)
        json_output = getattr(self.args, 'json_output', False)
        jobs = service.list_jobs(include_disabled=include_all)

        if json_output:
            result = []
            for job, state in jobs:
                result.append({
                    'id': job.id,
                    'name': job.name,
                    'enabled': job.enabled,
                    'status': state.status,
                    'next_run_at': state.next_run_at,
                    'run_count': state.run_count,
                })
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        if not jobs:
            print('No cron jobs found.')
            return

        print(f'{"ID":<12} {"Name":<25} {"Status":<12} {"Next Run":<25} {"Runs":>5}')
        print('-' * 82)
        for job, state in jobs:
            name = job.name[:24] if job.name else '-'
            next_run = state.next_run_at or '-'
            print(f'{job.id:<12} {name:<25} {state.status:<12} {next_run:<25} {state.run_count:>5}')

    def _cmd_create(self):
        service = self._get_service()
        try:
            job = service.create_job(
                schedule_str=self.args.schedule,
                prompt=self.args.prompt,
                name=getattr(self.args, 'name', ''),
                project=getattr(self.args, 'project', None),
                timeout=getattr(self.args, 'timeout', None),
            )
            print(f'Created job: {job.id} ({job.name})')
        except Exception as e:
            print(f'Error: {e}', file=sys.stderr)
            sys.exit(1)

    def _cmd_pause(self):
        service = self._get_service()
        if service.pause_job(self.args.job_id):
            print(f'Job {self.args.job_id} paused.')
        else:
            print(f'Failed to pause job {self.args.job_id}.', file=sys.stderr)

    def _cmd_resume(self):
        service = self._get_service()
        if service.resume_job(self.args.job_id):
            print(f'Job {self.args.job_id} resumed.')
        else:
            print(f'Failed to resume job {self.args.job_id}.', file=sys.stderr)

    def _cmd_run(self):
        service = self._get_service()
        result = asyncio.run(service.run_job_now(self.args.job_id))
        if result is None:
            print(f'Job {self.args.job_id} not found.', file=sys.stderr)
            sys.exit(1)
        if result.success:
            print(f'Job completed successfully ({result.duration_ms}ms)')
            if result.output:
                print('--- Output ---')
                print(result.output)
        else:
            print(f'Job failed: {result.error}', file=sys.stderr)
            sys.exit(1)

    def _cmd_remove(self):
        service = self._get_service()
        if service.delete_job(self.args.job_id):
            print(f'Job {self.args.job_id} removed.')
        else:
            print(f'Job {self.args.job_id} not found.', file=sys.stderr)

    def _cmd_history(self):
        service = self._get_service()
        records = service.get_history(self.args.job_id, limit=self.args.limit)
        if not records:
            print('No history found.')
            return
        print(f'{"Run At":<22} {"Status":<8} {"Duration":>10} {"Error"}')
        print('-' * 65)
        for r in records:
            dur = f'{r.duration_ms}ms'
            err = r.error or ''
            print(f'{r.run_at:<22} {r.status:<8} {dur:>10} {err}')

    def _cmd_import_jobs(self):
        service = self._get_service()
        count = service.manager.repo.import_declarative()
        print(f'Imported {count} job(s) from jobs.d/.')

    def _cmd_output(self):
        service = self._get_service()
        idx = -1 if getattr(self.args, 'last', False) else -1
        text = service.get_output(self.args.job_id, run_index=idx)
        if text is None:
            print('No output found.', file=sys.stderr)
        else:
            print(text)
