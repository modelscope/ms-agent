# Copyright (c) ModelScope Contributors. All rights reserved.
"""Lightweight discovery primitives for local Agent Skills.

Discovery intentionally reads only ``SKILL.md``.  Full file materialization,
safety scanning, and registration remain the catalog's responsibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class SkillDescriptor:
    """Metadata discovered from a skill root without walking support files."""

    skill_id: str
    name: str
    description: str
    content: str
    version: str = 'latest'
    author: Optional[str] = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    skill_path: Path = field(default_factory=lambda: Path.cwd().resolve())

    @property
    def key(self) -> str:
        return f'{self.skill_id}@{self.version}'
