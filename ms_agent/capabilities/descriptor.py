# Copyright (c) Alibaba, Inc. and its affiliates.
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CapabilityDescriptor:
    """Uniform descriptor for any ms-agent capability at any granularity.

    Three granularity levels:
      - project:   Full workflow (e.g. deep_research end-to-end)
      - component: Standalone subsystem (e.g. LSPCodeServer, EvidenceStore)
      - tool:      Atomic operation (e.g. replace_file_contents)
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

    def to_mcp_tool(self) -> dict:
        """Convert to MCP Tool schema dict."""
        return {
            'name': self.name,
            'description': self.summary,
            'inputSchema': self.input_schema,
        }
