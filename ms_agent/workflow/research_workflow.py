# flake8: noqa
# yapf: disable
import copy
import os
import re
from typing import Any, Dict, List, Union

import json
from ms_agent.llm.openai import OpenAIChat
from ms_agent.rag.extraction import HierarchicalKeyInformationExtraction
from ms_agent.rag.schema import KeyInformation
from ms_agent.tools.exa import ExaSearchRequest, ExaSearchResult
from ms_agent.tools.exa.schema import dump_batch_search_results
from ms_agent.utils.logger import get_logger
from ms_agent.utils.thread_util import thread_executor
from ms_agent.utils.utils import remove_resource_info, text_hash
from ms_agent.workflow.principle import Principle

logger = get_logger()


class ResearchWorkflow:
    RESOURCES = 'resources'

    def __init__(
            self,
            client: OpenAIChat,
            principle: Principle,
            search_engine=None,  # todo
            workdir: str = None,
            reuse: bool = False,
            **kwargs):
        self._client = client
        self._principle = principle
        self._search_engine = search_engine
        self._reuse = reuse

        self._todo_d: Dict[str, Any] = {
            'markdown': None,
            'py': None,
        }

        # History messages： TODO: should be implemented in the `Agent` class
        ## User Message: {'role': 'user', 'content': 'xxx'}
        ## Assistant Message: {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'abc123', 'type': 'function', 'function': {'name': 'get_current_weather', 'arguments': '{\"location\": \"Hangzhou, China\", \"unit\": \"celsius\"}'}}]}
        ## Tool Message: {'role': 'tool', 'tool_call_id': 'abc123', 'content': '{\"temperature\": 25, \"unit\": \"celsius\", \"description\": \"clear\"}'}
        self._history: List[Dict[str, Any]] = []

        self.default_system = 'You are a helpful assistant.'

        # Construct output directory for current workflow
        self.workdir = workdir
        self.workdir_structure: Dict[
            str, str] = self._construct_workdir_structure(workdir)

        # Init pdf parser  Note: unused
        # self.parser_workdir = self.workdir_structure['resources_dir']

    @staticmethod
    def _construct_workdir_structure(workdir: str) -> Dict[str, str]:
        """
        Construct the directory structure for the workflow outputs.

        your_workdir/
            ├── todo_list.md
            ├── search.json
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

        search_json: str = os.path.join(workdir, 'search.json')
        resources_dir: str = os.path.join(workdir, ResearchWorkflow.RESOURCES)
        report_path: str = os.path.join(workdir, 'report.md')
        os.makedirs(workdir, exist_ok=True)
        os.makedirs(resources_dir, exist_ok=True)

        return {
            'todo_list_md': todo_list_md,
            'todo_list_json': todo_list_json,
            'search': search_json,
            'resources_dir': resources_dir,
            'report_md': report_path,
        }

    def _chat(self,
              messages: List[Dict[str, Any]],
              tools: List[Dict[str, Any]] = None,
              **kwargs):

        stream: bool = kwargs.get('stream', True)

        if stream:
            stream_chunks = self._client.chat_stream(
                messages=messages, tools=tools, **kwargs)
            chunk_list = []
            for chunk in stream_chunks:
                chunk_new = copy.deepcopy(
                    chunk)  # Ensure we do not modify the original chunk
                chunk_list.append(chunk_new)

            aggregated_chunks = self._client.aggregate_stream_chunks(chunk_list)

            return aggregated_chunks
        else:
            return self._client.chat(messages=messages, tools=tools, **kwargs)

    def breakdown(self, user_prompt: str, **kwargs) -> None:
        """
        Generate a breakdown of the task into a systematic analysis plan.
        """

        if self._reuse:
            if os.path.exists(self.workdir_structure['todo_list_md']):
                logger.info(
                    f"Skip breakdown, using existing todo list for `reuse` mode: {self.workdir_structure['todo_list_md']}"
                )
                return

        messages = [{
            'role': 'system',
            'content': self.default_system,
        }, {
            'role':
                'user',
            'content':
                f'{user_prompt}{self._principle.breakdown_prompt}'
        }]
        self._history.extend(messages)

        round_d: Dict[str, Any] = self._chat(messages=messages, **kwargs)

        assistant_msg: Dict[str, Any] = self._client.convert_message(
            role='assistant',
            round_message=round_d,
        )
        self._history.append(assistant_msg)

        # # Add todo content
        # todo_content: str = assistant_msg.get('content', '').strip()
        # assert todo_content, "todo content cannot be empty."
        # self._todo_d['markdown'] = todo_content

    def generate_todo(self, **kwargs) -> None:
        """
        Generate a `todo-list` based on the breakdown.
        """

        if self._reuse and self._load_todo_file():
            # Load existing todolist file if it exists
            print(
                f">>Loaded existing todo list from {self.workdir_structure['todo_list_md']}"
            )
            return

        messages: List[Dict[str, Any]] = [self._history[-1]]
        user_todo_msg: Dict[str, Any] = {
            'role': 'user',
            'content': f'{self._principle.todo_prompt}'
        }
        self._history.append(user_todo_msg)
        messages.append(user_todo_msg)

        round_d: Dict[str, Any] = self._chat(
            messages=messages, tools=None, **kwargs)

        assistant_msg: Dict[str, Any] = self._client.convert_message(
            role='assistant',
            round_message=round_d,
        )
        self._history.append(assistant_msg)

        todo_content: str = round_d['content']
        assert todo_content.strip(), 'Todo content cannot be empty.'
        self._todo_d['markdown'] = todo_content
        logger.info(f'>>todo_content: {todo_content}')

        # Convert `todo-list` to Python list format
        messages_new: List[Dict[str, Any]] = [{
            'role':
                'user',
            'content':
                f'{todo_content}{self._principle.convert_todo_prompt}'
        }]
        round_d_new: Dict[str, Any] = self._chat(
            messages=messages_new, tools=None, **kwargs)
        todo_py_content: str = round_d_new['content']
        assert todo_py_content.strip(
        ), 'Converted todo content py-format cannot be empty.'
        todo_py_list: List[Dict[str,
        Any]] = self.parse_json_from_content(todo_py_content)
        self._todo_d['py'] = todo_py_list

        self._dump_todo_file()

    def search(self, search_requests: List[ExaSearchRequest]) -> str:

        if self._reuse:
            # Load existing search results if they exist
            if os.path.exists(self.workdir_structure['search']):
                logger.info(
                    f"Loaded existing search results from {self.workdir_structure['search']}"
                )
                return self.workdir_structure['search']
            else:
                logger.warning(
                    f"Warning: Search results file not found for `reuse` mode: {self.workdir_structure['search']}"
                )

        # Perform search using the provided search request
        @thread_executor()
        def search_single_request(search_request: ExaSearchRequest):
            return self._search_engine.search(search_request=search_request)

        def filter_search_res(single_res: ExaSearchResult):
            results_new = []
            results = single_res.response.results
            for res in results:
                if res.url.startswith('https://arxiv.org/abs/') or res.url.startswith(
                        'https://arxiv.org/pdf/'):
                    res.url = res.url.replace('arxiv.org/abs', 'arxiv.org/pdf')
                elif res.url.startswith('https://arxiv.org/html/'):
                    res.url = res.url.replace('arxiv.org/html', 'arxiv.org/pdf')
                results_new.append(res)
            single_res.response.results = results_new

            return single_res

        search_results: List[ExaSearchResult] = search_single_request(search_requests)
        search_results = [
            filter_search_res(single_res) for single_res in search_results
        ]
        dump_batch_search_results(results=search_results, file_path=self.workdir_structure['search'])

        return self.workdir_structure['search']

    @staticmethod
    def parse_json_from_content(text_content: str) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Parses the given text content to extract JSON format data.

        Args:
            text_content (str): The text content containing JSON format data.

        Returns:
            list: A dict or list of dictionaries representing the target data.
        """
        pattern = r'```json(.*?)```'

        matches = re.findall(pattern, text_content, re.DOTALL)

        if len(matches) == 0:
            return []

        try:
            items = json.loads(matches[0].strip())
            return items
        except json.JSONDecodeError as e:
            raise ValueError(f'parse_py_todo: JSON decoding error: {e}') from e

    def _dump_todo_file(self):

        md_content: str = self._todo_d.get('markdown', '')
        with open(
                self.workdir_structure['todo_list_md'], 'w',
                encoding='utf-8') as f_md:
            f_md.write(md_content)

        with open(
                self.workdir_structure['todo_list_json'], 'w',
                encoding='utf-8') as f_json:
            json.dump(
                self._todo_d.get('py', []),
                f_json,
                ensure_ascii=False,
                indent=2)

        logger.info(
            f"Todo list saved to {self.workdir_structure['todo_list_md']} and {self.workdir_structure['todo_list_json']}"
        )

    def _load_todo_file(self) -> bool:
        """
        Load the todo list from the markdown file and parse it into a Python list.
        """
        if not os.path.exists(
                self.workdir_structure['todo_list_md']) or not os.path.exists(
            self.workdir_structure['todo_list_json']):
            logger.warning(
                f"Warning: Todo list markdown file not found: {self.workdir_structure['todo_list_md']}"
            )
            return False

        with open(
                self.workdir_structure['todo_list_md'], 'r',
                encoding='utf-8') as f_md:
            md_content = f_md.read()

        with open(
                self.workdir_structure['todo_list_json'], 'r',
                encoding='utf-8') as f_json:
            try:
                py_content = json.load(f_json)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Error decoding JSON from {self.workdir_structure['todo_list_json']}: {e}"
                )

        self._todo_d['markdown'] = md_content
        self._todo_d['py'] = py_content

        return True

    def run(self, user_prompt: str, **kwargs):

        # Rewrite the user prompt
        from datetime import datetime
        args_template: str = '{"query": "xxx", "num_results": 20, "start_published_date": "2025-01-01", "end_published_date": "2025-05-30"}'
        prompt_rewrite: str = (f'生成search request，具体要求为： '
                               f'\n1. 必须符合以下arguments格式：{args_template}'
                               f'\n2. 其中，query参数的值直接使用用户原始输入，即：{user_prompt}'
                               f'\n3. 参数需要符合搜索引擎的要求，num_results需要根据实际问题的复杂程度来估算，最大25，最小1,对于复杂的问题，num_results的值需要尽量大；'
                               f'\n3. start_published_date和end_published_date需要根据实际问题的时间范围来估算，默认均为None。当前日期为：{datetime.now().strftime("%Y-%m-%d")}')

        messages_rewrite = [{'role': 'user', 'content': prompt_rewrite}]
        resp_d: Dict[str, Any] = self._chat(messages=messages_rewrite,
                                            temperature=0.0,
                                            stream=False)
        resp_content: str = resp_d.get('content', '')
        print(f'>>Rewritten Prompt: {resp_content}')

        # Parse the rewritten prompt
        search_request_d: Dict[str, Any] = ResearchWorkflow.parse_json_from_content(resp_content)
        assert search_request_d, 'Rewritten search request cannot be empty !'

        if isinstance(search_request_d, list):
            search_request_d = search_request_d[0]

        search_request: ExaSearchRequest = ExaSearchRequest(**search_request_d)
        search_res_file: str = self.search(search_requests=[search_request])

        search_results: List[Dict[str, Any]] = ExaSearchResult.load_from_disk(file_path=search_res_file)
        assert search_results, 'Search results cannot be empty, workflow stopped!'

        urls_or_files = [res_d['url'] for res_d in search_results[0]['results']]
        extractor = HierarchicalKeyInformationExtraction(urls_or_files=urls_or_files)
        key_info_list: List[KeyInformation] = extractor.extract()

        # Dump pictures/table to resources directory
        resource_map: Dict[
            str, str] = {}  # item_name -> item_relative_path, e.g. {'2506.02718v1.pdf@2728311679401389578@#/pictures/0': 'resources/d5a93ca4.png'}
        for item_name, doc_item in extractor.all_ref_items.items():
            if hasattr(doc_item, 'image') and doc_item.image:
                # Get the item extension from mimetype such as `image/png`
                item_ext: str = doc_item.image.mimetype.split('/')[-1]
                item_file_name: str = f'{text_hash(item_name)}.{item_ext}'
                item_path: str = os.path.join(self.workdir_structure['resources_dir'], f'{item_file_name}')
                doc_item.image.pil_image.save(item_path)

                resource_map[item_name] = os.path.join(ResearchWorkflow.RESOURCES, item_file_name)

        context: str = '\n'.join(
            [key_info.text for key_info in key_info_list if key_info.text])

        logger.info(f'\n\nContext:\n{context}\n\n')

        prompt_sum: str = (f'结合用户输入：{user_prompt}，请帮我总结以下内容，生成一份markdown格式的报告；'
                           f'其中图片被表示为<resource_info>xxx</resource_info>之间的placeholder，要求尽量保留重要的图片和表格，保持图片或表格以及附近对应上下文的位置关系；'
                           f'符合MECE原则（Mutually Exclusive and Collectively Exhaustive）；'
                           f'如果收集到的信息足够多，则尽量精简和结构化，保留其中最重要的信息，最终生成一份图文并茂的报告：\n\n')

        prompt_sum_lite: str = f'结合用户输入：{user_prompt}，生成一份markdown格式的报告，要求符合MECE原则（Mutually Exclusive and Collectively Exhaustive）'

        messages_sum = [
            {'role': 'system', 'content': self.default_system},
            {'role': 'user', 'content': f'{prompt_sum}{context}' if context.strip() else prompt_sum_lite}
        ]
        aggregated_chunks = self._chat(messages=messages_sum, temperature=0.3)
        resp_content: str = aggregated_chunks.get('content', '')
        logger.info(f'\n\nSummary Content:\n{resp_content}')

        # Replace resource name with actual relative path   ![图片1](images/image1.png)
        for item_name, item_relative_path in resource_map.items():
            resp_content = resp_content.replace(
                f'<resource_info>{item_name}</resource_info>',
                f'![{os.path.basename(item_relative_path)}]({item_relative_path})<br>',
                1
            )

        # Remove unused <resource_info> tags
        # TODO: 存在未经转换的<resource_info>，待处理
        resp_content = remove_resource_info(resp_content)

        # Dump report to markdown file
        with open(self.workdir_structure['report_md'], 'w', encoding='utf-8') as f_report:
            f_report.write(resp_content)
        logger.info(f'Report saved to {self.workdir_structure["report_md"]}')
