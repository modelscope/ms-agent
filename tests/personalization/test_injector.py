from ms_agent.personalization.injector import PersonalizationInjector
from ms_agent.personalization.types import PersonalizationConfig


class TestPersonalizationInjector:

    def test_all_sources_present(self):
        config = PersonalizationConfig(
            global_instruction='Be concise.',
            project_instruction='Use FastAPI.',
            user_profile='Name: Alice',
        )
        result = PersonalizationInjector.build(config)
        assert 'Be concise.' in result
        assert 'Use FastAPI.' in result
        assert 'Name: Alice' in result

    def test_empty_sources_returns_empty(self):
        config = PersonalizationConfig()
        assert PersonalizationInjector.build(config) == ''

    def test_whitespace_only_sources_returns_empty(self):
        config = PersonalizationConfig(
            global_instruction='   ',
            project_instruction='\n\t',
            user_profile='  \n  ',
        )
        assert PersonalizationInjector.build(config) == ''

    def test_partial_sources_global_only(self):
        config = PersonalizationConfig(global_instruction='Be helpful.')
        result = PersonalizationInjector.build(config)
        assert '## Custom Instructions' in result
        assert '## Project Instructions' not in result
        assert '## User Profile' not in result

    def test_partial_sources_project_only(self):
        config = PersonalizationConfig(project_instruction='Use TypeScript.')
        result = PersonalizationInjector.build(config)
        assert '## Custom Instructions' not in result
        assert '## Project Instructions' in result
        assert '## User Profile' not in result

    def test_partial_sources_profile_only(self):
        config = PersonalizationConfig(user_profile='Role: Engineer')
        result = PersonalizationInjector.build(config)
        assert '## Custom Instructions' not in result
        assert '## Project Instructions' not in result
        assert '## User Profile' in result

    def test_section_headers_present(self):
        config = PersonalizationConfig(
            global_instruction='G',
            project_instruction='P',
            user_profile='U',
        )
        result = PersonalizationInjector.build(config)
        assert '## Custom Instructions' in result
        assert '## Project Instructions' in result
        assert '## User Profile' in result

    def test_global_before_project_before_profile(self):
        config = PersonalizationConfig(
            global_instruction='GLOBAL',
            project_instruction='PROJECT',
            user_profile='PROFILE',
        )
        result = PersonalizationInjector.build(config)
        gi = result.index('GLOBAL')
        pi = result.index('PROJECT')
        ui = result.index('PROFILE')
        assert gi < pi < ui

    def test_sections_separated_by_blank_lines(self):
        config = PersonalizationConfig(
            global_instruction='A',
            project_instruction='B',
        )
        result = PersonalizationInjector.build(config)
        assert '\n\n' in result

    def test_content_is_stripped(self):
        config = PersonalizationConfig(
            global_instruction='  leading and trailing  ',
        )
        result = PersonalizationInjector.build(config)
        assert 'leading and trailing' in result
        assert result.endswith('trailing')

    def test_multiline_content_preserved(self):
        instruction = 'Line 1\nLine 2\nLine 3'
        config = PersonalizationConfig(global_instruction=instruction)
        result = PersonalizationInjector.build(config)
        assert 'Line 1\nLine 2\nLine 3' in result


class TestPersonalizationConfig:

    def test_frozen(self):
        config = PersonalizationConfig(global_instruction='test')
        try:
            config.global_instruction = 'new'  # type: ignore[misc]
            assert False, 'Should raise FrozenInstanceError'
        except AttributeError:
            pass

    def test_defaults(self):
        config = PersonalizationConfig()
        assert config.global_instruction == ''
        assert config.project_instruction == ''
        assert config.user_profile == ''
        assert config.memory_enabled is False
        assert config.memory_backend is None
