# yapf: disable
import asyncio
import copy
import os
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import click
import json
from ms_agent.llm.openai import OpenAIChat
from ms_agent.rag.extraction import HierarchicalKeyInformationExtraction
from ms_agent.rag.schema import KeyInformation
from ms_agent.tools.exa.schema import dump_batch_search_results
from ms_agent.tools.search.search_base import SearchRequest, SearchResult
from ms_agent.tools.search.search_request import get_search_request_generator
from ms_agent.utils.logger import get_logger
from ms_agent.utils.utils import remove_resource_info, text_hash
from ms_agent.workflow.principle import MECEPrinciple, Principle
from ms_agent.workflow.research import (LearningsResponse, ProgressTracker,
                                        ResearchProgress, ResearchRequest,
                                        ResearchResponse, ResearchResult)
from ms_agent.workflow.research_workflow import ResearchWorkflow
from rich.prompt import Confirm, Prompt

logger = get_logger()


class DeepResearchWorkflow(ResearchWorkflow):
    """
    Deep Research Workflow for advanced research tasks.
    Inherits from ResearchWorkflow and can be extended with more features.
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

        # Additional initialization for DeepResearchWorkflow can be added here
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
            # Load existing search results if they exist
            if os.path.exists(self.workdir_structure['search']) and os.listdir(self.workdir_structure['search']):
                logger.info(
                    f"Loaded existing search results from {self.workdir_structure['search']}"
                )
                return [os.path.join(self.workdir_structure['search'], f)
                        for f in os.listdir(self.workdir_structure['search'])]
            else:
                logger.warning(
                    f"Warning: Search results file not found for `reuse` mode: {self.workdir_structure['search']}"
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
            # response_format={
            #     'type': 'json_schema',
            #     'json_schema': json_schema
            # },
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
            raise ValueError(
                f'Error creating search request generator: {e}') from e

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
            base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
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
                f'Generated {len(search_requests)} search requests based on the query: {query}'
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
        search_res_file: str = self.search(search_request=search_query, save_path=save_path)
        search_results: List[Dict[str, Any]] = SearchResult.load_from_disk(
            file_path=search_res_file)

        if not search_results:
            logger.warning('Warning: No search results found.')
        prepared_resources = [
            res_d['url'] for res_d in search_results[0]['results']
        ]

        extractor = HierarchicalKeyInformationExtraction(
            urls_or_files=prepared_resources, verbose=self._verbose)
        key_info_list: List[KeyInformation] = extractor.extract()

        context: List[str] = [
            key_info.text for key_info in key_info_list if key_info.text
        ]
        resource_map: Dict[str, str] = {}
        for item_name, dict_item in extractor.all_ref_items.items():
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
            resource_map: Dict[str, str],
            num_learnings: int = 3,
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
            logger.warning(
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

        if isinstance(search_results, List) and search_results:
            contents_text = '\n'.join([
                f'<content>\n{content}\n</content>'
                for content in search_results
            ])
        else:
            contents_text = ''

        user_prompt = (
            f'Given the following contents from a search for the query '
            f'<query>{query}</query>, generate a list of learnings from the contents. '
            f'Return a maximum of {num_learnings} learnings, but feel free to return '
            f'less if the contents are clear. Make sure each learning is unique and not '
            f'similar to each other. The learnings should be concise and to the point, '
            f'as detailed and information dense as possible. Make sure to include any '
            f'entities like people, places, companies, products, things, etc in the '
            f'learnings, as well as any exact metrics, numbers, or dates. The learnings '
            f'will be used to research the topic further.\n\n<contents>{contents_text}</contents>'
            f'\n\nPlease respond with valid JSON that matches provided schema:\n{json_schema}'
        )

        response = self._chat(
            messages=[
                {'role': 'system', 'content': self.default_system},
                {'role': 'user', 'content': user_prompt}
            ],
            # response_format={
            #     'type': 'json_schema',
            #     'json_schema': json_schema
            # },
            stream=False)

        response_data = ResearchWorkflow.parse_json_from_content(
            response.get('content', ''))
        # TODO: More robust way to handle the response
        response_data = response_data.get('learnings_extraction', {}) or response_data

        learnings = response_data.get('learnings', [])[:num_learnings]
        follow_up_questions = response_data.get('follow_up_questions',
                                                [])[:num_follow_up_questions]

        logger.info(f'Created {len(learnings)} learnings: {learnings}')

        return LearningsResponse(
            learnings=learnings, follow_up_questions=follow_up_questions)

    async def _process_single_query(
        self,
        search_request: SearchRequest,
        breadth: int,
        depth: int,
        learnings: Optional[List[str]] = None,
        visited_urls: Optional[List[str]] = None,
        report_progress: Optional[Callable[[ResearchProgress], None]] = None
    ) -> ResearchResult:
        """Process a single search query."""
        try:
            # Perform search and extraction
            search_result, resource_map, new_urls = await self._search_with_extraction(
                search_request)

            # Process results
            new_breadth = max(1, breadth // 2)
            new_depth = depth - 1

            processed_results = await self.process_search_results(
                query=search_request.query,
                search_results=search_result,
                resource_map=resource_map,
                num_follow_up_questions=new_breadth)

            all_learnings = learnings + processed_results.learnings
            all_urls = visited_urls + new_urls

            # Continue deeper if needed
            if new_depth > 0:
                logger.info(
                    f'Researching deeper, breadth: {new_breadth}, depth: {new_depth}'
                )

                report_progress({
                    'current_depth': new_depth,
                    'current_breadth': new_breadth,
                    'completed_queries': 1,  # This is incremental
                    'current_query': search_request.query
                })

                # Create next query from follow-up questions
                next_query = (
                    f"Previous research goal: {getattr(search_request, 'research_goal', '')}\n"
                    f"Follow-up research directions: {', '.join(processed_results.follow_up_questions)}"
                ).strip()

                return await self.deep_research(
                    query=next_query,
                    breadth=new_breadth,
                    depth=new_depth,
                    learnings=all_learnings,
                    visited_urls=all_urls,
                    on_progress=None  # Don't pass progress to avoid duplication
                )
            else:
                report_progress({
                    'current_depth': 0,
                    'completed_queries': 1,
                    'current_query': search_request.query
                })
                return ResearchResult(
                    learnings=all_learnings, visited_urls=all_urls)

        except Exception as e:
            logger.error(
                f"Error processing query '{search_request.query}': {e}")
            return ResearchResult(learnings=[], visited_urls=[])

    async def deep_research(
        self,
        query: str,
        breadth: int,
        depth: int,
        learnings: Optional[List[str]] = None,
        visited_urls: Optional[List[str]] = None,
        on_progress: Optional[Callable[[ResearchProgress], None]] = None
    ) -> ResearchResult:
        """Perform deep research on a query.

        Args:
            query: Research query
            breadth: Number of search queries to generate per depth level
            depth: Maximum research depth
            learnings: Previous learnings to build upon
            visited_urls: Previously visited URLs
            on_progress: Optional progress callback

        Returns:
            Research results with learnings and visited URLs
        """

        def report_progress(update: dict) -> None:
            """Update progress and call callback if provided."""
            for key, value in update.items():
                setattr(progress, key, value)
            if on_progress:
                on_progress(progress)

        if learnings is None:
            learnings = []
        if visited_urls is None:
            visited_urls = []

        progress = ResearchProgress(
            current_depth=depth,
            total_depth=depth,
            current_breadth=breadth,
            total_breadth=breadth,
            total_queries=0,
            completed_queries=0)

        search_queries = await self.generate_search_queries(
            query=query, learnings=learnings, num_queries=breadth)

        report_progress({
            'total_queries': len(search_queries),
            'current_query': search_queries[0].query if search_queries else None
        })

        # Process search queries concurrently
        tasks = []
        for search_query in search_queries:
            task = self._process_single_query(search_query, breadth, depth,
                                              learnings, visited_urls,
                                              report_progress)
            tasks.append(task)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results
        all_learnings = learnings.copy()
        all_urls = visited_urls.copy()

        for result in results:
            if isinstance(result, Exception):
                logger.error(f'Error in research task: {result}')
                continue

            if isinstance(result, ResearchResult):
                all_learnings.extend(result.learnings)
                all_urls.extend(result.visited_urls)

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
            learnings=unique_learnings, visited_urls=unique_urls)

    async def write_final_report(self, prompt: str, learnings: List[str],
                                 visited_urls: List[str]) -> str:
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

        learnings_text = '\n'.join(
            [f'<learning>\n{learning}\n</learning>' for learning in learnings])
        user_prompt = (
            f'Given the following prompt from the user, write a final report on the '
            f'topic using the learnings from research. Make it as detailed as possible, '
            f'aim for 3 or more pages, include ALL the learnings from research:\n\n'
            f'<prompt>{prompt}</prompt>\n\n'
            f'Here are all the learnings from previous research:\n\n'
            f'<learnings>\n{learnings_text}\n</learnings>'
            f'\n\nPlease respond with valid JSON that matches provided schema:\n{json_schema}')

        response = self._chat(
            messages=[
                {'role': 'system', 'content': self.default_system},
                {'role': 'user', 'content': user_prompt}
            ],
            # response_format={
            #     'type': 'json_schema',
            #     'json_schema': json_schema
            # },
            stream=False)

        response_data = ResearchWorkflow.parse_json_from_content(
            response.get('content', ''))
        # TODO: More robust way to handle the response
        response_data = response_data.get('report_markdown', {}) or response_data
        report = response_data.get('report', '')

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
                'required': ['exact_answer']
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
            f'\n\nPlease respond with valid JSON that matches provided schema:\n{json_schema}')

        response = self._chat(
            messages=[
                {'role': 'system', 'content': self.default_system},
                {'role': 'user', 'content': user_prompt}
            ],
            # response_format={
            #     'type': 'json_schema',
            #     'json_schema': json_schema
            # },
            stream=False
        )
        response_data = ResearchWorkflow.parse_json_from_content(
            response.get('content', ''))
        # TODO: More robust way to handle the response
        response_data = response_data.get('exact_answer', {}) or response_data

        return response_data.get('answer', '')

    async def run(self,
                  user_prompt: str,
                  breadth: int = 4,
                  depth: int = 2,
                  is_report: bool = False,
                  **kwargs) -> None:

        is_multimodal = kwargs.get('enable_multimodal', False)
        if is_multimodal:
            raise ValueError('Multimodal is not supported yet.')

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
                query=initial_query)
            if follow_up_questions:
                # TODO: Slit qa into n times.
                logger.info('Follow-up questions:\n'
                            + '\n'.join(follow_up_questions))
                answer = input('Please enter you answer: ')
                questions_text = '\n'.join(follow_up_questions)
                combined_query = (
                    f'Initial Query:\n{user_prompt}\n'
                    f'Follow-up Questions:\n{questions_text}\n'
                    f'User\'s Answers:\n{answer}')
        except Exception as e:
            logger.info(
                'Error generating follow-up questions, proceeding with initial query only...\n'
                + f'Error: {e}')
            combined_query = initial_query

        logger.info('\nStarting deep research...')
        show_progress = kwargs.get('show_progress', False)
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
                    logger.error(f'Error during research: {e}')
                    return
        else:
            result = await self.deep_research(
                query=combined_query, breadth=breadth, depth=depth)

        # Display results
        logger.info('\nResearch Complete!')
        logger.info(f'Learnings ({len(result.learnings)}):')
        for i, learning in enumerate(result.learnings, 1):
            logger.info(f'{i}. {learning}')
        logger.info(f'\nVisited URLs ({len(result.visited_urls)})')
        for url in result.visited_urls:
            logger.info(f'- {url}')

        logger.info('\nWriting final output...')
        try:
            if is_report:
                # Generate and save report
                report = await self.write_final_report(
                    prompt=combined_query,
                    learnings=result.learnings,
                    visited_urls=result.visited_urls)

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
