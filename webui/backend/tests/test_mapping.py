"""Pure converter round-trips (no server, no network)."""
import pytest

from app.backends.ms_agent import mcps
from app.backends.ms_agent.mapping import (
    _mask,
    _protocol,
    decode_model_id,
    encode_model_id,
)


@pytest.mark.parametrize(
    "provider_id,name",
    [
        ("openai", "gpt-4o"),
        ("my-gw", "Qwen/Qwen3-Max"),          # slash in name
        ("modelscope", "a:b/c model"),         # colon + space
    ],
)
def test_model_id_roundtrip(provider_id, name):
    mid = encode_model_id(provider_id, name)
    assert "/" not in mid and ":" not in mid   # url-safe, path-safe
    assert decode_model_id(mid) == (provider_id, name)


@pytest.mark.parametrize(
    "scope,name",
    [
        ("global", "fetch"),
        ("project:_default", "amap"),
        ("project:50326e77f949", "server with spaces"),
    ],
)
def test_mcp_id_roundtrip(scope, name):
    mid = mcps._encode_id(scope, name)
    assert mcps._decode_id(mid) == (scope, name)


def test_mcp_stdio_endpoint_roundtrip():
    server = mcps._server("stdio", "npx -y @modelcontextprotocol/server-fetch")
    assert server == {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-fetch"]}
    transport, endpoint = mcps._endpoint(server)
    assert transport == "stdio"
    assert endpoint == "npx -y @modelcontextprotocol/server-fetch"


def test_mcp_remote_endpoint_roundtrip():
    server = mcps._server("sse", "https://mcp.amap.com/sse")
    assert server == {"url": "https://mcp.amap.com/sse", "transport": "sse"}
    transport, endpoint = mcps._endpoint(server)
    assert transport == "sse"
    assert endpoint == "https://mcp.amap.com/sse"


def test_mcp_stdio_env_roundtrip():
    server = mcps._server("stdio", "npx -y srv", env={"HTTP_PROXY": "http://p"})
    assert server["command"] == "npx" and server["args"] == ["-y", "srv"]
    assert server["env"] == {"HTTP_PROXY": "http://p"}
    assert mcps._endpoint(server) == ("stdio", "npx -y srv")


def test_mcp_remote_headers_roundtrip():
    server = mcps._server("sse", "https://x/sse", headers={"Authorization": "Bearer T"})
    assert server == {"url": "https://x/sse", "transport": "sse",
                      "headers": {"Authorization": "Bearer T"}}


def test_protocol_and_mask():
    assert _protocol("openai_compat") == "openai"
    assert _protocol("anthropic_messages") == "anthropic"
    assert _mask("") == ""
    assert _mask("short") == "****"
    assert _mask("sk-secret-1234567890") == "sk-s****7890"
