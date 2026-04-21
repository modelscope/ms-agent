"""ACP configuration helpers: build configOptions from ms-agent config."""

from __future__ import annotations
from typing import Any

from acp.schema import (SessionConfigOptionSelect, SessionConfigSelect,
                        SessionConfigSelectOption, SessionMode,
                        SessionModeState)
from ms_agent.utils.logger import get_logger

logger = get_logger()


def build_config_options(
    config,
    available_models: list[str] | None = None,
) -> list | None:
    """Derive ACP ``configOptions`` from an ms-agent DictConfig.

    Returns a list of ``SessionConfigOptionSelect`` selectors that ACP
    clients can render for the user (model picker, etc.).
    """
    options: list = []

    model_id = _get_model_id(config)
    if model_id:
        models = available_models or [model_id]
        values = [SessionConfigSelectOption(value=m, name=m) for m in models]
        options.append(
            SessionConfigOptionSelect(
                type='select',
                id='model',
                name='LLM Model',
                category='model',
                current_value=model_id,
                options=values,
            ))

    return options if options else None


def build_session_modes() -> SessionModeState | None:
    """Build a default mode state for ms-agent sessions."""
    modes = [
        SessionMode(
            id='agent',
            name='Agent',
            description='Full agent mode with tools',
        ),
    ]
    return SessionModeState(
        available_modes=modes,
        current_mode_id='agent',
    )


def apply_config_option(config, config_id: str, value: str) -> bool:
    """Apply a config option change to the live agent config.

    Returns True if the option was applied successfully.
    """
    from omegaconf import OmegaConf

    if config_id == 'model':
        if hasattr(config, 'llm') and hasattr(config.llm, 'model'):
            OmegaConf.update(config, 'llm.model', value, merge=True)
            logger.info('Config option updated: llm.model = %s', value)
            return True
    return False


def _get_model_id(config) -> str | None:
    """Extract the current model identifier from config."""
    if hasattr(config, 'llm') and hasattr(config.llm, 'model'):
        return str(config.llm.model)
    return None
