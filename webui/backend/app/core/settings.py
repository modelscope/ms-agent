import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict

# app/core/settings.py -> backend/ ; anchor .env to the file, not the CWD, so it
# loads identically from the server, a script, or a test regardless of cwd.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
# This backend runs in two directory layouts and must resolve its dotenv chain
# without adaptation in either one:
#   standalone checkout:   <repo>/backend            -> repo/.env, backend/.env
#   embedded in ms-agent:  <repo>/webui/backend      -> repo/.env, webui/.env,
#                                                       backend/.env
# The embedded layout inserts one directory level, so the repository root --
# where shared provider credentials live -- sits one level higher. Detect it by
# the parent directory's name; walking further up unconditionally would read a
# stray .env from OUTSIDE the checkout in the standalone layout.
_IS_EMBEDDED = _BACKEND_DIR.parent.name == "webui"
_ENV_FILES = (
    (
        _BACKEND_DIR.parent.parent / ".env",
        _BACKEND_DIR.parent / ".env",
        _BACKEND_DIR / ".env",
    ) if _IS_EMBEDDED else (
        _BACKEND_DIR.parent / ".env",
        _BACKEND_DIR / ".env",
    ))

# Publish all supported .env files into os.environ (never overriding real
# exports). Later, more specific files win while merging: repository defaults
# < (webui shared values, embedded layout only) < backend-only values. MCP
# ${VAR} placeholders need
# these values in os.environ rather than only in pydantic's settings object.
# pydantic-settings only extracts its own declared fields; MCP ${VAR}
# placeholders (headers/args/env in mcp.json) resolve against os.environ at
# connection time, so keys like DASHSCOPE_API_KEY must actually be there.
_dotenv: dict[str, str] = {}
for _env_file in _ENV_FILES:
    if _env_file.is_file():
        _dotenv.update({
            key: value
            for key, value in dotenv_values(_env_file).items()
            if value is not None
        })
for _key, _value in _dotenv.items():
    os.environ.setdefault(_key, _value)


class Settings(BaseSettings):
    # Process environment variables win over dotenv files. Within the files,
    # the later, more specific file wins (repo < webui < backend).
    model_config = SettingsConfigDict(
        env_file=tuple(str(path) for path in _ENV_FILES),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # mock       — in-memory seed data (frontend-only dev, no SDK needed)
    # ms_agent   — real ms-agent SDK (projects/sessions/config/chat on disk)
    # anthropic/openai — reserved (not wired)
    agent_backend: Literal["mock", "ms_agent", "anthropic", "openai"] = "mock"

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""

    # --- ms_agent backend ---
    # Override the SDK global home (default ~/.ms_agent). Maps to MS_AGENT_HOME.
    ms_agent_home: str = ""
    # Bootstrap the SDK's settings.json `llm` block on first run when absent, so
    # ConfigResolver yields a working model. Credentials reuse openai_api_key /
    # openai_base_url. provider must be a known registry id (openai, modelscope,
    # dashscope, anthropic, ...).
    ms_agent_llm_provider: str = "openai"
    ms_agent_llm_model: str = ""
    # Optional third-party key passed through to the SDK env (e.g. web-search MCP).
    exa_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
