# Copyright (c) Alibaba, Inc. and its affiliates.
# flake8: noqa
import os
from typing import Any, Dict, List, Tuple

import json
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from spec_constant import (PRINCIPLE_ROUTING_GUIDE, PRINCIPLE_SPEC_GUIDE,
                           WRITING_ROUTING_GUIDE, WRITING_SPEC_GUIDE)

logger = get_logger()


class SpecLoader(ToolBase):
    """Aggregate access to multiple specs for financial reports.

    Server name: `spec_loader`

    This tool exposes functions `load_<x>_specs` that loads one or more
    spec files and returns their content to the model. Each
    spec provides concise rules and examples on how to structure and phrase
    financial analysis reports in an analyst-like style.
    The underlying knowledge is stored as Markdown files and can be configured via
    `tools.spec_loader.spec_dir` in the agent config. When not provided,
    the tool falls back to `projects/fin_research/tools/specs`
    under the current working directory.

    Supported spec tools (case-insensitive, synonyms allowed):
    - writing_specs → writing_specs/xxxx.md
    - principle_specs → principle_specs/xxxx.md
    """

    SPEC_DIR = 'projects/fin_research/tools/specs'

    def __init__(self, config):
        super().__init__(config)
        tools_cfg = getattr(config, 'tools',
                            None) if config is not None else None
        spec_cfg = getattr(tools_cfg, 'spec_loader',
                           None) if tools_cfg is not None else None
        self.exclude_func(spec_cfg)

        configured_dir = getattr(spec_cfg, 'spec_dir',
                                 None) if spec_cfg is not None else None
        default_dir = os.path.join(os.getcwd(), self.SPEC_DIR)
        self.spec_dir = configured_dir or default_dir

    async def connect(self):
        # Warn once if the directory cannot be found; still operate to allow deferred config
        if not os.path.isdir(self.spec_dir):
            logger.warning_once(
                f'Spec directory not found: {self.spec_dir}. '
                f'Configure tools.spec_loader.spec_dir or ensure default exists.'
            )

    async def get_tools(self) -> Dict[str, Any]:
        tools: Dict[str, List[Tool]] = {
            'spec_loader': [
                Tool(
                    tool_name='load_writing_specs',
                    server_name='spec_loader',
                    description=
                    ('Load one or more writing-style specs (rules + examples) and return '
                     'their curated Markdown content. Use this when you are unsure about '
                     'how to structure or phrase a financial report in an analyst-like style.\n\n'
                     'Supported spec identifiers (case-insensitive, synonyms allowed):\n'
                     '- structure → section depth / headings\n'
                     '- methods → how much to expose MECE/SWOT/etc.\n'
                     '- bullets → bullets vs paragraphs\n'
                     '- focus → task focus and relevance\n'
                     '- tone → analyst-style voice\n'
                     '- density → length and information density control\n\n'
                     'Provide a list of requested writing specs via the "writing_specs" parameter.\n\n'
                     f'{WRITING_SPEC_GUIDE}\n'
                     f'{WRITING_ROUTING_GUIDE}\n'),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'writing_specs': {
                                'type':
                                'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description':
                                ('List of writing specs to load. Case-insensitive; supports synonyms.\n'
                                 'Allowed identifiers include (non-exhaustive):\n'
                                 '- structure\n- methods\n- bullets\n- focus\n- tone\n- density\n'
                                 ),
                            },
                            'format': {
                                'type':
                                'string',
                                'enum': ['markdown', 'json'],
                                'description':
                                ('Output format: "markdown" (combined Markdown string) or "json" '
                                 '(JSON object mapping spec to content). Default: "markdown".'
                                 ),
                            },
                            'include_titles': {
                                'type':
                                'boolean',
                                'description':
                                ('When format="markdown", if true, each section is prefixed with a '
                                 'Markdown heading of the canonical spec title. Default: false.'
                                 ),
                            },
                            'join_with': {
                                'type':
                                'string',
                                'description':
                                ('When format="markdown", the delimiter used to join multiple '
                                 'sections. Default: "\n\n---\n\n".'),
                            },
                            'strict': {
                                'type':
                                'boolean',
                                'description':
                                ('If true, unknown specs cause an error. If false, unknown items are '
                                 'ignored with a note in the output. Default: false.'
                                 ),
                            },
                        },
                        'required': ['writing_specs'],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='load_principle_specs',
                    server_name='spec_loader',
                    description=
                    (f'Load one or more analysis principles (concept + how to apply to '
                     f'financial analysis) and return their curated Markdown content.\n\n'
                     f'This is a single-aggregator tool designed to fetch multiple principles '
                     f'in one call. Provide a list of requested principles via the "principles" '
                     f'parameter. The tool supports common synonyms and is case-insensitive.\n\n'
                     f'Examples of valid principle identifiers: "MECE", "Pyramid", "Minto", '
                     f'"SWOT", "Value Chain", "Pareto", "80-20", "80/20", "Boston Matrix", "BCG".\n\n'
                     f'When format is "markdown" (default), the tool returns a single combined '
                     f'Markdown string (optionally including section titles). When format is '
                     f'"json", the tool returns a JSON object mapping principle to content.\n'
                     f'{PRINCIPLE_SPEC_GUIDE}\n'
                     f'{PRINCIPLE_ROUTING_GUIDE}\n'),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'principles': {
                                'type':
                                'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description':
                                ('List of principles to load. Case-insensitive; supports synonyms.\n'
                                 'Allowed identifiers include (non-exhaustive):\n'
                                 '- MECE\n- Pyramid\n- Minto\n- SWOT\n- Value Chain\n'
                                 '- Pareto\n- 80-20\n- 80/20\n- Boston Matrix\n- BCG\n'
                                 ),
                            },
                            'format': {
                                'type':
                                'string',
                                'enum': ['markdown', 'json'],
                                'description':
                                ('Output format: "markdown" (combined Markdown string) or "json" '
                                 '(JSON object mapping principle to content). Default: "markdown".'
                                 ),
                            },
                            'include_titles': {
                                'type':
                                'boolean',
                                'description':
                                ('When format="markdown", if true, each section is prefixed with a '
                                 'Markdown heading of the canonical principle title. Default: false.'
                                 ),
                            },
                            'join_with': {
                                'type':
                                'string',
                                'description':
                                ('When format="markdown", the delimiter used to join multiple '
                                 'sections. Default: "\n\n---\n\n".'),
                            },
                            'strict': {
                                'type':
                                'boolean',
                                'description':
                                ('If true, unknown principles cause an error. If false, unknown '
                                 'items are ignored with a note in the output. Default: false.'
                                 ),
                            },
                        },
                        'required': ['principles'],
                        'additionalProperties': False,
                    },
                )
            ]
        }

        if hasattr(self, 'exclude_functions') and self.exclude_functions:
            tools['spec_loader'] = [
                t for t in tools['spec_loader']
                if t['tool_name'] not in self.exclude_functions
            ]

        return tools

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        return await getattr(self, tool_name)(**tool_args)

    async def load_writing_specs(self, writing_specs: List[str],
                                 **kwargs) -> str:
        writing_spec_map = self._build_writing_spec_index()
        return await self.load_specs(writing_spec_map, writing_specs, **kwargs)

    async def load_principle_specs(self, principles: List[str],
                                   **kwargs) -> str:
        principle_map = self._build_principle_spec_index()
        return await self.load_specs(principle_map, principles, **kwargs)

    async def load_specs(
        self,
        spec_map: Dict[str, Tuple[str, str]],
        specs: List[str],
        format: str = 'markdown',
        include_titles: bool = False,
        join_with: str = '\n\n---\n\n',
        strict: bool = False,
    ) -> str:
        """Load requested specs documents and return their content.

        Returns:
            str: Markdown string (default) or JSON string mapping spec to content.
        """

        if not specs:
            return json.dumps(
                {
                    'success': False,
                    'error': 'No specs provided.'
                },
                ensure_ascii=False,
                indent=2,
            )

        resolved: Dict[str, Tuple[str, str]] = {}
        unknown: List[str] = []
        for name in specs:
            key = self._normalize_name(name)
            if key in spec_map:
                resolved[name] = spec_map[key]
            else:
                unknown.append(name)

        if unknown and strict:
            return json.dumps(
                {
                    'success': False,
                    'error':
                    'Unknown specs (strict mode): ' + ', '.join(unknown),
                },
                ensure_ascii=False,
                indent=2,
            )

        loaded: Dict[str, str] = {}
        for _, (filename, canonical_title) in resolved.items():
            path = os.path.join(self.spec_dir, filename)
            try:
                with open(path, 'r') as f:
                    content = f.read().strip()
                loaded[canonical_title] = content
            except Exception as e:  # noqa
                loaded[
                    canonical_title] = f'Failed to load {filename}: {str(e)}'

        if not loaded:
            return json.dumps(
                {
                    'success': False,
                    'error': 'Failed to load any specs.'
                },
                ensure_ascii=False,
                indent=2,
            )

        if format == 'json':
            payload = {
                'success': True,
                'specs': loaded,
                'unknown': unknown,
                'source_dir': self.spec_dir,
            }
            return json.dumps(payload, ensure_ascii=False)

        # Default: markdown
        sections: List[str] = []
        for title, content in loaded.items():
            if include_titles:
                sections.append(f'# {title}\n\n{content}')
            else:
                sections.append(content)

        if unknown and not strict:
            sections.append(
                f'> Note: Unknown specs ignored: {", ".join(unknown)}')

        return json.dumps(
            {
                'success': True,
                'sections': join_with.join(sections)
            },
            ensure_ascii=False,
            indent=2)

    def _build_writing_spec_index(self) -> Dict[str, Tuple[str, str]]:
        """Return writing spec mapping from normalized query → (filename, canonical title)."""
        entries = [
            # synonyms, filename, canonical title
            (
                ['structure', 'structure & layering', 'layering', 'sections'],
                'writing_specs/Structure_Layering.md',
                'Structure & Layering',
            ),
            (
                [
                    'methods', 'methodology', 'framework exposure',
                    'methodology exposure'
                ],
                'writing_specs/Methodology_Exposure.md',
                'Methodology Exposure',
            ),
            (
                [
                    'bullets', 'bullet', 'bullets & paragraphs',
                    'paragraph rhythm'
                ],
                'writing_specs/Bullets_Paragraph_Rhythm.md',
                'Bullets & Paragraph Rhythm',
            ),
            (
                ['focus', 'relevance', 'task focus', 'task focus & relevance'],
                'writing_specs/Task_Focus_Relevance.md',
                'Task Focus & Relevance',
            ),
            (
                ['tone', 'voice', 'analyst voice', 'tone & analyst voice'],
                'writing_specs/Tone_Analyst_Voice.md',
                'Tone & Analyst Voice',
            ),
            (
                ['density', 'length', 'density & length', 'length control'],
                'writing_specs/Density_Length_Control.md',
                'Density & Length Control',
            ),
        ]

        index: Dict[str, Tuple[str, str]] = {}
        for synonyms, filename, title in entries:
            for s in synonyms:
                index[self._normalize_name(s)] = (filename, title)
        return index

    def _build_principle_spec_index(self) -> Dict[str, Tuple[str, str]]:
        """Return principle spec mapping from normalized query → (filename, canonical title)."""
        entries: List[Tuple[List[str], str, str]] = [
            # synonyms, filename, canonical title
            (['mece', 'mutually exclusive and collectively exhaustive'],
             'principle_specs/MECE.md', 'MECE'),
            ([
                'pyramid', 'minto', 'minto pyramid', 'pyramid principle',
                'minto_pyramid'
            ], 'principle_specs/Minto_Pyramid.md', 'Pyramid (Minto Pyramid)'),
            (['swot', 'swot analysis'], 'principle_specs/SWOT.md', 'SWOT'),
            (['value chain', 'value-chain',
              'value_chain'], 'principle_specs/Value_Chain.md', 'Value Chain'),
            ([
                'pareto', '80-20', '80/20', 'pareto 80-20', 'pareto_80-20',
                '8020'
            ], 'principle_specs/Pareto_80-20.md', 'Pareto (80/20 Rule)'),
            ([
                'boston matrix', 'bcg', 'boston consulting group',
                'boston_matrix', 'boston'
            ], 'principle_specs/Boston_Matrix.md', 'Boston Matrix (BCG)'),
        ]

        index: Dict[str, Tuple[str, str]] = {}
        for synonyms, filename, title in entries:
            for s in synonyms:
                index[self._normalize_name(s)] = (filename, title)
        return index

    @staticmethod
    def _normalize_name(name: str) -> str:
        s = (name or '').strip().lower()
        s = s.replace('_', ' ').replace('-', ' ')
        s = ' '.join(s.split())  # collapse whitespace

        # normalize 80/20 variants, specially for principle specs
        s = s.replace('80/20', '80-20').replace('80 20', '80-20')
        s = s.replace('8020', '80-20')

        return s
