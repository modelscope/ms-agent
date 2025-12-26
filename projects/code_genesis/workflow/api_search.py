import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict

import json
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils.constants import DEFAULT_INDEX_DIR


class ApiSearch(ToolBase):

    def __init__(self, config):
        super().__init__(config)
        index_dir = getattr(config, 'index_cache_dir', DEFAULT_INDEX_DIR)
        self.index_dir = os.path.join(self.output_dir, index_dir)

    async def connect(self) -> None:
        pass

    async def _get_tools_inner(self) -> Dict[str, Any]:
        tools = {
            'api_search': [
                Tool(
                    tool_name='url_search',
                    server_name='api_search',
                    description='Search api definitions with any keywords. '
                    'These apis are summarized from the code you have written. '
                    'You need to use this tool when:\n'
                    '1. You are writing a frontend api interface, which needs the exact http definitions\n'
                    '2. You want to check any api problem\n'
                    '3. You want to know if your api definition will duplicate with others\n'
                    'Instructions & Examples:\n'
                    '1. Search user api with `user` (substring match)\n'
                    '2. Search create music api with `music/create`\n'
                    '3. Split keywords with `,` for multiple substring matches\n'
                    '4. Use regex pattern like `r"/api/.*user"` for regex matching\n'
                    '5. If you want all api definitions, pass empty string into `keywords` argument\n'
                    '6. FOLLOW the definitions of this tool results, you should not use any undefined api. '
                    'Instead, you need to write missing api to a target file.\n',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'keywords': {
                                'type':
                                'string',
                                'description':
                                'The keywords/regex in the url to search api of.',
                            }
                        },
                        'required': [],
                        'additionalProperties': False
                    }),
            ]
        }
        return tools

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        return await self.url_search(**tool_args)

    async def url_search(self, keywords: str = None):
        """Search API definitions using keywords with support for regex and substring matching.

        Args:
            keywords(str): Search pattern. Supports:
                - Comma-separated substrings: 'user,admin' (will match URLs containing 'user' OR 'admin')
                - Regex pattern: Any valid regex pattern for URL matching
                - Empty/None: Returns all APIs

        Returns:
            str: Formatted search results
        """
        # Parse keywords and determine matching mode
        keyword_list = None
        use_regex = False
        regex_pattern = None

        if keywords:
            # Try to compile as regex pattern
            try:
                regex_pattern = re.compile(keywords)
                use_regex = True
            except re.error:
                # Not a valid regex, treat as comma-separated keywords
                keyword_list = [
                    kw.strip() for kw in keywords.split(',') if kw.strip()
                ]
                use_regex = False

        def search_in_file(file_path):
            matches = []
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = json.load(f)
                    if 'protocols' not in content:
                        return []
                    for protocol in content['protocols']:
                        url = protocol['url']

                        if not keywords:
                            # No filter, match all
                            is_match = True
                        elif use_regex:
                            # Regex matching
                            is_match = regex_pattern.search(url) is not None
                        else:
                            # Substring matching (any keyword matches)
                            is_match = any(keyword in url
                                           for keyword in keyword_list)

                        if is_match:
                            matches.append(
                                json.dumps(protocol, ensure_ascii=False))
            except Exception:  # noqa
                return []
            if matches:
                match_mode = '(regex)' if use_regex else '(substring)'
                matches.insert(
                    0,
                    f'API{" with keywords: " + str(keywords) + " " + match_mode if keywords else ""} defined '
                    f'in {file_path}:')
                matches.append('\n')
            return matches

        files_to_search = []
        for path, _, files in os.walk(self.index_dir):
            for file in files:
                files_to_search.append(os.path.join(path, file))

        # Use thread pool to search files in parallel
        all_matches = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_file = {
                executor.submit(search_in_file, f): f
                for f in files_to_search
            }
            for future in as_completed(future_to_file):
                matches = future.result()
                all_matches.extend(matches)
        return '\n'.join(all_matches)
