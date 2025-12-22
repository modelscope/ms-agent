# Copyright (c) Alibaba, Inc. and its affiliates.
# flake8: noqa
import os
from typing import Any, Dict, List, Optional, Tuple

import json
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger

logger = get_logger()

PRINCIPLE_GUIDE = """
<Principle Quick Guide & Usage Notes>
- **MECE (Mutually Exclusive, Collectively Exhaustive) — non-overlapping, no-omission framing**
  - **Use for:** Building problem & metric trees, defining scopes and boundaries, avoiding gaps/duplication.
  - **Best for:** Kick-off structuring of any report (industry/company/portfolio/risk).
  - **Deliverable:** 3-5 first-level dimensions; second-level factors with measurement definitions; a “Problem → Scope → Metrics” blueprint.

- **Value Chain (Porter) — sources of cost/value**
  - **Use for:** Explaining fundamentals and levers behind Gross Margin / ROIC (primary + support activities).
  - **Best for:** Company & supply-chain research; cost curve and pass-through analysis.
  - **Deliverable:** Stage → Drivers → Bottlenecks → Improvements → Financial impact (quantified to GM/Cash Flow/KPIs).

- **BCG Growth-Share Matrix (Boston Matrix) — growth x share portfolio positioning**
  - **Use for:** Placing multi-business/multi-track items into Star/Cash Cow/Question Mark/Dog to guide resource/weighting decisions.
  - **Best for:** Comparing industry sub-segments; managing company business portfolios.
  - **Deliverable:** Quadrant mapping; capital/attention flow plan (e.g., from Cows → Stars/Questions); target weights and migration triggers.

- **80/20 (Pareto) — focus on the vital few**
  - **Use for:** Selecting the top ~20% drivers that explain most outcomes across metrics/assets/factors; compressing workload.
  - **Best for:** Return/risk attribution; metric prioritization; evidence triage.
  - **Deliverable:** Top-K key drivers + quantified contributions + tracking KPIs; fold the remainder into “long-tail management.”

- **SWOT → TOWS — from inventory to action pairing**
  - **Use for:** Pairing internal (S/W) and external (O/T) to form SO/WO/ST/WT **actionable strategies** with KPIs.
  - **Best for:** Strategy setting, post-investment management, risk hedging and adjustment thresholds.
  - **Deliverable:** Action list with owners/KPIs/thresholds and financial mapping (revenue/GM/cash-flow impact).

- **Pyramid / Minto — conclusion-first presentation wrapper**
  - **Use for:** Packaging analysis as “Answer → 3 parallel supports → key evidence/risk hedges” for fast executive reading.
  - **Best for:** Executive summaries, IC materials, report front pages.
  - **Deliverable:** One-sentence conclusion (direction + range + time frame), three parallel key points, strongest evidence charts.
</Principle Quick Guide & Usage Notes>
"""
ROUTING_GUIDE = """
<Composition & Routing (Model Selection Hints)>
Here are some Heuristic hints for selecting the appropriate principles for the task:
- Need to “frame & define scope”? → Start with **MECE**; if explaining costs/moats, add **Value Chain**.
- Multi-business/multi-track “allocation decisions”? → Use **BCG** for positioning & weights, then **80/20** to focus key drivers.
- Want to turn inventory into **executable actions**? → **SWOT→TOWS** for strategy+KPI and threshold design.
- Delivering to management? → Present the whole piece with **Pyramid**; other principles provide evidence and structural core.
</Composition & Routing (Model Selection Hints)>
"""


class PrincipleSkill(ToolBase):
    """Aggregate access to multiple analysis principles.

    Server name: `principle_skill`

    This tool exposes a single function `load_principles` that loads one or more
    principle knowledge files and returns their content to the model. Each
    principle provides concise concept definitions and guidance on how to apply
    the principle to financial analysis and report writing. The underlying
    knowledge is stored as Markdown files and can be configured via
    `tools.principle_skill.principle_dir` in the agent config. When not provided,
    the tool falls back to `projects/fin_research/tools/principles`
    under the current working directory.

    Supported principle identifiers (case-insensitive, synonyms allowed):
    - MECE  → MECE.md
    - Pyramid / Minto / Minto Pyramid → Minto_Pyramid.md
    - SWOT  → SWOT.md
    - Value Chain → Value_Chain.md
    - Pareto / 80-20 / 80/20 → Pareto_80-20.md
    - Boston Matrix / BCG / Boston Consulting Group → Boston_Matrix.md
    """

    PRINCIPLE_DIR = 'projects/fin_research/tools/principles'

    def __init__(self, config):
        super().__init__(config)
        tools_cfg = getattr(config, 'tools',
                            None) if config is not None else None
        self.exclude_func(getattr(tools_cfg, 'principle_skill', None))

        configured_dir = None
        if tools_cfg is not None:
            configured_dir = getattr(tools_cfg, 'principle_dir', None)

        default_root = os.getcwd()
        default_dir = os.path.join(default_root, self.PRINCIPLE_DIR)

        # If a config-specified directory exists, prefer it; else use default.
        self.principle_dir = configured_dir or default_dir

        # Build a mapping from normalized user inputs to on-disk filenames and display names
        self._name_to_file: Dict[str,
                                 Tuple[str,
                                       str]] = self._build_principle_index()

    async def connect(self):
        # Warn once if the directory cannot be found; still operate to allow deferred config
        if not os.path.isdir(self.principle_dir):
            logger.warning_once(
                f'[principle_skill] Principle directory not found: {self.principle_dir}. '
                f'Configure tools.principle_skill.principle_dir or ensure default exists.'
            )

    async def _get_tools_inner(self) -> Dict[str, Any]:
        tools = {
            'principle_skill': [
                Tool(
                    tool_name='load_principles',
                    server_name='principle_skill',
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
                     f'{PRINCIPLE_GUIDE}\n'
                     f'{ROUTING_GUIDE}\n'),
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
                                 'Markdown heading of the canonical principle title. Default: true.'
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
        return tools

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        return await getattr(self, tool_name)(**tool_args)

    async def load_principles(
        self,
        principles: List[str],
        format: str = 'markdown',
        include_titles: bool = False,
        join_with: str = '\n\n---\n\n',
        strict: bool = False,
    ) -> str:
        """Load requested principle documents and return their content.

        Returns:
            str: Markdown string (default) or JSON string mapping principle → content.
        """

        if not principles:
            return json.dumps(
                {
                    'success': False,
                    'error': 'No principles provided.'
                },
                ensure_ascii=False,
                indent=2,
            )

        resolved: Dict[str, Tuple[str, str]] = {}
        unknown: List[str] = []
        for name in principles:
            key = self._normalize_name(name)
            if key in self._name_to_file:
                resolved[name] = self._name_to_file[key]
            else:
                unknown.append(name)

        if unknown and strict:
            return json.dumps(
                {
                    'success':
                    False,
                    'error':
                    'Unknown principles (strict mode): ' + ', '.join(unknown)
                },
                ensure_ascii=False,
                indent=2,
            )

        loaded: Dict[str, str] = {}
        for original_name, (filename, canonical_title) in resolved.items():
            path = os.path.join(self.principle_dir, filename)
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
                    'error': 'Failed to load any principles.'
                },
                ensure_ascii=False,
                indent=2,
            )

        if format == 'json':
            payload = {
                'success': True,
                'principles': loaded,
                'unknown': unknown,
                'source_dir': self.principle_dir,
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
                f'> Note: Unknown principles ignored: {", ".join(unknown)}')

        return json.dumps(
            {
                'success': True,
                'sections': sections
            },
            ensure_ascii=False,
            indent=2,
        )

    def _build_principle_index(self) -> Dict[str, Tuple[str, str]]:
        """Return mapping from normalized query → (filename, canonical title)."""
        entries: List[Tuple[List[str], str, str]] = [
            # synonyms, filename, canonical title
            (['mece', 'mutually exclusive and collectively exhaustive'],
             'MECE.md', 'MECE'),
            ([
                'pyramid', 'minto', 'minto pyramid', 'pyramid principle',
                'minto_pyramid'
            ], 'Minto_Pyramid.md', 'Pyramid (Minto Pyramid)'),
            (['swot', 'swot analysis'], 'SWOT.md', 'SWOT'),
            (['value chain', 'value-chain',
              'value_chain'], 'Value_Chain.md', 'Value Chain'),
            ([
                'pareto', '80-20', '80/20', 'pareto 80-20', 'pareto_80-20',
                '8020'
            ], 'Pareto_80-20.md', 'Pareto (80/20 Rule)'),
            ([
                'boston matrix', 'bcg', 'boston consulting group',
                'boston_matrix', 'boston'
            ], 'Boston_Matrix.md', 'Boston Matrix (BCG)'),
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
        # normalize 80/20 variants
        s = s.replace('80/20', '80-20').replace('80 20', '80-20')
        s = s.replace('8020', '80-20')
        return s
