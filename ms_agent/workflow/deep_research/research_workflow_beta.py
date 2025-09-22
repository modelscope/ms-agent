# yapf: disable
import asyncio
import os
import re
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import click
from ms_agent.llm.openai import OpenAIChat
from ms_agent.rag.extraction_manager import extract_key_information
from ms_agent.tools.exa.schema import dump_batch_search_results
from ms_agent.tools.search.search_base import SearchRequest, SearchResult
from ms_agent.tools.search.search_request import get_search_request_generator
from ms_agent.utils.logger import get_logger
from ms_agent.utils.utils import remove_resource_info, text_hash
from ms_agent.workflow.deep_research.principle import MECEPrinciple, Principle
from ms_agent.workflow.deep_research.research_utils import (LearningsResponse,
                                                            ProgressTracker,
                                                            ResearchProgress,
                                                            ResearchResult)
from ms_agent.workflow.deep_research.research_workflow import ResearchWorkflow
from rich.prompt import Confirm, Prompt

logger = get_logger()


class ProgressManager:
    """Thread-safe progress manager for deep research workflow."""

    def __init__(self, initial_progress: ResearchProgress,
                 callback: Optional[Callable[[ResearchProgress], None]] = None):
        self.progress = initial_progress
        self.callback = callback
        self.lock = threading.Lock()

    def update(self, **updates):
        """Thread-safe progress update."""
        with self.lock:
            for key, value in updates.items():
                if hasattr(self.progress, key):
                    setattr(self.progress, key, value)
            if self.callback:
                # Create a copy to avoid race conditions
                progress_copy = ResearchProgress(**self.progress.model_dump())
                self.callback(progress_copy)

    def increment_completed_queries(self, current_query: Optional[str] = None):
        """Thread-safe atomic increment of completed queries."""
        with self.lock:
            self.progress.completed_queries += 1
            if current_query:
                self.progress.current_query = current_query
            if self.callback:
                progress_copy = ResearchProgress(**self.progress.model_dump())
                self.callback(progress_copy)

    def get_current(self) -> ResearchProgress:
        """Get current progress state safely."""
        with self.lock:
            return ResearchProgress(**self.progress.model_dump())


class ResearchWorkflowBeta(ResearchWorkflow):
    """
    Overview
    -------
    A deep-research workflow that orchestrates recursive web search, structured
    extraction, and final answer/report generation.

    Key Features
    ------------
    1) Deep search:
       - Recursive search architecture with auto-generated follow-up questions.
       - Tunable search breadth (queries per level) and depth (recursion levels).

    2) Query rewriting:
       - LLM-driven reformulation from the research goal.
       - Produces search requests that target heterogeneous engines (e.g., keyword,
         semantic, fielded/boolean) with engine-aware schemas.

    3) Interaction:
      - Optional human-feedback loop to clarify user intent.
      - Supports selecting the output mode (concise direct answer vs. Markdown report).

    4) Context hygiene:
       - Intermediate steps search, extract, and summarize into dense “learnings”
         to pass state cleanly between stages and avoid context drift/noise.

    5) Multimodal report generation:
       - Uses docling to extract figure/table nodes.
       - Preserves contextual linkage and captions; inserts figures/tables into the
         report while keeping ordering and references coherent.

    6) Efficiency:
       - Asynchronous workflow.
       - Ray-based acceleration for document parsing/extraction.
    """

    def __init__(self,
                 client: OpenAIChat,
                 principle: Principle = MECEPrinciple(),
                 search_engine=None,
                 workdir: str = None,
                 reuse: bool = False,
                 verbose: bool = False,
                 **kwargs):
        super().__init__(client, principle, search_engine, workdir, reuse,
                         verbose, **kwargs)

        # Additional initialization for ResearchWorkflowBeta can be added here
        self.default_system = (
            f'You are an expert researcher. Today is {datetime.now().isoformat()}. '
            f'Follow these instructions when responding:'
            f'- You may be asked to research subjects that is after your knowledge cutoff, '
            f'assume the user is right when presented with news.'
            f'- The user is a highly experienced analyst, no need to simplify it, '
            f'be as detailed as possible and make sure your response is correct.'
            f'- Be highly organized.'
            f'- Suggest solutions that I didn\'t think about.'
            f'- Be proactive and anticipate my needs.'
            f'- Treat me as an expert in all subject matter.'
            f'- Mistakes erode my trust, so be accurate and thorough.'
            f'- Provide detailed explanations, I\'m comfortable with lots of detail.'
            f'- Value good arguments over authorities, the source is irrelevant.'
            f'- Consider new technologies and contrarian ideas, not just the conventional wisdom.'
            f'You may use high levels of speculation or prediction, just flag it for me.'
        )
        self._use_ray = (
            kwargs.pop('use_ray', False)
            or str(os.environ.get('RAG_EXTRACT_USE_RAY', '0')).lower() in ('1', 'true', 'True')
        )
        self._enable_multimodal = kwargs.pop('enable_multimodal', False)
        self._kwargs = kwargs

    @staticmethod
    def _construct_workdir_structure(workdir: str) -> Dict[str, str]:
        """
        Construct the directory structure for the workflow outputs.

        your_workdir/
            ├── todo_list.md
            ├── search/
                └── search_1.json
                └── search_2.json
                └── search_3.json
            ├── resources/
                └── abc123.png
                └── xyz456.txt
                └── efg789.pdf
            ├── report.md
        """
        # TODO: tbd ...
        if not workdir:
            workdir = './outputs/workflow/default'
            logger.warning(f'Using default workdir: {workdir}')

        todo_list_md: str = os.path.join(workdir, 'todo_list.md')
        todo_list_json: str = os.path.join(workdir, 'todo_list.json')

        search_dir: str = os.path.join(workdir, 'search')
        resources_dir: str = os.path.join(workdir, ResearchWorkflow.RESOURCES)
        report_path: str = os.path.join(workdir, 'report.md')
        os.makedirs(workdir, exist_ok=True)
        os.makedirs(resources_dir, exist_ok=True)
        os.makedirs(search_dir, exist_ok=True)

        return {
            'todo_list_md': todo_list_md,
            'todo_list_json': todo_list_json,
            'search': search_dir,
            'resources_dir': resources_dir,
            'report_md': report_path,
        }

    def search(self, search_request: SearchRequest, save_path: str = None) -> Union[str, List[str]]:

        if self._reuse:
            raise ValueError(
                'Reuse mode is not supported for deep research workflow.'
                'Please set reuse to False to start a new research.'
            )

        # Perform search using the provided search request
        def search_single_request(search_request: SearchRequest):
            return self._search_engine.search(search_request=search_request)

        def filter_search_res(single_res: SearchResult):

            # TODO: Implement filtering logic

            return single_res

        search_results: List[SearchResult] = [search_single_request(search_request)]
        search_results = [
            filter_search_res(single_res) for single_res in search_results
        ]

        # TODO: Implement a more robust way to handle multiple search results
        dump_batch_search_results(
            results=search_results,
            file_path=save_path if save_path else os.path.join(self.workdir_structure['search'], 'search.json')
        )

        return save_path if save_path else os.path.join(self.workdir_structure['search'], 'search.json')

    def generate_feedback(self,
                          query: str = '',
                          num_questions: int = 3) -> List[str]:
        """Generate follow-up questions for the query to clarify the research direction."""

        user_prompt = (
            f'Given the following query from the user, ask some follow up questions '
            f'to clarify the research direction. Return a maximum of {num_questions} '
            f'questions, but feel free to return less if the original query is clear: '
            f'<query>{query}</query>')
        json_schema = {
            'name': 'follow_up_questions',
            'strict': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'questions': {
                        'type': 'array',
                        'items': {
                            'type': 'string'
                        },
                        'description': f'Follow up questions to clarify the research direction, '
                                       f'max of {num_questions}',
                        'minItems': 1,
                        'maxItems': num_questions
                    }
                },
                'required': ['questions']
            }
        }
        enhanced_prompt = f'{user_prompt}\n\nPlease respond with valid JSON that matches this schema:\n{json_schema}'

        response = self._chat(
            messages=[
                {'role': 'system', 'content': self.default_system},
                {'role': 'user', 'content': enhanced_prompt}
            ],
            stream=False)
        question_prompt = response.get('content', '')
        follow_up_questions = ResearchWorkflow.parse_json_from_content(question_prompt)
        # TODO: More robust way to handle the response
        follow_up_questions = follow_up_questions.get('follow_up_questions', []) or follow_up_questions

        return follow_up_questions.get('questions', '')

    async def generate_search_queries(
        self,
        query: str,
        learnings: Optional[List[str]] = None,
        num_queries: int = 2,
    ) -> List[SearchRequest]:

        try:
            search_request_generator = get_search_request_generator(
                engine_type=getattr(self._search_engine, 'engine_type', None),
                user_prompt=query)
        except Exception as e:
            logger.error(
                f'Error creating search request generator: {e}')
            return []

        json_schema = search_request_generator.get_json_schema(
            num_queries=num_queries)

        learnings_prompt = ''
        if learnings:
            learnings_prompt = (
                f'\n\nHere are some learnings from previous research, '
                f'use them to generate more specific queries: {", ".join(learnings)}'
            )

        rewrite_prompt = (
            f'Given the following prompt from the user, generate a list of search requests '
            f'to research the topic. Return a maximum of {num_queries} requests, but feel '
            f'free to return less if the original prompt is clear. Make sure query in each request '
            f'is unique and not similar to each other: <prompt>{query}</prompt>{learnings_prompt}'
            # f'\n\nPlease respond with valid JSON that matches provided schema:\n{json_schema}'
        )

        search_client = OpenAIChat(
            api_key=os.getenv('OPENAI_API_KEY'),
            base_url=os.getenv('OPENAI_BASE_URL'),
            model='gemini-2.5-flash',
        )
        response = search_client.chat(
            messages=[
                {'role': 'system', 'content': self.default_system},
                {'role': 'user', 'content': rewrite_prompt}
            ],
            response_format={
                'type': 'json_schema',
                'json_schema': json_schema
            },
            stream=False)

        search_requests_json = response.get('content', '')
        search_requests_data = ResearchWorkflow.parse_json_from_content(
            search_requests_json)

        if search_requests_data:
            if isinstance(search_requests_data, dict):
                search_requests_data: List[Dict[str, Any]] = search_requests_data.get(
                    'search_requests', []) or search_requests_data
            search_requests = [
                search_request_generator.create_request(search_request)
                for search_request in search_requests_data
            ][:num_queries]
            logger.info(
                f'Generated {len(search_requests)} search requests based on the query:\n{query}'
            )
        else:
            logger.warning('Warning: No search requests generated from the prompt, using default query.')
            search_requests = [search_request_generator.create_request({
                'query': query,
                'num_results': 20,
                'research_goal': 'General research on the topic'
            })]

        return search_requests

    async def _search_with_extraction(
        self, search_query: SearchRequest
    ) -> Tuple[List[str], Dict[str, str], List[str]]:
        """Perform search with extraction."""
        save_path: str = os.path.join(
            self.workdir_structure['search'],
            f'search_{text_hash(search_query.query)}.json')
        search_res_file: str = await asyncio.to_thread(
            self.search, search_request=search_query, save_path=save_path
        )
        search_results: List[Dict[str, Any]] = SearchResult.load_from_disk(
            file_path=search_res_file)

        if not search_results:
            logger.warning('Warning: No search results found.')
        prepared_resources = [
            res_d['url'] for res_d in search_results[0]['results']
        ]

        key_info_list, all_ref_items = extract_key_information(
            urls_or_files=prepared_resources,
            use_ray=self._use_ray,
            verbose=self._verbose,
            ray_num_workers=int(os.environ.get('RAG_EXTRACT_RAY_NUM_WORKERS', '0')) or None,
            ray_cpus_per_task=float(os.environ.get('RAG_EXTRACT_RAY_CPUS_PER_TASK', '1')),
        )

        context: List[str] = [
            key_info.text for key_info in key_info_list if key_info.text
        ]
        resource_map: Dict[str, str] = {}
        for item_name, dict_item in all_ref_items.items():
            doc_item = dict_item.get('item', None)
            if hasattr(doc_item, 'image') and doc_item.image:
                # Get the item extension from mimetype such as `image/png`
                item_ext: str = doc_item.image.mimetype.split('/')[-1]
                item_file_name: str = f'{text_hash(item_name)}.{item_ext}'
                item_path: str = os.path.join(
                    self.workdir_structure['resources_dir'],
                    f'{item_file_name}')
                doc_item.image.pil_image.save(item_path)
                resource_map[item_name] = os.path.join(
                    ResearchWorkflow.RESOURCES, item_file_name)

        return context, resource_map, prepared_resources

    async def process_search_results(
            self,
            query: str,
            search_results: List[str],
            num_learnings: int = 20,
            num_follow_up_questions: int = 3) -> LearningsResponse:
        """Process search results and extract learnings.

        Args:
            query: The search query
            search_results: Results from docling parser
            num_learnings: Maximum number of learnings to extract
            num_follow_up_questions: Maximum number of follow-up questions

        Returns:
            Extracted learnings and follow-up questions
        """

        # TODO: Process image and table in the search results

        if not search_results:
            logger.info(
                f'No content found and extracted for query: {query}')
            return LearningsResponse(learnings=[], follow_up_questions=[])

        json_schema = {
            'name': 'learnings_extraction',
            'strict': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'learnings': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': f'List of learnings, max of {num_learnings}'
                    },
                    'follow_up_questions': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': f'List of follow-up questions, '
                                       f'max of {num_follow_up_questions}'
                    }
                },
                'required': ['learnings', 'follow_up_questions']
            }
        }

        if isinstance(search_results, List):
            contents_text = '\n'.join([
                f'<content>\n{content}\n</content>'
                for content in search_results
            ])
        else:
            contents_text = ''

        multimodal_prompt = (
            '- The <contents> may include images and tables. '
            'Images are represented as placeholders within <resource_info>xxx</resource_info>. '
            'Tables may exist either in the form of images or as extracted text. '
            'It is required to preserve as many important images and tables as possible - '
            'do not omit them unless absolutely necessary.'
            'Note that a figure caption may immediately follow a <resource_info>xxx</resource_info> placeholder, '
            'or it may appear in another part of the document. '
            'Figures and tables must be grouped and listed after the corresponding learning '
            'under "Related figures:" and "Related tables:" sections, '
            'strictly following the example format below. '
            'The entire learning with figures and tables MUST be a single plain-text string '
            '(e.g., as the value of a JSON string field elsewhere). '
            'Do not start with { or [. Do not include any top-level braces or brackets.\n'
            'Example:\n'
            'The MARL-ODDA framework models each origin-destination (OD) pair as an agent in a DEC-POMDP setup, '
            'where agents optimize routing decisions using local observations that include static features '
            '(e.g., free-flow travel time, route identifiers) and dynamic features '
            '(e.g., marginal travel time, volume-to-capacity ratio). This approach reduces agent count by '
            'orders of magnitude compared to traveler-level agents, enabling scalability on networks like '
            'SiouxFalls and Anaheim.\n'
            'Related figures:\n'
            '- Figure 1. Network topology of SiouxFalls: <resource_info>aaaa</resource_info>\n'
            '- Figure 2. Convergence of training episodes: <resource_info>bbbb</resource_info>\n'
            'Related tables:\n'
            '- Table 1. Summary of static OD features: either <resource_info>cccc</resource_info> '
            'or a text-based table in Markdown format\n'
            '- Table 2. Comparison of routing performance across methods: either <resource_info>dddd</resource_info> '
            'or a text-based table in Markdown format\n\n'
        )
        user_prompt = (
            f'You are given a user search query and the raw text contents returned for that query. '
            f'Your task is to generate a list of learnings and some follow-up questions based on them.'
            f'\n\n<query>{query}</query>\n<contents>{contents_text}</contents>.\n\n'
            f'Instructions (follow strictly):\n'
            f'1. Requirements for learnings:\n'
            f'- Return a maximum of {num_learnings} learnings, but feel free to return '
            f'less if the contents are clear.\n'
            f'- Make sure each learning is unique and not similar to each other.\n'
            f'- The learnings should be concise and to the point, as detailed and '
            f'information dense as possible.\n'
            f'- Make sure to include any entities like people, places, companies, products, '
            f'things, etc in the learnings, as well as any exact metrics, numbers, or dates.\n'
            f'{multimodal_prompt if self._enable_multimodal else ""}'
            f'- The learnings will be used to research the topic further.\n'
            f'- Do NOT repeat the query verbatim as a learning. '
            f'Do NOT invent facts not present in <contents>.\n'
            f'2. Requirements for follow-up questions:\n'
            f'- Return a maximum of {num_follow_up_questions} follow-up questions that are '
            f'actionable for further web search, but feel free to return less if the contents are clear. '
            f'If nothing needs to be searched further, return an empty array.\n'
            f'- Make sure each follow-up question is unique and not similar to each other.\n'
            f'- The follow-up questions will be used to search further to get more information.'
            f'- Do NOT repeat the query verbatim as a follow-up question.'
            f'\n\nPlease respond with valid JSON that matches provided schema:\n{json_schema}'
        )

        response = self._chat(
            messages=[
                {'role': 'system', 'content': self.default_system},
                {'role': 'user', 'content': user_prompt}
            ],
            stream=False)

        try:
            response_data = ResearchWorkflow.parse_json_from_content(
                response.get('content', ''))
            # TODO: More robust way to handle the response
            response_data = response_data.get('learnings_extraction', {}) or response_data
        except Exception as e:
            logger.error(f'Error parsing JSON response: {e}')
            logger.error(f'Raw response content: {response.get("content", "")}')
            return LearningsResponse(learnings=[], follow_up_questions=[])

        learnings = response_data.get('learnings', [])[:num_learnings]
        follow_up_questions = response_data.get('follow_up_questions',
                                                [])[:num_follow_up_questions]

        logger.info(f'Created {len(follow_up_questions)} follow-up questions:\n{follow_up_questions}')

        return LearningsResponse(
            learnings=learnings, follow_up_questions=follow_up_questions)

    async def _process_single_query(
        self,
        search_request: SearchRequest,
        breadth: int,
        depth: int,
        learnings: Optional[List[str]] = None,
        visited_urls: Optional[List[str]] = None,
        resource_map: Optional[Dict[str, str]] = None,
        progress_manager: Optional[ProgressManager] = None
    ) -> ResearchResult:
        """Process a single search query."""
        try:
            # Perform search and extraction
            search_result, new_resource_map, new_urls = await self._search_with_extraction(
                search_request)

            # Process results
            new_breadth = max(1, breadth // 2)
            new_depth = depth - 1

            processed_results = await self.process_search_results(
                query=search_request.query,
                search_results=search_result,
                num_learnings=20,  # TODO: Make it configurable
                num_follow_up_questions=new_breadth)

            all_learnings = learnings + processed_results.learnings
            all_urls = visited_urls + new_urls
            all_resource_map = resource_map.copy()
            if resource_map:
                all_resource_map.update(new_resource_map)
            else:
                all_resource_map = new_resource_map

            # Continue deeper if needed
            if new_depth > 0 and len(processed_results.follow_up_questions) > 0:
                logger.info(
                    f'Researching deeper, breadth: {new_breadth}, '
                    f'depth: {progress_manager.get_current().current_depth + 1}'
                )
                # Use atomic increment to avoid race conditions
                if progress_manager is not None:
                    progress_manager.increment_completed_queries(search_request.query)

                # Create next query from follow-up questions
                next_query = (
                    f'Previous Query: {search_request.query}\n'
                    f'Previous research goal: {getattr(search_request, "research_goal", "")}\n'
                    f'Follow-up research directions: {", ".join(processed_results.follow_up_questions)}'
                ).strip()

                # Continue with deeper research, passing through the progress manager
                deeper_result = await self.deep_research(
                    query=next_query,
                    breadth=new_breadth,
                    depth=new_depth,
                    learnings=all_learnings,
                    visited_urls=all_urls,
                    resource_map=all_resource_map,
                    _progress_manager=progress_manager  # Pass through the same progress manager
                )
                return deeper_result
            else:
                return ResearchResult(
                    learnings=all_learnings, visited_urls=all_urls, resource_map=all_resource_map)

        except Exception as e:
            logger.error(
                f"Error processing query '{search_request.query}': {e}")
            return ResearchResult(learnings=[], visited_urls=[], resource_map={})

    async def deep_research(
        self,
        query: str,
        breadth: int = 4,
        depth: int = 2,
        learnings: Optional[List[str]] = None,
        visited_urls: Optional[List[str]] = None,
        resource_map: Optional[Dict[str, str]] = None,
        on_progress: Optional[Callable[[ResearchProgress], None]] = None,
        _progress_manager: Optional[ProgressManager] = None
    ) -> ResearchResult:
        """Perform deep research on a query.

        Args:
            query: Research query
            breadth: Number of search queries to generate per depth level
            depth: Maximum research depth
            learnings: Previous learnings to build upon
            visited_urls: Previously visited URLs
            resource_map: Previously visited resources map(images and tables)
            on_progress: Optional progress callback
            _progress_manager: Internal progress manager for recursive calls

        Returns:
            Research results with learnings and visited URLs
        """

        if learnings is None:
            learnings = []
        if visited_urls is None:
            visited_urls = []
        if resource_map is None:
            resource_map = {}

        # Initialize progress manager only at the top level and only if progress tracking is needed
        if _progress_manager is None:
            if on_progress is not None:
                initial_progress = ResearchProgress(
                    current_depth=0,
                    total_depth=depth,
                    current_breadth=breadth,
                    total_breadth=breadth,
                    total_queries=0,
                    completed_queries=0
                )
                progress_manager = ProgressManager(initial_progress, on_progress)
            else:
                progress_manager = None
        else:
            progress_manager = _progress_manager

        search_queries = await self.generate_search_queries(
            query=query, learnings=learnings, num_queries=breadth)

        # Update initial progress if progress tracking is enabled
        if progress_manager is not None:
            current_progress = progress_manager.get_current()
            # Add current level queries to total (for recursive calls)
            new_total_queries = current_progress.total_queries + len(search_queries)
            progress_manager.update(
                total_queries=new_total_queries,
                current_query=search_queries[0].query if search_queries else '',
                current_depth=current_progress.total_depth - depth + 1
            )

        # Process search queries concurrently
        tasks = []
        for search_query in search_queries:
            task = self._process_single_query(
                search_query,
                breadth=breadth,
                depth=depth,
                learnings=learnings,
                visited_urls=visited_urls,
                resource_map=resource_map,
                progress_manager=progress_manager
            )
            tasks.append(task)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results
        all_learnings = learnings.copy()
        all_urls = visited_urls.copy()
        all_resource_map = resource_map.copy()

        for result in results:
            if isinstance(result, Exception):
                logger.error(f'Error in research task: {result}')
                continue

            if isinstance(result, ResearchResult):
                all_learnings.extend(result.learnings)
                all_urls.extend(result.visited_urls)
                all_resource_map.update(result.resource_map)

        # TODO: Use a small agent take over?
        # Remove duplicates while preserving order
        unique_learnings = []
        seen_learnings = set()
        for learning in all_learnings:
            if learning not in seen_learnings:
                unique_learnings.append(learning)
                seen_learnings.add(learning)

        unique_urls = []
        seen_urls = set()
        for url in all_urls:
            if url not in seen_urls:
                unique_urls.append(url)
                seen_urls.add(url)

        return ResearchResult(
            learnings=unique_learnings,
            visited_urls=unique_urls,
            resource_map=all_resource_map
        )

    async def write_final_report(self, prompt: str,
                                 learnings: List[str],
                                 visited_urls: List[str],
                                 resource_map: Dict[str, str]) -> str:
        json_schema = {
            'name': 'report_markdown',
            'strict': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'report': {
                        'type': 'string',
                        'description': 'Final report on the topic in Markdown'
                    }
                },
                'required': ['report']
            }
        }

        multimodal_prompt = (
            'The <learnings> may include images and tables. '
            'Images are represented as placeholders within <resource_info>xxx</resource_info>. '
            'It is required to preserve important images and tables as much as possible, '
            'maintain their correct order (Figure 1, Figure 2, Table 1, Table 2, etc.), '
            'and to maintain the positional relationship between the '
            'images or tables and their surrounding context. '
            'Please make sure to add right captions/titles to the figures and tables.'
            'Please do not represent figure and table captions/titles in the following form, '
            'as this prevents proper rendering in Markdown: '
            '\"<!-- Table 1: compute achieves lower error than a handcrafted semantic operator '
            'program written in Palimpzest. -->\", '
            '\"<!-- Figure 1: An example query from the Kramabench dataset which a handcrafted '
            'semantic operator program struggles to perform well on. -->\"'
        )
        learnings_text = '\n'.join(
            [f'<learning>\n{learning}\n</learning>' for learning in learnings])
        user_prompt = (
            f'Given the following prompt from the user, write a final report on the '
            f'topic using the learnings from research. Please be sure not to use the first person.'
            f'Make it as detailed as possible, '
            f'aim for 3 or more pages, include ALL the learnings from research:\n\n'
            f'<prompt>{prompt}</prompt>\n\n'
            f'Here are all the learnings from previous research:\n\n'
            f'<learnings>\n{learnings_text}\n</learnings>'
            f'\n\nPlease respond with valid JSON that matches provided schema:\n{json_schema}\n'
            f'Please respond in the language of the <prompt>. '
            f'{multimodal_prompt if self._enable_multimodal else ""}'
        )

        response = self._chat(
            messages=[
                {'role': 'system', 'content': self.default_system},
                {'role': 'user', 'content': user_prompt}
            ],
            stream=False)

        try:
            response_data = ResearchWorkflow.parse_json_from_content(
                response.get('content', ''))
        except Exception as e:
            logger.error(f'Error parsing JSON from response: {e}')
            # try to fix the response
            fix_prompt = (
                f'The response is not valid JSON. Please fix it. '
                f'You can only return the fixed JSON, no other text. '
                f'The response is: {response.get("content", "")}'
            )
            response = self._chat(
                messages=[
                    {'role': 'system', 'content': 'You are a helpful assistant.'},
                    {'role': 'user', 'content': fix_prompt}
                ],
                stream=False)
            try:
                response_data = ResearchWorkflow.parse_json_from_content(
                    response.get('content', ''))
            except Exception as e:
                logger.error(f'Error parsing JSON from fixed response: {e}')
                return response.get('content', '')

        # TODO: More robust way to handle the response
        response_data = response_data.get('report_markdown', {}) or response_data
        report = response_data.get('report', '')

        if self._enable_multimodal:
            replace_pattern = r'!\[[^\]]*\]\(<resource_info>(.*?)</resource_info>\)'
            report = re.sub(replace_pattern, r'<resource_info>\1</resource_info>', report)
            for item_name, item_relative_path in resource_map.items():
                report = report.replace(
                    f'src="<resource_info>{item_name}</resource_info>"',
                    f'src="{item_relative_path}"',
                    1
                ).replace(
                    f'<resource_info>{item_name}</resource_info>',
                    f'![{os.path.basename(item_relative_path)}]({item_relative_path})<br>',
                    1
                )
            report = remove_resource_info(report)

        # Append sources section
        sources_section = f"\n\n## Sources\n\n{chr(10).join([f'- {url}' for url in visited_urls])}"
        return report + sources_section

    async def write_final_answer(self, prompt: str,
                                 learnings: List[str]) -> str:
        json_schema = {
            'name': 'exact_answer',
            'strict': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'answer': {
                        'type': 'string',
                        'description': 'The final answer, short and concise'
                    }
                },
                'required': ['answer']
            }
        }

        learnings_text = '\n'.join(
            [f'<learning>\n{learning}\n</learning>' for learning in learnings])
        user_prompt = (
            f'Given the following prompt from the user, write a final answer on the '
            f'topic using the learnings from research. Follow the format specified in '
            f'the prompt. Do not yap or babble or include any other text than the answer '
            f'besides the format specified in the prompt. Keep the answer as concise as '
            f'possible - usually it should be just a few words or maximum a sentence. '
            f'Try to follow the format specified in the prompt.\n\n'
            f'<prompt>{prompt}</prompt>\n\n'
            f'Here are all the learnings from research on the topic that you can use '
            f'to help answer the prompt:\n\n'
            f'<learnings>\n{learnings_text}\n</learnings>'
            f'\n\nPlease respond with valid JSON that matches provided schema:\n{json_schema}\n'
            f'Please respond in the language of the prompt.')

        response = self._chat(
            messages=[
                {'role': 'system', 'content': self.default_system},
                {'role': 'user', 'content': user_prompt}
            ],
            stream=False
        )

        try:
            response_data = ResearchWorkflow.parse_json_from_content(
                response.get('content', ''))
        except Exception as e:
            logger.error(f'Error parsing JSON from response: {e}')
            return response.get('content', '')

        # TODO: More robust way to handle the response
        response_data = response_data.get('exact_answer', {}) or response_data

        if self._enable_multimodal:
            logger.warning('Multimodal is not supported for short answer.')

        return response_data.get('answer', '')

    async def run(self,
                  user_prompt: str,
                  breadth: int = 4,
                  depth: int = 2,
                  is_report: bool = False,
                  show_progress: bool = False,
                  **kwargs) -> None:

        if not user_prompt:
            initial_query = Prompt.ask(
                '\n[bold]What would you like to research?[/bold]')
            breadth = click.prompt(
                'Enter research breadth (recommended 2-10)',
                type=int,
                default=4,
                show_default=True)
            depth = click.prompt(
                'Enter research depth (recommended 1-5)',
                type=int,
                default=2,
                show_default=True)
            # Choose output format
            is_report = not Confirm.ask(
                'Generate specific answer instead of detailed report?',
                default=False)
        else:
            initial_query = user_prompt

        try:
            follow_up_questions: List[str] = self.generate_feedback(
                query=initial_query, num_questions=3)
            if follow_up_questions:
                logger.info('Follow-up questions:\n'
                            + '\n'.join(follow_up_questions))
                answer = input('Please enter you answer: ')
                questions_text = '\n'.join(follow_up_questions)
                combined_query = (
                    f'Initial Query:\n{initial_query}\n'
                    f'Follow-up Questions:\n{questions_text}\n'
                    f'User\'s Answers:\n{answer}')
        except Exception as e:
            logger.info(
                'Error generating follow-up questions, proceeding with initial query only...\n'
                + f'Error: {e}')
            combined_query = initial_query

        if show_progress:
            # Perform research with progress tracking
            with ProgressTracker() as tracker:
                try:
                    result = await self.deep_research(
                        query=combined_query,
                        breadth=breadth,
                        depth=depth,
                        on_progress=tracker.update_progress)
                except Exception as e:
                    logger.error(f'Error during deep research: {e}')
                    return
        else:
            result = await self.deep_research(
                query=combined_query, breadth=breadth, depth=depth)

        # Display results
        logger.info('Research Complete!')
        logger.info(f'Learnings ({len(result.learnings)}):')
        if self._verbose:
            for i, learning in enumerate(result.learnings, 1):
                logger.info(f'{i}. {learning}')
        logger.info(f'\nVisited URLs ({len(result.visited_urls)})')
        if self._verbose:
            for url in result.visited_urls:
                logger.info(f'- {url}')

        logger.info('Writing final output...')
        try:
            if is_report:
                # Generate and save report
                report = await self.write_final_report(
                    prompt=combined_query,
                    learnings=result.learnings,
                    visited_urls=result.visited_urls,
                    resource_map=result.resource_map)

                if self._verbose:
                    logger.info(f'\n\nFinal Report Content:\n{report}')

                # Dump report to markdown file
                with open(
                        self.workdir_structure['report_md'], 'w',
                        encoding='utf-8') as f_report:
                    f_report.write(report)
                logger.info(
                    f'Report saved to {self.workdir_structure["report_md"]}')
            else:
                # Generate and save answer
                answer = await self.write_final_answer(
                    prompt=combined_query, learnings=result.learnings)

                if self._verbose:
                    logger.info(f'\n\nFinal Answer:\n{answer}')

                # Dump answer to markdown file
                with open(
                        self.workdir_structure['report_md'], 'w',
                        encoding='utf-8') as f_answer:
                    f_answer.write(answer)
                logger.info(
                    f'Answer saved to {self.workdir_structure["report_md"]}')

        except Exception as e:
            logger.error(f'Error generating final output: {e}')
