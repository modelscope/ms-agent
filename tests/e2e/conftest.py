"""Shared fixtures for TUI / WebUI ledger e2e tests.

Both sides must share one ``MS_AGENT_HOME``. These tests never touch
``~/.ms_agent``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf

from ms_agent.prompting import workspace_files as wf

from tests.e2e.helpers import DummyLLM

SDK_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEBUI_BACKEND = Path(
    os.environ.get(
        'MS_AGENT_WEBUI_BACKEND',
        '/Users/luyan/workspace/ms-agent-webui-feat-tui-align/backend',
    ))

try:
    from dotenv import load_dotenv
    load_dotenv(SDK_ROOT / '.env')
except Exception:
    pass


def pytest_configure(config):
    config.addinivalue_line(
        'markers',
        'live: hits a real model / search provider (needs API key in .env)',
    )
    config.addinivalue_line(
        'markers',
        'usability: user/developer-facing contract that may xfail on product bugs',
    )


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / 'ms_agent_home'
    home.mkdir()
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    monkeypatch.delenv('MS_AGENT_LLM_MODEL', raising=False)
    monkeypatch.delenv('MS_AGENT_LLM_PROVIDER', raising=False)
    wf.reset_cache()
    yield home
    wf.reset_cache()


@pytest.fixture
def work_dir(tmp_path):
    work = tmp_path / 'align-work'
    work.mkdir()
    return work


@pytest.fixture
def stub_llm_rebuild(monkeypatch):
    """Let ``/model <id>`` persist without talking to a real gateway."""

    def _from_config(config):
        return DummyLLM(
            config,
            str(OmegaConf.select(config, 'llm.model', default='') or ''),
        )

    monkeypatch.setattr('ms_agent.llm.LLM.from_config', _from_config)
    return _from_config


def webui_backend() -> Path:
    if not DEFAULT_WEBUI_BACKEND.is_dir():
        pytest.skip(f'WebUI backend not found: {DEFAULT_WEBUI_BACKEND}')
    return DEFAULT_WEBUI_BACKEND


def _ensure_webui_on_path() -> Path:
    backend = webui_backend()
    inserted = str(backend)
    if inserted not in sys.path:
        sys.path.insert(0, inserted)
    return backend


@pytest.fixture
def webui(isolated_home):
    """Import GitLab WebUI adapters against the isolated home.

    Adapters read ``MS_AGENT_HOME`` on each call, so they see the same
    ledger TUI slash commands write.
    """
    _ensure_webui_on_path()
    from app.backends.ms_agent import (
        agent_settings,
        instructions,
        mcps,
        profile,
        projects,
        providers,
        search,
        sessions,
        skills,
    )
    return SimpleNamespace(
        agent_settings=agent_settings,
        instructions=instructions,
        mcps=mcps,
        profile=profile,
        projects=projects,
        providers=providers,
        search=search,
        sessions=sessions,
        skills=skills,
    )


@pytest.fixture
def webui_client(isolated_home):
    """HTTP TestClient for the GitLab WebUI backend (same isolated home)."""
    _ensure_webui_on_path()
    pytest.importorskip('fastapi')
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client
    try:
        from app.backends.ms_agent.skill_index import skill_index
        skill_index.stop()
    except Exception:
        pass
