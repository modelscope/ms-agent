"""A2A (Agent-to-Agent) protocol support for ms-agent.

This package provides:

- **Server**: ``MSAgentA2AExecutor`` bridges A2A requests to ms-agent's
  agent runtime, allowing ms-agent to be called by remote A2A clients.
- **Client**: ``A2AClientManager`` sends messages to remote A2A agents
  over HTTP, enabling ms-agent to delegate work to external agents.
- **Agent Card**: ``build_agent_card`` / ``generate_agent_card_json``
  produce the A2A discovery document from ms-agent config.

All SDK-dependent imports are lazy so the package can be imported even
when ``a2a-sdk`` is not installed (the tools and CLI will gracefully
degrade).
"""

from .client import A2AClientManager
from .errors import (A2AServerError, AgentLoadError, ConfigError, LLMError,
                     MaxTasksError, RateLimitError, TaskNotFoundError,
                     wrap_a2a_error)
from .session_store import A2AAgentStore, A2ATaskEntry
from .translator import (a2a_message_to_ms_messages, collect_full_response,
                         extract_text_from_a2a_message, ms_messages_to_text)


def __getattr__(name):
    """Lazy-load SDK-dependent symbols on first access."""
    if name == 'MSAgentA2AExecutor':
        from .executor import MSAgentA2AExecutor
        return MSAgentA2AExecutor
    if name == 'configure_a2a_logging':
        from .executor import configure_a2a_logging
        return configure_a2a_logging
    if name == 'build_agent_card':
        from .agent_card import build_agent_card
        return build_agent_card
    if name == 'generate_agent_card_json':
        from .agent_card import generate_agent_card_json
        return generate_agent_card_json
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


__all__ = [
    'A2AAgentStore',
    'A2AClientManager',
    'A2AServerError',
    'A2ATaskEntry',
    'AgentLoadError',
    'ConfigError',
    'LLMError',
    'MSAgentA2AExecutor',
    'MaxTasksError',
    'RateLimitError',
    'TaskNotFoundError',
    'a2a_message_to_ms_messages',
    'build_agent_card',
    'collect_full_response',
    'configure_a2a_logging',
    'extract_text_from_a2a_message',
    'generate_agent_card_json',
    'ms_messages_to_text',
    'wrap_a2a_error',
]
