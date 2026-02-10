# Copyright (c) ModelScope Contributors. All rights reserved.
from datetime import datetime
from typing import Any

from ms_agent.config.config import ConfigLifecycleHandler
from omegaconf import DictConfig


class TimeHandler(ConfigLifecycleHandler):
    """Config handler that injects current date/time into prompts"""

    def task_begin(self, config: DictConfig, tag: str) -> DictConfig:
        """Inject current date and time before task begins"""
        now = datetime.now()

        # Prepare time variables
        time_vars = {
            'current_date': now.strftime('%Y-%m-%d'),
            'current_time': now.strftime('%H:%M:%S'),
            'current_datetime': now.isoformat(),
        }

        # Inject into config using the same mechanism as main config system
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
