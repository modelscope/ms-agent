# Copyright (c) ModelScope Contributors. All rights reserved.
import os
import shutil
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CapabilityDescriptor:
    """Uniform descriptor for any ms-agent capability at any granularity.

    Three granularity levels:
      - project:   Full workflow (e.g. deep_research end-to-end)
      - component: Standalone subsystem (e.g. LSPCodeServer, EvidenceStore)
      - tool:      Atomic operation (e.g. replace_file_contents)

    The ``requires`` dict declares external prerequisites:

    - ``env``  – list of environment variable names that must be set.
    - ``bins`` – list of executable names that must be on ``$PATH``.

    Call :meth:`check_requires` before invocation to get a human-readable
    list of unmet requirements (empty list means all satisfied).
    """

    name: str
    version: str
    granularity: Literal['project', 'component', 'tool']

    summary: str
    description: str

    input_schema: dict
    output_schema: dict = field(default_factory=dict)

    tags: list[str] = field(default_factory=list)
    estimated_duration: Literal['seconds', 'minutes', 'hours'] = 'seconds'

    parent: str | None = None
    sub_capabilities: list[str] = field(default_factory=list)

    requires: dict = field(default_factory=dict)

    def check_requires(self) -> list[str]:
        """Validate that all declared prerequisites are satisfied.

        Returns a list of human-readable error strings for each unmet
        requirement.  An empty list means everything is available.
        """
        errors: list[str] = []

        for var in self.requires.get('env', []):
            if not os.environ.get(var):
                errors.append(
                    f'Environment variable {var} is required but not set. '
                    f'Set it via .env file, shell export, or MCP client '
                    f'env config block before starting the server.')

        for bin_name in self.requires.get('bins', []):
            if not shutil.which(bin_name):
                errors.append(
                    f'Executable "{bin_name}" is required but not found '
                    f'on $PATH. Please install it first.')

        return errors

    def to_mcp_tool(self) -> dict:
        """Convert to MCP Tool schema dict."""
        return {
            'name': self.name,
            'description': self.summary,
            'inputSchema': self.input_schema,
        }
