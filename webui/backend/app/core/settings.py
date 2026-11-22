import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# app/core/settings.py -> backend/ ; anchor .env to the file, not the CWD, so it
# loads identically from the server, a script, or a test regardless of cwd.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
# Under webui/, include the SDK root's shared .env before the WebUI and backend
# files. Otherwise, restrict discovery to the backend and its parent directory.
# This avoids reading an unrelated .env higher in the filesystem.
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

# Installed resources live in a versioned cache, outside a source checkout.
# Never discover credentials in site-packages or arbitrary cache parents.
if os.environ.get("MS_AGENT_WEBUI_INSTALLED") == "1":
    _ENV_FILES = ()

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
        hide_input_in_errors=True,
    )

    host: str = "127.0.0.1"
    port: int = 8000

    ms_agent_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    ms_agent_webui_auth_enabled: bool = False
    ms_agent_webui_username: str = "admin"
    ms_agent_webui_password: SecretStr = SecretStr("")

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
    # Where the LOCAL embedding model (fastembed ONNX) is downloaded from on
    # first use: "modelscope" (default — reachable without a HuggingFace
    # proxy) or "huggingface" (fastembed's own source, the pre-existing
    # behaviour). An already-downloaded model is always reused as-is.
    ms_agent_embed_model_source: str = "modelscope"

    @model_validator(mode="after")
    def validate_webui_auth(self) -> "Settings":
        if self.ms_agent_webui_auth_enabled:
            if not self.ms_agent_webui_username.strip() or len(self.ms_agent_webui_username) > 256:
                raise ValueError("MS_AGENT_WEBUI_USERNAME must contain 1–256 characters.")
            password = self.ms_agent_webui_password.get_secret_value()
            if not password.strip() or len(password) > 4096:
                raise ValueError("Set MS_AGENT_WEBUI_PASSWORD to a nonempty password (at most 4096 characters).")
            if "*" in self.cors_origin_list:
                raise ValueError("Use explicit MS_AGENT_CORS_ORIGINS when authentication is enabled.")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.ms_agent_cors_origins.split(",") if o.strip()]


settings = Settings()
