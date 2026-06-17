from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PersonalizationConfig:
    """Immutable container for all personalization sources.

    Created by the caller from appropriate sources (settings, project, profile),
    then passed to PersonalizationInjector.build() for prompt assembly.
    """

    global_instruction: str = ''
    project_instruction: str = ''
    user_profile: str = ''
    memory_enabled: bool = False
    memory_backend: str | None = None
