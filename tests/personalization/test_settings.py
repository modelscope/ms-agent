import json

import pytest

from ms_agent.personalization.settings import PersonalizationSettings
from ms_agent.personalization.types import PersonalizationConfig


class TestPersonalizationSettings:

    @pytest.fixture
    def settings_dir(self, tmp_path):
        d = tmp_path / '.ms_agent'
        d.mkdir()
        return d

    @pytest.fixture
    def settings(self, settings_dir):
        return PersonalizationSettings(global_dir=str(settings_dir))

    def test_load_missing_file(self, tmp_path):
        s = PersonalizationSettings(global_dir=str(tmp_path / 'nonexistent'))
        config = s.load()
        assert config.global_instruction == ''
        assert config.memory_enabled is False
        assert config.memory_backend is None

    def test_load_missing_section(self, settings_dir):
        (settings_dir / 'settings.json').write_text(
            json.dumps({'llm': {'model': 'test'}})
        )
        s = PersonalizationSettings(global_dir=str(settings_dir))
        config = s.load()
        assert config.global_instruction == ''

    def test_load_from_settings_json(self, settings_dir):
        data = {
            'llm': {'model': 'qwen'},
            'personalization': {
                'global_instruction': 'Be concise.',
                'memory_enabled': True,
                'memory_backend': 'mem0',
            },
        }
        (settings_dir / 'settings.json').write_text(json.dumps(data))
        s = PersonalizationSettings(global_dir=str(settings_dir))
        config = s.load()
        assert config.global_instruction == 'Be concise.'
        assert config.memory_enabled is True
        assert config.memory_backend == 'mem0'

    def test_save_creates_file(self, tmp_path):
        d = tmp_path / 'new_dir'
        s = PersonalizationSettings(global_dir=str(d))
        config = PersonalizationConfig(
            global_instruction='Test instruction',
            memory_enabled=True,
        )
        s.save(config)
        assert (d / 'settings.json').exists()
        loaded = s.load()
        assert loaded.global_instruction == 'Test instruction'
        assert loaded.memory_enabled is True

    def test_save_preserves_other_keys(self, settings_dir):
        original = {
            'llm': {'model': 'gpt-4', 'provider': 'openai'},
            'theme': 'dark',
            'output_dir': './output',
        }
        (settings_dir / 'settings.json').write_text(json.dumps(original))

        s = PersonalizationSettings(global_dir=str(settings_dir))
        s.save(PersonalizationConfig(global_instruction='New'))

        with open(settings_dir / 'settings.json', 'r') as f:
            result = json.load(f)
        assert result['llm'] == {'model': 'gpt-4', 'provider': 'openai'}
        assert result['theme'] == 'dark'
        assert result['output_dir'] == './output'
        assert result['personalization']['global_instruction'] == 'New'

    def test_save_overwrites_personalization_section(self, settings):
        settings.save(PersonalizationConfig(global_instruction='First'))
        settings.save(PersonalizationConfig(global_instruction='Second'))
        assert settings.load().global_instruction == 'Second'

    def test_memory_defaults_roundtrip(self, settings):
        config = PersonalizationConfig(
            memory_enabled=True,
            memory_backend='file_based',
        )
        settings.save(config)
        loaded = settings.load()
        assert loaded.memory_enabled is True
        assert loaded.memory_backend == 'file_based'

    def test_memory_backend_none_roundtrip(self, settings):
        config = PersonalizationConfig(memory_backend=None)
        settings.save(config)
        loaded = settings.load()
        assert loaded.memory_backend is None

    def test_load_corrupt_json(self, settings_dir):
        (settings_dir / 'settings.json').write_text('not valid json{{{')
        s = PersonalizationSettings(global_dir=str(settings_dir))
        config = s.load()
        assert config.global_instruction == ''

    def test_project_instruction_not_persisted(self, settings):
        """project_instruction comes from Project, not settings.json."""
        config = PersonalizationConfig(
            global_instruction='G',
            project_instruction='P',
        )
        settings.save(config)
        loaded = settings.load()
        assert loaded.global_instruction == 'G'
        assert loaded.project_instruction == ''
