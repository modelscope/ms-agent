# Copyright (c) Alibaba, Inc. and its affiliates.
from dataclasses import dataclass
from typing import Optional

from ms_agent.llm import LLM


@dataclass
class Runtime:

    should_stop: bool = False

    llm: LLM = None

    tag: Optional[str] = None

    round: int = 0

    def to_dict(self):
        return {
            'should_stop': self.should_stop,
            'tag': self.tag,
            'round': self.round,
        }

    def from_dict(self, data: dict):
        self.should_stop = data['should_stop']
        self.tag = data['tag']
        self.round = data['round']
