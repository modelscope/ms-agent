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

    def to_dict(self):
        return {
            'should_stop': self.should_stop,
            'tag': self.tag,
            'round': self.round,
            'stop_hook_active': self.stop_hook_active,
            'session_id': self.session_id,
        }

    def from_dict(self, data: dict):
        self.should_stop = data['should_stop']
        self.tag = data['tag']
        self.round = data['round']
        self.stop_hook_active = data.get('stop_hook_active', False)
        self.session_id = data.get('session_id', '')
