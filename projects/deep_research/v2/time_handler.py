# Copyright (c) Alibaba, Inc. and its affiliates.
from datetime import datetime
from typing import Any

from ms_agent.config.config import ConfigLifecycleHandler
from omegaconf import DictConfig


class TimeHandler(ConfigLifecycleHandler):
    """Config handler that injects current date/time and other config values into prompts"""

    def task_begin(self, config: DictConfig, tag: str) -> DictConfig:
        now = datetime.now()

        # Prepare variables (time + selected config values)
        time_vars = {
            'current_date': now.strftime('%Y-%m-%d'),
            'current_time': now.strftime('%H:%M:%S'),
            'current_datetime': now.isoformat(),
        }

        # Also expose config-driven limits for prompt placeholders.
        # This enables writing prompts like: "max_chat_round=<max_chat_round>".
        max_chat_round = getattr(config, 'max_chat_round', None)
        if max_chat_round is not None:
            time_vars['max_chat_round'] = str(max_chat_round)

        # Inject into config using recursive traversal
        def traverse_and_replace(_config: Any):
            if isinstance(_config, DictConfig):
                for name, value in _config.items():
                    if isinstance(value, DictConfig) or isinstance(
                            value, list):
                        traverse_and_replace(value)
                    elif isinstance(value, str):
                        new_value = value
                        # Replace <variable> placeholders
                        for var_name, var_value in time_vars.items():
                            placeholder = f'<{var_name}>'
                            if placeholder in new_value:
                                new_value = new_value.replace(
                                    placeholder, var_value)
                        setattr(_config, name, new_value)

            elif isinstance(_config, list):
                for i, item in enumerate(_config):
                    if isinstance(item, (DictConfig, list)):
                        traverse_and_replace(item)
                    elif isinstance(item, str):
                        new_value = item
                        # Replace <variable> placeholders
                        for var_name, var_value in time_vars.items():
                            placeholder = f'<{var_name}>'
                            if placeholder in new_value:
                                new_value = new_value.replace(
                                    placeholder, var_value)
                        _config[i] = new_value

        traverse_and_replace(config)
        return config
