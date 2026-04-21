from acp import RequestError


class ACPError(Exception):
    """Base exception for ACP-specific errors in ms-agent."""

    def __init__(self, code: int, message: str, data: dict | None = None):
        self.code = code
        self.message = message
        self.data = data or {}
        super().__init__(message)


class SessionNotFoundError(ACPError):

    def __init__(self, session_id: str):
        super().__init__(-32001, 'Session not found',
                         {'sessionId': session_id})


class ResourceNotFoundError(ACPError):

    def __init__(self, path: str):
        super().__init__(-32002, 'Resource not found', {'path': path})


class LLMError(ACPError):

    def __init__(self, detail: str):
        super().__init__(-32003, 'LLM generation failed', {'detail': detail})


class RateLimitError(ACPError):

    def __init__(self, detail: str = ''):
        super().__init__(-32004, 'Rate limit exceeded', {'detail': detail})


class ConfigError(ACPError):

    def __init__(self, detail: str):
        super().__init__(-32005, 'Invalid configuration', {'detail': detail})


class MaxSessionsError(ACPError):

    def __init__(self, max_sessions: int):
        super().__init__(-32006, 'Maximum concurrent sessions reached',
                         {'max': max_sessions})


# Map known ms-agent / Python exception types to ACP JSON-RPC errors.
_EXCEPTION_MAP: list[tuple[type, int, str]] = [
    (FileNotFoundError, -32002, 'Resource not found'),
    (PermissionError, -32000, 'Permission denied'),
    (TimeoutError, -32004, 'Request timed out'),
    (ValueError, -32602, 'Invalid params'),
]


def wrap_agent_error(exc: Exception) -> RequestError:
    """Convert an ms-agent exception into an ``acp.RequestError``.

    ``RequestError`` is what the ACP SDK expects to be raised inside
    agent method handlers; it serialises to a proper JSON-RPC error object.
    """
    if isinstance(exc, ACPError):
        return RequestError(exc.code, exc.message, exc.data)

    if isinstance(exc, RequestError):
        return exc

    for exc_type, code, msg in _EXCEPTION_MAP:
        if isinstance(exc, exc_type):
            return RequestError(code, msg, {'detail': str(exc)})

    return RequestError(-32603, 'Internal error', {'detail': str(exc)})
