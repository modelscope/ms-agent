"""Default tool scope for WebUI sessions."""

# WebUI persists missing defaults at startup and before reading settings or
# starting a turn. The same defaults remain below user settings at runtime.
DEFAULT_TOOLS: dict = {
    "file_system": {
        "enabled": True,
        "mcp": False,
        "include": ["read_file", "grep", "glob", "edit_file", "write_file"],
    },
    "todo_list": {"enabled": True, "mcp": False},
    # Shell/terminal only. implementation must be the SDK's "python_env" (a
    # local executor, no Docker); "local"/"sandbox" route to the Docker
    # CodeExecutionTool (needs ms-enclave). `include: [shell_executor]` exposes
    # ONLY the terminal tool. The local executor does not start Jupyter. Restricted
    # permission gates shell_executor (not whitelisted) so every command asks.
    "code_executor": {
        "enabled": True,
        "mcp": False,
        "implementation": "python_env",
        "include": ["shell_executor"],
    },
    # Web search is ON by default, and Tavily is the default engine because it
    # is the only web-wide one that WORKS with no credentials: the SDK falls
    # back to Tavily's keyless tier (tavily/search.py KEYLESS_HEADER) when no
    # key is configured, so a fresh install can search immediately instead of
    # silently having no engine until someone visits Settings -> Search. The
    # keyless quota is a small sliding hourly bucket; adding a key lifts it, and
    # a configured key always takes precedence.
    "web_search": {"mcp": False, "engine": "tavily", "enabled": True},
}

# task_control has no WebUI rendering component yet; strip it from any home that
# was seeded with the earlier default so it isn't loaded (idempotent migration).
RETIRED_TOOLS = ("task_control",)
