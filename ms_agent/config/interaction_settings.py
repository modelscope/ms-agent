# Copyright (c) ModelScope Contributors. All rights reserved.
"""Shared conversation input preference; independent of any interface."""
import json
from pathlib import Path

from ms_agent.utils.json_store import json_transaction


class InteractionSettings:

    def __init__(self, global_dir=None):
        from ms_agent.project.paths import global_home
        self.path = Path(global_dir or global_home()) / 'settings.json'

    def get(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return 'queue'
        value = data.get('interaction', {}).get('follow_up_behavior', 'queue')
        return value if value in ('queue', 'steer') else 'queue'

    def update(self, value):
        if value not in ('queue', 'steer'):
            raise ValueError('Unknown follow-up behavior')
        from functools import partial
        from .secrets import write_managed_config
        with json_transaction(self.path, writer=partial(
                write_managed_config, home=self.path.parent)) as data:
            data.setdefault('interaction', {})['follow_up_behavior'] = value
