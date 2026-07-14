# Copyright (c) ModelScope Contributors. All rights reserved.
from dataclasses import dataclass
from typing import Optional

from ms_agent.llm import LLM


@dataclass
class Runtime:

    should_stop: bool = False

    llm: LLM = None

    tag: Optional[str] = None

    round: int = 0

    stop_hook_active: bool = False

    session_id: str = ''

    # -- /loop (loop engineering) state --------------------------------------
    # An active in-session loop re-injects ``loop_prompt`` after the model
    # finishes each turn, turning the "wait for human input" fork into "ask an
    # automatic policy". All fields below are serialized (to_dict/from_dict) so
    # a loop survives ``save_history`` and can be re-hydrated on resume.
    loop_active: bool = False
    # 'interval' | 'self_paced' | 'maintenance'
    loop_mode: str = ''
    # Re-injected each iteration; may be a plain prompt or a /slash body.
    loop_prompt: str = ''
    # Interval mode: fixed delay between iterations, in seconds.
    loop_interval: Optional[int] = None
    loop_iteration: int = 0
    # Hard iteration cap (circuit breaker).
    loop_max: int = 50
    # Wall-clock auto-expiry, epoch seconds (circuit breaker).
    loop_deadline: Optional[float] = None
    # Optional token budget: max tokens the loop may spend before stopping.
    loop_token_budget: Optional[int] = None
    # Process token total captured when the loop started (for budget deltas).
    loop_token_start: int = 0
    # Self-paced: delay/reason the model chose via the schedule_wakeup tool.
    loop_next_delay: Optional[int] = None
    loop_next_reason: str = ''

    def reset_loop(self) -> None:
        """Clear all loop state (used by /loop stop and on termination)."""
        self.loop_active = False
        self.loop_mode = ''
        self.loop_prompt = ''
        self.loop_interval = None
        self.loop_iteration = 0
        self.loop_deadline = None
        self.loop_token_budget = None
        self.loop_token_start = 0
        self.loop_next_delay = None
        self.loop_next_reason = ''

    def to_dict(self):
        return {
            'should_stop': self.should_stop,
            'tag': self.tag,
            'round': self.round,
            'stop_hook_active': self.stop_hook_active,
            'session_id': self.session_id,
            'loop_active': self.loop_active,
            'loop_mode': self.loop_mode,
            'loop_prompt': self.loop_prompt,
            'loop_interval': self.loop_interval,
            'loop_iteration': self.loop_iteration,
            'loop_max': self.loop_max,
            'loop_deadline': self.loop_deadline,
            'loop_token_budget': self.loop_token_budget,
            'loop_token_start': self.loop_token_start,
            'loop_next_delay': self.loop_next_delay,
            'loop_next_reason': self.loop_next_reason,
        }

    def from_dict(self, data: dict):
        self.should_stop = data['should_stop']
        self.tag = data['tag']
        self.round = data['round']
        self.stop_hook_active = data.get('stop_hook_active', False)
        self.session_id = data.get('session_id', '')
        self.loop_active = data.get('loop_active', False)
        self.loop_mode = data.get('loop_mode', '')
        self.loop_prompt = data.get('loop_prompt', '')
        self.loop_interval = data.get('loop_interval', None)
        self.loop_iteration = data.get('loop_iteration', 0)
        self.loop_max = data.get('loop_max', 50)
        self.loop_deadline = data.get('loop_deadline', None)
        self.loop_token_budget = data.get('loop_token_budget', None)
        self.loop_token_start = data.get('loop_token_start', 0)
        self.loop_next_delay = data.get('loop_next_delay', None)
        self.loop_next_reason = data.get('loop_next_reason', '')
