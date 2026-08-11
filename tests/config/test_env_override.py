# Copyright (c) ModelScope Contributors. All rights reserved.
"""Config.from_task matches config leaf keys against env names case-insensitively
to allow overrides (e.g. OPENAI_API_KEY -> llm.openai_api_key). Ambient shell
vars (PATH/HOME/...) must be excluded from that source, else a config key like
``path`` (skills sources[].path) is silently clobbered by the shell's $PATH."""
import sys
from unittest.mock import patch

from ms_agent.config import Config


def _cfg_dir(tmp_path, body):
    (tmp_path / 'agent.yaml').write_text(body)
    return str(tmp_path)


def test_path_key_not_clobbered_by_env_PATH(tmp_path, monkeypatch):
    monkeypatch.setenv('PATH', '/usr/bin:/bin:/sentinel/from/shell')
    d = _cfg_dir(tmp_path, (
        'llm:\n  service: openai\n  model: m\n'
        'skills:\n  sources:\n    - type: local\n'
        '      path: /marker/skills/dir\n'))
    with patch.object(sys, 'argv', ['ms-agent']):
        cfg = Config.from_task(d)
    assert cfg.skills.sources[0].path == '/marker/skills/dir'


def test_home_key_not_clobbered_by_env_HOME(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', '/Users/somebody')
    d = _cfg_dir(tmp_path,
                 'llm:\n  service: openai\n  model: m\n  home: /keep/this\n')
    with patch.object(sys, 'argv', ['ms-agent']):
        cfg = Config.from_task(d)
    assert cfg.llm.home == '/keep/this'


def test_non_shell_env_override_still_applies(tmp_path, monkeypatch):
    # A non-blocklisted env var must still override a same-named config key —
    # the feature the blocklist must NOT break.
    monkeypatch.setenv('MODEL', 'env-model-xyz')
    d = _cfg_dir(tmp_path, 'llm:\n  service: openai\n  model: file-model\n')
    with patch.object(sys, 'argv', ['ms-agent']):
        cfg = Config.from_task(d)
    assert cfg.llm.model == 'env-model-xyz'
