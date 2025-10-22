from __future__ import annotations
import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from typing import (Any, Callable, Dict, Iterable, List, Optional, Sequence,
                    Tuple)

import json
from ms_agent.llm.openai import OpenAIChat
from ms_agent.rag.utils import rag_mapping
from ms_agent.tools.mcp_client import MCPClient
from ms_agent.utils.logger import get_logger
from ms_agent.workflow.deep_research.research_workflow import ResearchWorkflow
from ms_agent.workflow.deep_research.research_workflow_beta import \
    ResearchWorkflowBeta
from omegaconf import DictConfig, OmegaConf

logger = get_logger()


@dataclass
class FinancialDataRecord:
    """A normalized representation for evidence used in financial reports."""

    title: str
    content: str
    source_url: str
    source_name: str
    published_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    reliability: float = 0.5
    priority: int = 0

    def to_markdown(self) -> str:
        """Render a short markdown bullet summarizing the record."""

        published = f' ({self.published_at})' if self.published_at else ''
        reliability = f' — confidence {self.reliability:.2f}' if self.reliability else ''
        title = self.title or self.metadata.get('headline',
                                                'Financial data point')
        return f'- [{title}]({self.source_url}) — {self.source_name}{published}{reliability}'


@dataclass
class FinancialEvidenceBundle:
    """Aggregated evidence used to ground the final research deliverable."""

    records: List[FinancialDataRecord] = field(default_factory=list)
    ranked_sources: List[Tuple[str, str, float]] = field(default_factory=list)
    diagnostics: List[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Convert the ranked sources into a markdown list."""

        if not self.ranked_sources:
            return '- No supporting sources were collected.'

        lines = []
        for name, url, score in self.ranked_sources:
            confidence = f'confidence {score:.2f}' if score else 'confidence N/A'
            lines.append(f'- [{name}]({url}) — {confidence}')
        return '\n'.join(lines)


class FinancialDataSource:
    """Base class for domain specific data sources.

    Sub-classes should implement :meth:`fetch` and return normalized
    :class:`FinancialDataRecord` instances.  The base class exposes a
    ``priority`` attribute that is used by the orchestrator when combining
    heterogeneous sources.
    """

    def __init__(self, name: str, priority: int = 0):
        self.name = name
        self.priority = priority

    async def fetch(self, query: str, **kwargs) -> List[FinancialDataRecord]:
        raise NotImplementedError

    def is_available(self) -> bool:
        """Return True if the source is ready to serve requests."""

        return True


class RESTFinancialDataSource(FinancialDataSource):
    """Simple REST based financial data source.

    The implementation is intentionally conservative and only depends on the
    ``requests`` package when it is available.  Missing dependencies or API
    credentials are treated as soft-failures so the rest of the workflow can
    continue using alternative evidence.
    """

    def __init__(self,
                 name: str,
                 endpoint: str,
                 method: str = 'GET',
                 query_param: Optional[str] = 'query',
                 api_key_env: Optional[str] = None,
                 api_key_param: Optional[str] = 'apikey',
                 default_params: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, str]] = None,
                 timeout: int = 15,
                 priority: int = 0,
                 parser: Optional[Callable[[Dict[str, Any]],
                                           List[FinancialDataRecord]]] = None):
        super().__init__(name=name, priority=priority)
        self.endpoint = endpoint
        self.method = method.upper()
        self.query_param = query_param
        self.api_key_env = api_key_env
        self.api_key_param = api_key_param
        self.default_params = default_params or {}
        self.headers = headers or {}
        self.timeout = timeout
        self._parser = parser

    def is_available(self) -> bool:
        if self.api_key_env and not os.getenv(self.api_key_env):
            logger.debug(
                'Skip REST data source %s because environment variable %s is missing.',
                self.name, self.api_key_env)
            return False
        return True

    async def fetch(self, query: str, **kwargs) -> List[FinancialDataRecord]:
        if not self.is_available():
            return []

        try:
            import requests
        except ImportError:
            logger.warning(
                'requests is not installed, skip financial data source %s',
                self.name)
            return []

        params: Dict[str, Any] = dict(self.default_params)
        params.update(kwargs.get('params', {}))
        if self.query_param:
            params[self.query_param] = query
        if self.api_key_env and self.api_key_param:
            params[self.api_key_param] = os.getenv(self.api_key_env)

        request_kwargs: Dict[str, Any] = {
            'headers': {
                **self.headers,
                **kwargs.get('headers', {})
            },
            'timeout': kwargs.get('timeout', self.timeout),
        }
        if self.method == 'GET':
            request_kwargs['params'] = params
        else:
            request_kwargs['json'] = params

        def _send_request() -> Optional[Dict[str, Any]]:
            try:
                response = requests.request(self.method, self.endpoint,
                                            **request_kwargs)
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # pragma: no cover - network failure
                logger.warning('Failed to query %s: %s', self.name, exc)
                return None

        loop = asyncio.get_running_loop()
        payload = await loop.run_in_executor(None, _send_request)
        if not payload:
            return []

        parser = self._parser or self._default_parser
        try:
            return parser(payload)
        except Exception as exc:
            logger.warning('Failed to parse response from %s: %s', self.name,
                           exc)
            return []

    def _default_parser(self, payload: Dict[str,
                                            Any]) -> List[FinancialDataRecord]:
        """Heuristic parser for common financial news APIs."""

        candidates: Iterable[Dict[str, Any]] = []
        if isinstance(payload, dict):
            if 'data' in payload and isinstance(payload['data'], list):
                candidates = payload['data']
            elif 'results' in payload and isinstance(payload['results'], list):
                candidates = payload['results']
            else:
                candidates = payload.values()

        records: List[FinancialDataRecord] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue

            url = item.get('url') or item.get('link')
            if not url:
                continue

            highlights = item.get('summary') or item.get('content')
            if not highlights:
                highlights = item.get('description') or json.dumps(
                    item, ensure_ascii=False)

            score = item.get('relevance_score') or item.get('relevance')
            try:
                reliability = float(score) if score is not None else 0.6
            except (TypeError, ValueError):
                reliability = 0.6

            published_at = (
                item.get('time_published') or item.get('published_at')
                or item.get('date'))

            records.append(
                FinancialDataRecord(
                    title=item.get('title') or item.get('headline')
                    or item.get('name') or 'Financial insight',
                    content=highlights,
                    source_url=url,
                    source_name=self.name,
                    published_at=published_at,
                    metadata=item,
                    reliability=reliability,
                    priority=self.priority,
                ))

        return records


class MCPFinancialDataSource(FinancialDataSource):
    """Data source backed by a registered MCP tool."""

    def __init__(self,
                 name: str,
                 client: MCPClient,
                 server_name: str,
                 tool_name: str,
                 priority: int = 0,
                 description: Optional[str] = None):
        super().__init__(name=name, priority=priority)
        self._client = client
        self._server_name = server_name
        self._tool_name = tool_name
        self.description = description

    def is_available(self) -> bool:
        if not self._client:
            return False
        return self._server_name in getattr(self._client, 'sessions', {})

    async def fetch(self, query: str, **kwargs) -> List[FinancialDataRecord]:
        if not self.is_available():
            return []

        try:
            response = await self._client.call_tool(self._server_name,
                                                    self._tool_name, {
                                                        'query': query,
                                                        **kwargs
                                                    })
        except Exception as exc:
            logger.warning('MCP data source %s failed: %s', self.name, exc)
            return []

        # Many MCP tools return JSON. Attempt to parse but fall back to text.
        records: List[FinancialDataRecord] = []
        parsed: Optional[Any] = None
        if isinstance(response, str):
            try:
                parsed = json.loads(response)
            except json.JSONDecodeError:
                parsed = None
        else:
            parsed = response

        if isinstance(parsed, dict):
            payload = [parsed]
        elif isinstance(parsed, list):
            payload = parsed
        else:
            payload = [{
                'title': self.description or self.name,
                'summary': response,
                'url': kwargs.get('fallback_url', '')
            }]

        for item in payload:
            if not isinstance(item, dict):
                continue
            url = item.get('url') or item.get('link') or kwargs.get(
                'fallback_url', '')
            content = (
                item.get('content') or item.get('summary') or item.get('text')
                or json.dumps(item, ensure_ascii=False))

            records.append(
                FinancialDataRecord(
                    title=item.get('title') or item.get('name')
                    or self.description or self.name,
                    content=content,
                    source_url=url,
                    source_name=f'MCP:{self.name}',
                    published_at=item.get('published_at'),
                    metadata=item,
                    reliability=float(item.get('confidence', 0.7)),
                    priority=self.priority,
                ))

        return records


class FinancialRAGCoordinator:
    """Thin helper around the framework's RAG abstraction."""

    def __init__(self, rag_instance=None):
        self._rag = rag_instance

    @staticmethod
    def build_from_config(config: Optional[Dict[str, Any]]):
        if not config:
            return FinancialRAGCoordinator()

        if isinstance(config, DictConfig):
            cfg = config
        else:
            cfg = OmegaConf.create(config)

        if hasattr(cfg, 'rag') and isinstance(cfg.rag, DictConfig):
            rag_section = cfg.rag
        elif hasattr(cfg, 'rag') and isinstance(cfg.rag, dict):
            rag_section = OmegaConf.create({'rag': cfg.rag}).rag
        else:
            rag_section = cfg if isinstance(
                cfg, DictConfig) else OmegaConf.create({
                    'rag': cfg
                }).rag

        name = getattr(rag_section, 'name', None)
        if not name:
            raise ValueError('RAG configuration must specify a `name`.')

        rag_cls = rag_mapping.get(name)
        if not rag_cls:
            raise ValueError(f'Unsupported RAG implementation: {name}')

        full_cfg = cfg if isinstance(cfg, DictConfig) and hasattr(
            cfg, 'rag') else OmegaConf.create({'rag': rag_section})

        rag_instance = rag_cls(full_cfg)
        return FinancialRAGCoordinator(rag_instance)

    @property
    def rag(self):
        return self._rag

    async def ingest(self, bundle: FinancialEvidenceBundle) -> bool:
        if not self._rag or not bundle.records:
            return False

        documents = []
        for record in bundle.records:
            doc = [
                f'Source: {record.source_name}', f'URL: {record.source_url}',
                f"Published: {record.published_at or 'Unknown'}",
                f'Reliability: {record.reliability:.2f}',
                f'Content:\n{record.content}'
            ]
            documents.append('\n'.join(doc))

        await self._rag.add_documents(documents)
        return True

    async def retrieve(self,
                       query: str,
                       limit: int = 5) -> List[Dict[str, Any]]:
        if not self._rag:
            return []
        return await self._rag.retrieve(
            query=query, limit=limit, score_threshold=0.0)

    @staticmethod
    def format_retrieval(results: Sequence[Dict[str, Any]]) -> str:
        if not results:
            return ''

        snippets = []
        for idx, item in enumerate(results, start=1):
            text = item.get('text') or ''
            meta = item.get('metadata') or {}
            source = meta.get('source') or meta.get(
                'url') or f'RAG snippet {idx}'
            score = item.get('score', 0.0)
            snippets.append(
                f'[RAG-{idx}] ({score:.2f}) {source}: {text[:800]}')
        return '\n'.join(snippets)


class FinancialDataOrchestrator:
    """Collects and normalises evidence from heterogeneous data sources."""

    def __init__(self,
                 workdir_structure: Dict[str, str],
                 data_sources: Optional[Sequence[FinancialDataSource]] = None,
                 rag_coordinator: Optional[FinancialRAGCoordinator] = None,
                 max_records: int = 40):
        self._workdir_structure = workdir_structure
        self._sources = sorted(
            data_sources or [], key=lambda src: src.priority, reverse=True)
        self._rag_coordinator = rag_coordinator
        self._max_records = max_records

    async def collect(
        self,
        query: str,
        learnings: Optional[Sequence[str]] = None,
        visited_urls: Optional[Sequence[str]] = None
    ) -> FinancialEvidenceBundle:
        records: List[FinancialDataRecord] = []
        diagnostics: List[str] = []

        records.extend(self._collect_from_search_cache())
        diagnostics.append(
            f'Loaded {len(records)} records from cached web search results.')

        external_records = await self._collect_from_sources(
            query=query, learnings=learnings)
        records.extend(external_records)
        diagnostics.append(
            f'Loaded {len(external_records)} records from specialised financial APIs/MCP.'
        )

        url_records = self._records_from_urls(visited_urls or [])
        records.extend(url_records)
        diagnostics.append(
            f'Loaded {len(url_records)} records from visited URLs.')

        deduped: Dict[str, FinancialDataRecord] = {}
        for record in records:
            if not record.source_url:
                continue
            existing = deduped.get(record.source_url)
            if (not existing or record.reliability > existing.reliability
                    or record.priority > existing.priority):
                deduped[record.source_url] = record

        ranked_records = sorted(
            deduped.values(),
            key=lambda rec: (rec.priority, rec.reliability),
            reverse=True)[:self._max_records]

        bundle = FinancialEvidenceBundle(
            records=ranked_records,
            ranked_sources=[(rec.source_name, rec.source_url, rec.reliability)
                            for rec in ranked_records],
            diagnostics=diagnostics,
        )

        if self._rag_coordinator:
            await self._rag_coordinator.ingest(bundle)

        return bundle

    def _collect_from_search_cache(self) -> List[FinancialDataRecord]:
        search_dir = self._workdir_structure.get('search')
        if not search_dir or not os.path.isdir(search_dir):
            return []

        records: List[FinancialDataRecord] = []
        for file_name in os.listdir(search_dir):
            if not file_name.endswith('.json'):
                continue
            file_path = os.path.join(search_dir, file_name)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning('Failed to read cached search results %s: %s',
                               file_path, exc)
                continue

            for entry in data:
                query = entry.get('query', '')
                for result in entry.get('results', []):
                    url = result.get('url')
                    if not url:
                        continue
                    highlight_scores = result.get('highlight_scores') or []
                    reliability = 0.55
                    if isinstance(highlight_scores, list) and highlight_scores:
                        try:
                            reliability = float(max(highlight_scores))
                        except (TypeError, ValueError):
                            reliability = 0.55
                    summary = (
                        result.get('summary') or result.get('markdown')
                        or ' '.join(result.get('highlights') or []))
                    records.append(
                        FinancialDataRecord(
                            title=result.get('title') or query
                            or 'Search insight',
                            content=summary,
                            source_url=url,
                            source_name='Open Web Search',
                            metadata={
                                'search_query': query,
                                'source_file': file_name
                            },
                            reliability=reliability,
                            priority=5,
                        ))

        return records

    async def _collect_from_sources(
            self, query: str,
            learnings: Optional[Sequence[str]]) -> List[FinancialDataRecord]:
        if not self._sources:
            return []

        tasks = []
        active_sources: List[FinancialDataSource] = []
        for source in self._sources:
            if not source.is_available():
                continue
            task = source.fetch(query=query, learnings=list(learnings or []))
            tasks.append(task)
            active_sources.append(source)

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        records: List[FinancialDataRecord] = []
        for source, result in zip(active_sources, results):
            if isinstance(result, Exception):
                logger.warning('Financial data source %s failed: %s',
                               source.name, result)
                continue
            records.extend(result)
        return records

    def _records_from_urls(self,
                           urls: Sequence[str]) -> List[FinancialDataRecord]:
        if not urls:
            return []

        records_local: List[FinancialDataRecord] = []
        for url in dict.fromkeys(urls):
            records_local.append(
                FinancialDataRecord(
                    title='Visited resource reference',
                    content=
                    'Reference captured from user supplied or previously visited URL.',
                    source_url=url,
                    source_name='Visited Resource',
                    metadata={},
                    reliability=0.4,
                    priority=2,
                ))
        return records_local


@dataclass
class HallucinationCheckResult:
    is_trusted: bool
    flagged_statements: List[str] = field(default_factory=list)
    citation_suggestions: Dict[str, List[str]] = field(default_factory=dict)
    summary: str = ''


class FinancialHallucinationGuard:
    """Runs post-generation hallucination checks with the LLM."""

    def __init__(self, llm_callable: Callable[..., Any],
                 parse_callable: Callable[[str], Any], system_prompt: str):
        self._llm_callable = llm_callable
        self._parse = parse_callable
        self._system_prompt = system_prompt

    async def review(
            self, report: str, evidence_bundle: FinancialEvidenceBundle
    ) -> HallucinationCheckResult:
        if not report.strip():
            return HallucinationCheckResult(
                is_trusted=False,
                flagged_statements=['Empty report.'],
                summary='Report is empty.')

        if not evidence_bundle.records:
            return HallucinationCheckResult(
                is_trusted=True,
                summary=
                'No evidence bundle available, skipping hallucination review.')

        evidence_text = '\n\n'.join([
            f'Source: {record.source_name}\nURL: {record.source_url}\nContent: {record.content[:1000]}'
            for record in evidence_bundle.records[:10]
        ])

        json_schema = {
            'name': 'hallucination_audit',
            'strict': True,
            'schema': {
                'type':
                'object',
                'properties': {
                    'summary': {
                        'type':
                        'string',
                        'description':
                        'High level assessment of report reliability.'
                    },
                    'flagged_statements': {
                        'type': 'array',
                        'items': {
                            'type': 'string'
                        }
                    },
                    'citation_suggestions': {
                        'type': 'object',
                        'additionalProperties': {
                            'type': 'array',
                            'items': {
                                'type': 'string'
                            }
                        }
                    },
                    'is_trusted': {
                        'type': 'boolean'
                    }
                },
                'required': [
                    'summary', 'flagged_statements', 'citation_suggestions',
                    'is_trusted'
                ]
            }
        }

        prompt = (
            'You are a compliance officer reviewing a financial research report. '
            'Cross-check the report against the provided evidence snippets. '
            'Flag statements that cannot be supported, and suggest citations '
            'using the source URLs. Return JSON matching the provided schema.')

        messages = [{
            'role': 'system',
            'content': self._system_prompt
        }, {
            'role':
            'user',
            'content':
            f'{prompt}\n\nReport:\n{report}\n\nEvidence:\n{evidence_text}'
        }]

        response = await self._invoke_llm(
            messages=messages,
            response_format={
                'type': 'json_schema',
                'json_schema': json_schema
            })

        data = self._parse(response.get('content', ''))
        data = data.get('hallucination_audit', {}) or data

        return HallucinationCheckResult(
            is_trusted=bool(data.get('is_trusted', True)),
            flagged_statements=data.get('flagged_statements', []),
            citation_suggestions=data.get('citation_suggestions', {}),
            summary=data.get('summary', ''),
        )

    async def _invoke_llm(self, **kwargs) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None,
                                          lambda: self._llm_callable(**kwargs))


class FinancialReportFormatter:
    """Applies structural and citation level adjustments to the report."""

    def __init__(self, required_sections: Optional[Sequence[str]] = None):
        self.required_sections = list(required_sections or [
            'Executive Summary', 'Market Overview', 'Financial Performance',
            'Risk Assessment', 'Catalysts', 'Valuation', 'Investment View',
            'Sources'
        ])

    def apply(self, report: str, evidence_bundle: FinancialEvidenceBundle,
              hallucination_report: HallucinationCheckResult) -> str:
        report = self._ensure_sections(report)
        report = self._append_sources(report, evidence_bundle)
        report = self._append_hallucination_summary(report,
                                                    hallucination_report)
        return report

    def _ensure_sections(self, report: str) -> str:
        lowered = report.lower()
        fragments = report
        for section in self.required_sections:
            header = f'## {section}'
            if header.lower() not in lowered:
                fragments += f'\n\n{header}\n\nTBD.'
        return fragments

    def _append_sources(self, report: str,
                        evidence_bundle: FinancialEvidenceBundle) -> str:
        if '## Sources' not in report:
            report += '\n\n## Sources\n\n'
        else:
            report += '\n'
        report += evidence_bundle.to_markdown()
        return report

    def _append_hallucination_summary(self, report: str,
                                      result: HallucinationCheckResult) -> str:
        report += '\n\n## Compliance Checks\n\n'
        report += f"- Overall assessment: {'Pass' if result.is_trusted else 'Needs attention'}\n"
        if result.summary:
            report += f'- Summary: {result.summary}\n'
        if result.flagged_statements:
            report += '- Flagged Statements:\n'
            for statement in result.flagged_statements:
                report += f'  - {statement}\n'
        if result.citation_suggestions:
            report += '- Citation Suggestions:\n'
            for passage, sources in result.citation_suggestions.items():
                joined = ', '.join(sources)
                report += f'  - {passage}: {joined}\n'
        return report


class FinancialResearchWorkflow(ResearchWorkflowBeta):
    """Financial research workflow with domain specific safeguards.

    This module extends :class:`DeepResearchWorkflow` with utilities that are tailored
    for generating financial research style deliverables.  The design draws
    inspiration from public resources such as Datawhale's financial research
    guidelines and open-source implementations (e.g.
    ``https://github.com/li-xiu-qi/financial_research_report``) while reusing the
    core capabilities that already exist in MS-Agent.

    Key capabilities provided here include:

    * Domain aware data source orchestration with graceful fallbacks and optional
    Model Context Protocol (MCP) integrations.
    * Hooks for local Retrieval-Augmented Generation (RAG) using the framework's
    existing abstractions.
    * Post-processing safeguards covering hallucination detection, citation
    tracing, format validation and ranked source presentation.

    The workflow is intentionally modular so users can extend or swap components
    depending on the financial datasets that are available in their environment.
    """

    def __init__(self,
                 client: OpenAIChat,
                 principle=None,
                 search_engine=None,
                 workdir: Optional[str] = None,
                 reuse: bool = False,
                 verbose: bool = False,
                 financial_data_sources: Optional[
                     Sequence[FinancialDataSource]] = None,
                 rag_config: Optional[Dict[str, Any]] = None,
                 rag_instance=None,
                 mcp_client: Optional[MCPClient] = None,
                 **kwargs):
        super().__init__(client, principle, search_engine, workdir, reuse,
                         verbose, **kwargs)

        self.default_system = (
            f'You are a senior sell-side analyst preparing institutional grade '
            f'financial research. Today is {datetime.now().strftime("%Y-%m-%d")}. '
            f'All insights must be grounded with verifiable evidence and include '
            f'clear citations. Prioritise data integrity, regulatory compliance '
            f'and balanced risk disclosures.')

        self._rag_coordinator = (
            FinancialRAGCoordinator(rag_instance) if rag_instance else
            FinancialRAGCoordinator.build_from_config(rag_config)
            if rag_config else FinancialRAGCoordinator())

        default_sources = self._build_default_sources(mcp_client)
        sources = list(financial_data_sources or []) or default_sources
        self._data_orchestrator = FinancialDataOrchestrator(
            workdir_structure=self.workdir_structure,
            data_sources=sources,
            rag_coordinator=self._rag_coordinator,
        )

        self._hallucination_guard = FinancialHallucinationGuard(
            llm_callable=self._chat,
            parse_callable=ResearchWorkflow.parse_json_from_content,
            system_prompt=self.default_system,
        )
        self._report_formatter = FinancialReportFormatter()

    def _build_default_sources(
            self,
            mcp_client: Optional[MCPClient]) -> List[FinancialDataSource]:
        sources: List[FinancialDataSource] = [
            RESTFinancialDataSource(
                name='AlphaVantage-News',
                endpoint='https://www.alphavantage.co/query',
                query_param='keywords',
                default_params={
                    'function': 'NEWS_SENTIMENT',
                    'sort': 'LATEST',
                },
                api_key_env='ALPHAVANTAGE_API_KEY',
                priority=8,
            ),
            RESTFinancialDataSource(
                name='FinancialModelingPrep',
                endpoint='https://financialmodelingprep.com/api/v3/search',
                query_param='query',
                default_params={
                    'limit': 10,
                    'exchange': 'NASDAQ'
                },
                api_key_env='FMP_API_KEY',
                api_key_param='apikey',
                priority=6,
            ),
        ]

        akshare_configs = [
            AkshareQueryConfig(
                function='stock_news_em',
                static_params={
                    'symbol': '全部',
                    'page': 1,
                    'page_size': 50
                },
                description='EastMoney Stock News',
                limit=12,
                reliability=0.66,
            ),
            AkshareQueryConfig(
                function='stock_news_em',
                static_params={
                    'symbol': '全部',
                    'page': 2,
                    'page_size': 50
                },
                description='EastMoney Stock News (page 2)',
                limit=8,
                reliability=0.6,
            ),
        ]

        sources.append(
            AkshareFinancialDataSource(
                name='Akshare',
                query_configs=akshare_configs,
                priority=7,
            ))

        if mcp_client:
            sources.append(
                MCPFinancialDataSource(
                    name='MCP-FinancialNews',
                    client=mcp_client,
                    server_name='financial-news',
                    tool_name='search_news',
                    priority=9,
                    description='Financial news feed provided via MCP.',
                ))

        return sources

    async def write_final_report(self, prompt: str, learnings: List[str],
                                 visited_urls: List[str]) -> str:
        bundle = await self._data_orchestrator.collect(
            query=prompt, learnings=learnings, visited_urls=visited_urls)

        rag_context = ''
        if self._rag_coordinator.rag:
            retrievals = await self._rag_coordinator.retrieve(
                query=prompt, limit=5)
            rag_context = FinancialRAGCoordinator.format_retrieval(retrievals)

        evidence_summary = '\n'.join(bundle.diagnostics)
        learnings_text = '\n'.join(f'<learning>{learning}</learning>'
                                   for learning in learnings)
        evidence_text = '\n'.join(record.to_markdown()
                                  for record in bundle.records)

        json_schema = {
            'name': 'financial_report',
            'strict': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'report': {
                        'type': 'string',
                        'description': 'A complete markdown research report.'
                    }
                },
                'required': ['report']
            }
        }

        user_prompt = (
            'Prepare a professional sell-side style financial research report. '
            'Incorporate the learnings, the ranked evidence list, and the '
            'retrieved RAG context. Ensure the report includes quantitative '
            'analysis, scenario discussion, risk disclosures and explicit '
            'citations. Sections should follow industry best practices.'
            f'\n\nUser prompt:\n{prompt}\n\n'
            f'Learnings:\n{learnings_text}\n\n'
            f'Collected evidence (ranked):\n{evidence_text}\n\n'
            f'Evidence diagnostics:\n{evidence_summary}\n\n'
            f'RAG context:\n{rag_context}')

        response = self._chat(
            messages=[{
                'role': 'system',
                'content': self.default_system
            }, {
                'role': 'user',
                'content': user_prompt
            }],
            response_format={
                'type': 'json_schema',
                'json_schema': json_schema
            },
            stream=False)

        response_data = ResearchWorkflow.parse_json_from_content(
            response.get('content', ''))
        response_data = response_data.get('financial_report',
                                          {}) or response_data
        report = response_data.get('report', '')

        check_result = await self._hallucination_guard.review(
            report=report, evidence_bundle=bundle)
        final_report = self._report_formatter.apply(
            report=report,
            evidence_bundle=bundle,
            hallucination_report=check_result)

        return final_report


@dataclass
class AkshareQueryConfig:
    """Configuration for invoking an ``akshare`` dataset."""

    function: str
    query_param: Optional[str] = None
    static_params: Dict[str, Any] = field(default_factory=dict)
    description: Optional[str] = None
    limit: Optional[int] = 20
    reliability: float = 0.7
    filter_field: Optional[str] = None


class AkshareFinancialDataSource(FinancialDataSource):
    """Data source that retrieves structured data from ``akshare``.

    ``akshare`` is a widely used Python package that aggregates mainland China
    and global financial datasets.  This adapter keeps the integration lazy and
    optional—if ``akshare`` (or its heavy pandas dependency) is not installed,
    the workflow simply skips this data source.

    The implementation is intentionally generic: callers provide
    :class:`AkshareQueryConfig` instances describing which ``akshare`` functions
    to call.  The adapter normalises the resulting pandas DataFrames (or other
    serialisable payloads) into :class:`FinancialDataRecord` objects with
    heuristic field detection, so existing workflows do not need to maintain a
    large amount of bespoke parsing logic.
    """

    def __init__(self,
                 name: str = 'Akshare',
                 query_configs: Optional[Sequence[AkshareQueryConfig]] = None,
                 priority: int = 5):
        super().__init__(name=name, priority=priority)
        self._query_configs = list(query_configs or [])

    @cached_property
    def _module(
            self):  # pragma: no cover - import side effects difficult to test
        try:
            import akshare  # type: ignore

            return akshare
        except Exception as exc:  # ImportError or pandas related failures
            logger.debug('akshare data source unavailable: %s', exc)
            return None

    def is_available(self) -> bool:
        return self._module is not None and bool(self._query_configs)

    async def fetch(self, query: str, **kwargs) -> List[FinancialDataRecord]:
        if not self.is_available():
            return []

        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(None, self._run_query, config, query,
                                 kwargs.get('akshare_overrides', {}))
            for config in self._query_configs
        ]

        records: List[FinancialDataRecord] = []
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result,
                          Exception):  # pragma: no cover - runtime failure
                logger.warning('akshare query failed: %s', result)
                continue
            records.extend(result)

        return records

    def _run_query(
            self, config: AkshareQueryConfig, query: str,
            overrides: Dict[str, Dict[str, Any]]) -> List[FinancialDataRecord]:
        akshare = self._module
        if not akshare:
            return []

        function = getattr(akshare, config.function, None)
        if not callable(function):
            logger.warning('akshare function %s is not callable',
                           config.function)
            return []

        params: Dict[str, Any] = dict(config.static_params)
        if config.query_param:
            params.setdefault(config.query_param, query)

        if overrides:
            params.update(overrides.get(config.function, {}))

        try:
            payload = function(**params)
        except Exception as exc:  # pragma: no cover - upstream failure
            logger.warning('akshare function %s raised %s', config.function,
                           exc)
            return []

        return self._parse_payload(payload, query, config)

    def _parse_payload(
            self, payload: Any, query: str,
            config: AkshareQueryConfig) -> List[FinancialDataRecord]:
        items: List[Dict[str, Any]] = []

        if hasattr(payload, 'to_dict'):
            try:
                items = payload.to_dict(
                    orient='records')  # type: ignore[arg-type]
            except Exception as exc:
                logger.debug('failed to convert akshare dataframe: %s', exc)
        elif isinstance(payload, list):
            items = [item for item in payload if isinstance(item, dict)]
        elif isinstance(payload, dict):
            items = [payload]
        else:
            text = str(payload)
            if not text:
                return []
            items = [{
                'title': config.description or self.name,
                'content': text
            }]

        if not items:
            return []

        enriched: List[Tuple[FinancialDataRecord, str, Dict[str, Any]]] = []
        for item in items:
            record = self._item_to_record(item, config)
            if not record:
                continue
            context = f'{record.title}\n{record.content}' if record.content else record.title
            enriched.append((record, context.lower(), item))

        if not enriched:
            return []

        query_lower = (query or '').lower()
        matching: List[FinancialDataRecord]
        if query_lower:
            if config.filter_field:
                matching = [
                    record for record, _, original in enriched
                    if query_lower in str(
                        original.get(config.filter_field, '')).lower()
                ]
            else:
                matching = [
                    record for record, context, _ in enriched
                    if query_lower in context
                ]
        else:
            matching = [record for record, _, _ in enriched]

        if not matching:
            matching = [record for record, _, _ in enriched]

        if config.limit:
            matching = matching[:config.limit]

        for record in matching:
            record.metadata.setdefault('akshare_function', config.function)
            if config.description:
                record.metadata.setdefault('akshare_dataset',
                                           config.description)
            record.reliability = config.reliability
            record.priority = max(record.priority, self.priority)

        return matching

    def _item_to_record(
            self, item: Dict[str, Any],
            config: AkshareQueryConfig) -> Optional[FinancialDataRecord]:
        lowered = {str(key).lower(): value for key, value in item.items()}

        def _pick(keys: Sequence[str]) -> Optional[str]:
            for key in keys:
                if key in lowered and lowered[key]:
                    value = lowered[key]
                    if isinstance(value, (list, dict)):
                        continue
                    return str(value)
            return None

        title = (
            _pick(['title', 'news_title', '标题', 'name', '证券简称', '股票简称'])
            or config.description or self.name)
        content = (
            _pick([
                'content', 'news_summary', '摘要', '新闻内容', 'info', '描述',
                'details'
            ]) or '')
        url = _pick(['url', 'link', '详情链接', '网页链接', '新闻链接'
                     ]) or 'https://www.akshare.xyz'
        published = _pick([
            'datetime', 'date', '时间', '发布时间', 'pub_date', '公告日期', 'report_date'
        ])

        record = FinancialDataRecord(
            title=title,
            content=content,
            source_url=url,
            source_name=f'{self.name}/{config.description or config.function}',
            published_at=published,
            metadata=item,
            reliability=config.reliability,
            priority=self.priority,
        )
        return record
