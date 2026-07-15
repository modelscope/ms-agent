# Copyright (c) ModelScope Contributors. All rights reserved.
"""The ``/loop`` slash command (loop engineering).

Three modes, all driven from one entry point:

  - ``/loop <interval> <prompt|/cmd>``  -> in-session interval loop (fixed
    cadence). If the interval is long (>= 1h) or ``--detach`` is passed, the
    loop is handed to the cron backend as a detached persistent job instead.
  - ``/loop <prompt>``                  -> in-session self-paced loop (the model
    picks each delay via the ``schedule_wakeup`` tool and can self-terminate).
  - ``/loop``                           -> in-session maintenance loop (a
    built-in default prompt, overridable via ``<work_dir>/.ms_agent/loop.md``).

Sub-commands: ``/loop status`` shows the active loop; ``/loop stop`` (aliases
``off``/``cancel``) clears it.

The handler writes loop configuration onto ``ctx.runtime`` (persisted via
``Runtime.to_dict``) and returns a ``SUBMIT_PROMPT`` for the first iteration.
The :class:`~ms_agent.callbacks.loop_controller.LoopController` drives every
subsequent iteration.
"""
from __future__ import annotations

import os
import re
import time
from typing import Optional, Tuple

from ms_agent.command.router import CommandRouter
from ms_agent.command.types import (
    CommandContext,
    CommandDef,
    CommandResult,
    CommandResultType,
)

# In-session loops shorter than this stay in the live session; longer cadences
# (or an explicit --detach) are handed to the cron backend.
CRON_THRESHOLD_SECONDS = 3600
# Default wall-clock lifetime of a loop before it auto-expires (7 days).
LOOP_MAX_AGE_SECONDS = 7 * 24 * 3600
# Default hard iteration cap (aligns with Claude Code's per-session task cap).
DEFAULT_LOOP_MAX = 50

_UNIT_SECONDS = {
    's': 1, 'sec': 1, 'secs': 1, 'second': 1, 'seconds': 1,
    'm': 60, 'min': 60, 'mins': 60, 'minute': 60, 'minutes': 60,
    'h': 3600, 'hr': 3600, 'hrs': 3600, 'hour': 3600, 'hours': 3600,
    'd': 86400, 'day': 86400, 'days': 86400,
}
_UNIT_SHORT = {'s': 's', 'm': 'm', 'h': 'h', 'd': 'd'}

_UNIT_PATTERN = (r'(s|sec|secs|seconds?|m|min|mins|minutes?|'
                 r'h|hr|hrs|hours?|d|days?)')
_LEADING_INTERVAL_RE = re.compile(r'^(\d+)\s*' + _UNIT_PATTERN + r'\b',
                                  re.IGNORECASE)
_TRAILING_EVERY_RE = re.compile(r'\bevery\s+(\d+)\s*' + _UNIT_PATTERN + r'\s*$',
                                re.IGNORECASE)

CMD_LOOP = CommandDef(
    name='loop',
    description='Run a prompt on a recurring or self-paced loop',
    category='session',
)

_USAGE = (
    'Usage:\n'
    '  /loop <interval> <prompt|/command>   run every interval (e.g. 5m, 1h)\n'
    '  /loop <prompt>                       self-paced (model picks the pace)\n'
    '  /loop                                maintenance loop (default prompt)\n'
    '  /loop status                         show the active loop\n'
    '  /loop stop                           stop the active loop\n'
    'Flags: --detach (force a background cron job), --times N (bounded runs),\n'
    '       --max N (iteration cap), --budget N (token budget).')

DEFAULT_MAINTENANCE_PROMPT = (
    'Continue routine maintenance on the current project. Look for unfinished '
    'work, failing checks, or follow-ups from the recent conversation, and make '
    'safe, incremental progress. Do NOT take irreversible actions (push, '
    'deploy, delete, or anything not already authorized in this session) '
    'without explicit confirmation. If there is nothing useful to do right now, '
    'say so briefly.')


def _norm_unit(unit: str) -> str:
    return unit.lower()[0]


def _interval_seconds(count: int, unit: str) -> int:
    return count * _UNIT_SECONDS[unit.lower()]


def _parse_interval(args: str) -> Tuple[Optional[int], Optional[str], str]:
    """Return ``(interval_seconds, interval_token, body)``.

    ``interval_seconds``/``interval_token`` are None when no interval is given.
    """
    text = args.strip()
    m = _LEADING_INTERVAL_RE.match(text)
    if m:
        secs = _interval_seconds(int(m.group(1)), m.group(2))
        token = f'{m.group(1)}{_UNIT_SHORT[_norm_unit(m.group(2))]}'
        return secs, token, text[m.end():].strip()
    m = _TRAILING_EVERY_RE.search(text)
    if m:
        secs = _interval_seconds(int(m.group(1)), m.group(2))
        token = f'{m.group(1)}{_UNIT_SHORT[_norm_unit(m.group(2))]}'
        return secs, token, text[:m.start()].strip()
    return None, None, text


def _extract_int_flag(args: str, name: str) -> Tuple[Optional[int], str]:
    m = re.search(rf'--{name}(?:[=\s]+)(\d+)', args)
    if not m:
        return None, args
    return int(m.group(1)), (args[:m.start()] + args[m.end():]).strip()


def _extract_bool_flag(args: str, name: str) -> Tuple[bool, str]:
    pat = re.compile(rf'(?:^|\s)--{name}(?=\s|$)')
    if pat.search(args):
        return True, pat.sub(' ', args).strip()
    return False, args


def _work_dir(ctx: CommandContext) -> str:
    from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR
    cfg = getattr(getattr(ctx.runtime, 'llm', None), 'config', None)
    if cfg is not None:
        return getattr(cfg, 'output_dir', None) or DEFAULT_OUTPUT_DIR
    return DEFAULT_OUTPUT_DIR


def _load_maintenance_prompt(ctx: CommandContext) -> str:
    path = os.path.join(_work_dir(ctx), '.ms_agent', 'loop.md')
    try:
        if os.path.isfile(path):
            content = open(path, 'r', encoding='utf-8').read().strip()
            if content:
                return content
    except OSError:
        pass
    return DEFAULT_MAINTENANCE_PROMPT


def _current_total_tokens() -> int:
    try:
        from ms_agent.agent.llm_agent import LLMAgent
        return LLMAgent.TOTAL_PROMPT_TOKENS + LLMAgent.TOTAL_COMPLETION_TOKENS
    except Exception:  # noqa: BLE001
        return 0


def _status_text(runtime) -> str:
    if not getattr(runtime, 'loop_active', False):
        return 'No active loop.'
    lines = [
        f'Loop: active ({runtime.loop_mode})',
        f'  Iteration: {runtime.loop_iteration}/{runtime.loop_max}',
    ]
    if runtime.loop_interval:
        lines.append(f'  Interval:  {runtime.loop_interval}s')
    if runtime.loop_deadline:
        remaining = int(runtime.loop_deadline - time.time())
        lines.append(f'  Expires in: {max(0, remaining)}s')
    if runtime.loop_token_budget:
        lines.append(f'  Token budget: {runtime.loop_token_budget:,}')
    preview = (runtime.loop_prompt or '').strip().splitlines()[0:1]
    if preview:
        lines.append(f'  Prompt: {preview[0][:70]}')
    return '\n'.join(lines)


async def _create_detached_loop(name: str, interval_token: str, body: str,
                                times: Optional[int]) -> CommandResult:
    """Register a detached persistent cron job for a long-interval loop."""
    try:
        from ms_agent.cron.parser import parse_schedule
        from ms_agent.cron.service import CronService
        from ms_agent.cron.types import CronJobSpec, RepeatSpec
    except Exception as e:  # noqa: BLE001
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Cron backend unavailable for detached loop: {e}')

    workspace = os.environ.get(
        'MS_AGENT_CRON_WORKSPACE', os.path.expanduser('~/.ms_agent/cron'))
    schedule_str = f'every {interval_token}'
    try:
        schedule = parse_schedule(schedule_str)
    except ValueError as e:
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Invalid interval for detached loop: {e}')

    spec = CronJobSpec(
        name=name,
        schedule=schedule,
        prompt=body,
        session_mode='persistent',
        repeat=RepeatSpec(times=times) if times else None,
    )
    try:
        service = CronService(workspace=workspace)
        job = service.manager.create_job_from_spec(spec)
    except Exception as e:  # noqa: BLE001
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Failed to create detached loop: {e}')

    bound = f' for {times} run(s)' if times else ''
    return CommandResult(
        type=CommandResultType.MESSAGE,
        content=(
            f'Detached loop registered as cron job {job.id} '
            f'(every {interval_token}{bound}).\n'
            'It runs in its own persistent session, decoupled from this chat. '
            'Start the scheduler with `ms-agent cron start` if it is not '
            f'already running; remove it later with `ms-agent cron remove '
            f'{job.id}`.'))


async def cmd_loop(ctx: CommandContext) -> CommandResult:
    runtime = ctx.runtime
    if runtime is None:
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content='/loop needs an active agent session.')

    args = (ctx.args or '').strip()
    sub = args.lower()

    if sub in ('stop', 'off', 'cancel'):
        if not getattr(runtime, 'loop_active', False):
            return CommandResult(
                type=CommandResultType.MESSAGE, content='No active loop.')
        runtime.reset_loop()
        return CommandResult(
            type=CommandResultType.MESSAGE, content='Loop stopped.')

    if sub in ('status', 'info'):
        return CommandResult(
            type=CommandResultType.MESSAGE, content=_status_text(runtime))

    # Flags
    detach, args = _extract_bool_flag(args, 'detach')
    times, args = _extract_int_flag(args, 'times')
    max_iters, args = _extract_int_flag(args, 'max')
    budget, args = _extract_int_flag(args, 'budget')

    interval_secs, interval_token, body = _parse_interval(args)

    maintenance = False
    if not body and interval_secs is None:
        body = _load_maintenance_prompt(ctx)
        maintenance = True

    if not body:
        return CommandResult(type=CommandResultType.MESSAGE, content=_USAGE)

    if body.strip().lower().startswith('/loop'):
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content='A /loop body cannot itself be /loop.')

    # Detached / long-interval -> cron backend.
    if interval_secs is not None and (detach
                                      or interval_secs >= CRON_THRESHOLD_SECONDS):
        name = f'loop: {body[:40]}'
        return await _create_detached_loop(name, interval_token, body, times)

    # In-session loop: arm the runtime and kick off iteration 1.
    runtime.reset_loop()
    runtime.loop_active = True
    runtime.loop_prompt = body
    runtime.loop_max = max_iters or times or DEFAULT_LOOP_MAX
    runtime.loop_deadline = time.time() + LOOP_MAX_AGE_SECONDS
    runtime.loop_token_budget = budget
    runtime.loop_token_start = _current_total_tokens()
    if interval_secs is not None:
        runtime.loop_mode = 'interval'
        runtime.loop_interval = interval_secs
    elif maintenance:
        runtime.loop_mode = 'maintenance'
    else:
        runtime.loop_mode = 'self_paced'

    from ms_agent.callbacks.loop_controller import build_iteration_prompt
    router = ctx.extra.get('router')
    messages = ctx.extra.get('messages', [])
    first_prompt = await build_iteration_prompt(router, runtime, messages, body)

    cadence = (f'every {interval_token}' if interval_secs is not None else
               'maintenance' if maintenance else 'self-paced')
    print(f'[loop] started ({runtime.loop_mode}, {cadence}). '
          f'Use /loop stop to cancel, /loop status to inspect.')
    return CommandResult(type=CommandResultType.SUBMIT_PROMPT,
                         content=first_prompt)


def register_loop_commands(router: CommandRouter) -> None:
    router.register(CMD_LOOP, cmd_loop)
