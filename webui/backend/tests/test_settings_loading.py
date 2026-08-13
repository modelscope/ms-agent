"""Configuration precedence used by the source-checkout launcher."""

from app.core.settings import Settings


def test_dotenv_files_progress_from_repository_to_backend(tmp_path, monkeypatch):
    repository_env = tmp_path / "repository.env"
    webui_env = tmp_path / "webui.env"
    backend_env = tmp_path / "backend.env"
    repository_env.write_text("OPENAI_BASE_URL=https://repository.example\n")
    webui_env.write_text("OPENAI_BASE_URL=https://webui.example\n")
    backend_env.write_text("OPENAI_BASE_URL=https://backend.example\n")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    configured = Settings(
        _env_file=(repository_env, webui_env, backend_env),
        _env_file_encoding="utf-8",
    )

    assert configured.openai_base_url == "https://backend.example"


def test_process_environment_wins_over_all_dotenv_files(tmp_path, monkeypatch):
    backend_env = tmp_path / "backend.env"
    backend_env.write_text("OPENAI_BASE_URL=https://backend.example\n")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://process.example")

    configured = Settings(
        _env_file=(backend_env,),
        _env_file_encoding="utf-8",
    )

    assert configured.openai_base_url == "https://process.example"


def test_app_wires_the_env_chain_for_its_layout():
    """Pin the APP's wiring, not pydantic's semantics.

    The two tests above hand-build ``Settings(_env_file=...)``, so they stay
    green even if ``app/core/settings.py`` reverses the tuple or drops a
    layer. This asserts the actual module-level chain for whichever layout
    this checkout is in: the standalone repository (``<repo>/backend``) reads
    repo + backend, and the same file embedded in the ms-agent repository
    (``<repo>/webui/backend``) inserts the webui level and anchors the
    repository root one directory higher.
    """
    import app.core.settings as s

    backend_dir = s._BACKEND_DIR
    assert backend_dir.name == "backend"
    assert (backend_dir / "app" / "core" / "settings.py").is_file()

    if backend_dir.parent.name == "webui":  # embedded in the ms-agent repo
        expected = (
            backend_dir.parent.parent / ".env",
            backend_dir.parent / ".env",
            backend_dir / ".env",
        )
    else:  # standalone checkout
        expected = (
            backend_dir.parent / ".env",
            backend_dir / ".env",
        )
    assert s._ENV_FILES == expected
    assert s.Settings.model_config["env_file"] == tuple(
        str(path) for path in expected)
