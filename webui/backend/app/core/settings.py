from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# app/core/settings.py -> backend/ ; anchor .env to the file, not the CWD, so it
# loads identically from the server, a script, or a test regardless of cwd.
_BACKEND_DIR = Path(__file__).resolve().parents[2]

# Publish both .env files into os.environ (never overriding real exports).
# pydantic-settings only extracts its own declared fields; MCP ${VAR}
# placeholders (headers/args/env in mcp.json) resolve against os.environ at
# connection time, so keys like DASHSCOPE_API_KEY must actually be there.
for _env_file in (_BACKEND_DIR / ".env", _BACKEND_DIR.parent / ".env"):
    if _env_file.is_file():
        load_dotenv(_env_file, override=False)


class Settings(BaseSettings):
    # Read backend/.env (backend config) and the repo-root ../.env (shared
    # provider secrets). Keys don't overlap, so load order is immaterial.
    model_config = SettingsConfigDict(
        env_file=(str(_BACKEND_DIR / ".env"), str(_BACKEND_DIR.parent / ".env")),
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
