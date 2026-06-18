from __future__ import annotations

from ms_agent.personalization.types import PersonalizationConfig


class PersonalizationInjector:
    """Builds the personalization section for system prompt injection.

    Stateless builder -- all data is passed in, no I/O.
    """

    HEADER_GLOBAL = '## Custom Instructions'
    HEADER_PROJECT = '## Project Instructions'
    HEADER_PROFILE = '## User Profile'

    @staticmethod
    def build(config: PersonalizationConfig) -> str:
        """Assemble personalization content with labeled Markdown headers.

        Injection order (later items provide more specific context):
          1. Global instruction
          2. Project instruction
          3. User profile

        Returns empty string if all sources are empty.
        """
        sections: list[str] = []

        if config.global_instruction.strip():
            sections.append(
                f'{PersonalizationInjector.HEADER_GLOBAL}\n\n'
                f'{config.global_instruction.strip()}'
            )

        if config.project_instruction.strip():
            sections.append(
                f'{PersonalizationInjector.HEADER_PROJECT}\n\n'
                f'{config.project_instruction.strip()}'
            )

        if config.user_profile.strip():
            sections.append(
                f'{PersonalizationInjector.HEADER_PROFILE}\n\n'
                f'{config.user_profile.strip()}'
            )

        return '\n\n'.join(sections)
