from ms_agent.utils.logger import get_logger

logger = get_logger()


class A2AServerError(Exception):
    """Base exception for A2A server-side errors in ms-agent."""

    def __init__(self, code: int, message: str, data: dict | None = None):
        self.code = code
        self.message = message
        self.data = data or {}
        super().__init__(message)


class TaskNotFoundError(A2AServerError):

    def __init__(self, task_id: str):
        super().__init__(-32001, 'Task not found', {'taskId': task_id})


class AgentLoadError(A2AServerError):

    def __init__(self, detail: str):
        super().__init__(-32002, 'Failed to load agent', {'detail': detail})


class LLMError(A2AServerError):

    def __init__(self, detail: str):
        super().__init__(-32003, 'LLM generation failed', {'detail': detail})


class RateLimitError(A2AServerError):

    def __init__(self, detail: str = ''):
        super().__init__(-32004, 'Rate limit exceeded', {'detail': detail})


class ConfigError(A2AServerError):

    def __init__(self, detail: str):
        super().__init__(-32005, 'Invalid configuration', {'detail': detail})


class MaxTasksError(A2AServerError):

    def __init__(self, max_tasks: int):
        super().__init__(-32006, 'Maximum concurrent tasks reached',
                         {'max': max_tasks})


_EXCEPTION_MAP: list[tuple[type, int, str]] = [
    (FileNotFoundError, -32002, 'Resource not found'),
    (PermissionError, -32000, 'Permission denied'),
    (TimeoutError, -32004, 'Request timed out'),
    (ValueError, -32602, 'Invalid params'),
]


def wrap_a2a_error(exc: Exception) -> dict:
    """Convert an ms-agent exception into a JSON-RPC-style error dict.

    Returns a dict with ``code``, ``message``, and ``data`` keys suitable
    for logging or constructing an A2A ``ServerError``.
    """
    if isinstance(exc, A2AServerError):
        return {'code': exc.code, 'message': exc.message, 'data': exc.data}

    for exc_type, code, msg in _EXCEPTION_MAP:
        if isinstance(exc, exc_type):
            return {'code': code, 'message': msg, 'data': {'detail': str(exc)}}

    return {
        'code': -32603,
        'message': 'Internal error',
        'data': {
            'detail': str(exc)
        }
    }
