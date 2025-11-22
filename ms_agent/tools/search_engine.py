import os
import threading
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from ms_agent.config.env import Env
from ms_agent.tools.exa import ExaSearch
from ms_agent.tools.search.arxiv import ArxivSearch
from ms_agent.tools.search.search_base import SearchEngineType
from ms_agent.tools.search.serpapi import SerpApiSearch
from ms_agent.utils.logger import get_logger

logger = get_logger()

SEARCH_ENGINE_OVERRIDE_ENV = 'FIN_RESEARCH_SEARCH_ENGINE'

_search_env_local = threading.local()


def set_search_env_overrides(env_overrides: Optional[Dict[str, str]]) -> None:
    """Set per-thread search environment overrides.

    Expected keys (all optional):
      - 'EXA_API_KEY'
      - 'SERPAPI_API_KEY'
      - SEARCH_ENGINE_OVERRIDE_ENV (e.g. 'exa' / 'serpapi' / 'arxiv')
    """
    if not env_overrides:
        if hasattr(_search_env_local, 'overrides'):
            delattr(_search_env_local, 'overrides')
        return
    _search_env_local.overrides = {
        k: v
        for k, v in env_overrides.items() if v is not None
    }


def get_search_env_overrides() -> Dict[str, str]:
    """Get current thread-local search environment overrides."""
    return getattr(_search_env_local, 'overrides', {}) or {}


def get_search_config(config_file: str):
    config_file = os.path.abspath(os.path.expanduser(config_file))
    config = load_base_config(config_file)
    search_config = config.get('SEARCH_ENGINE', {})
    return search_config


def load_base_config(file_path: str) -> Dict[str, Any]:
    """
    Load the base configuration from a YAML file.

    Args:
        file_path (str): Path to the YAML configuration file.

    Returns:
        Dict[str, Any]: The loaded configuration as a dictionary.
    """
    # Load environment variables from .env file if it exists
    if not load_dotenv(os.path.join(os.getcwd(), '.env')):
        Env.load_env()

    if not os.path.exists(file_path):
        logger.warning(
            f'Config file {file_path} does not exist. Using default config (ArxivSearch).'
        )
        return {}

    import yaml
    with open(file_path, 'r') as file:
        config = yaml.safe_load(file)

    return process_dict(config)


def process_dict(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively process dictionary to replace environment variables.

    Args:
        config (Dict[str, Any]): The configuration dictionary to process.

    Returns:
        Dict[str, Any]: The processed configuration dictionary with environment variables replaced.
    """
    if not config:
        return {}

    result = {}
    for key, value in config.items():
        if isinstance(value, dict):
            result[key] = process_dict(value)
        elif isinstance(value, str):
            result[key] = replace_env_vars(value)
        else:
            result[key] = value
    return result


def replace_env_vars(value: str) -> str:
    """
    Replace environment variables in string values.

    Args:
        value (str): The string potentially containing environment variables.
    Returns:
        str: The string with environment variables replaced.
    """
    if not isinstance(value, str):
        return value

    if value.startswith('$'):
        env_var = value[1:]
        return os.getenv(env_var, None)

    return value


def get_web_search_tool(config_file: str):
    """
    Get the web search tool based on the configuration.

    Returns:
        SearchEngine: An instance of the SearchEngine class configured with the API key.
    """
    search_config = get_search_config(config_file=config_file)
    local_env = get_search_env_overrides()

    # Engine override precedence:
    # 1) Thread-local override (per-request, e.g. FinResearch UI)
    # 2) Global environment variable (shared default)
    engine_override = ((local_env.get(SEARCH_ENGINE_OVERRIDE_ENV, '') or '')
                       or (os.getenv(SEARCH_ENGINE_OVERRIDE_ENV, '')
                           or '')).strip().lower()
    if engine_override and engine_override in (SearchEngineType.EXA.value,
                                               SearchEngineType.SERPAPI.value,
                                               SearchEngineType.ARXIV.value):
        search_config['engine'] = engine_override

    engine_name = (search_config.get('engine', '') or '').lower()

    # Per-request API key overrides (thread-local) take precedence
    override_exa_key = local_env.get('EXA_API_KEY')
    override_serp_key = local_env.get('SERPAPI_API_KEY')

    if engine_name == SearchEngineType.EXA.value:
        return ExaSearch(
            api_key=override_exa_key or search_config.get(
                'exa_api_key', os.getenv('EXA_API_KEY', None)))
    elif engine_name == SearchEngineType.SERPAPI.value:
        return SerpApiSearch(
            api_key=override_serp_key or search_config.get(
                'serpapi_api_key', os.getenv('SERPAPI_API_KEY', None)),
            provider=search_config.get('provider', 'google').lower())
    elif engine_name == SearchEngineType.ARXIV.value:
        return ArxivSearch()
    else:
        return ArxivSearch()
