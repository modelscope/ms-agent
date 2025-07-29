from datetime import datetime
from typing import Any, Dict

from ms_agent.tools.exa import ExaSearchRequest
from ms_agent.tools.search.arxiv.schema import ArxivSearchRequest
from ms_agent.tools.search.search_base import SearchEngineType, SearchRequest
from ms_agent.tools.search.serpapi.schema import SerpApiSearchRequest


class SearchRequestGenerator:
    """Base class for search request generators"""

    def __init__(self, user_prompt: str):
        self.user_prompt = user_prompt

    def get_args_template(self) -> str:
        raise NotImplementedError

    def get_rewrite_prompt(self) -> str:
        raise NotImplementedError

    def create_request(self, search_request_d: Dict[str,
                                                    Any]) -> SearchRequest:
        raise NotImplementedError


class ExaSearchRequestGenerator(SearchRequestGenerator):

    def get_args_template(self) -> str:
        return (
            '{"query": "xxx", "num_results": 20, '
            '"start_published_date": "2025-01-01", "end_published_date": "2025-05-30"}'
        )

    def get_rewrite_prompt(self) -> str:
        return (
            f'生成search request，具体要求为： '
            f'\n1. 必须符合以下arguments格式：{self.get_args_template()}'
            f'\n2. 其中，query参数的值直接使用用户原始输入，即：{self.user_prompt}'
            f'\n3. 参数需要符合搜索引擎的要求，num_results需要根据实际问题的复杂程度来估算，最大25，最小1,对于复杂的问题，num_results的值需要尽量大；'
            f'\n3. start_published_date和end_published_date需要根据实际问题的时间范围来估算，默认均为None。'
            f'当前日期为：{datetime.now().strftime("%Y-%m-%d")}')

    def create_request(self, search_request_d: Dict[str,
                                                    Any]) -> ExaSearchRequest:
        return ExaSearchRequest(**search_request_d)


class SerpApiSearchRequestGenerator(SearchRequestGenerator):

    def get_args_template(self) -> str:
        return '{"query": "xxx", "num_results": 20, "location": null}'

    def get_rewrite_prompt(self) -> str:
        return (f'生成search request，具体要求为： '
                f'\n1. 必须符合以下arguments格式：{self.get_args_template()}'
                f'\n2. 其中，query参数的值直接使用用户原始输入，即：{self.user_prompt}'
                f'\n3. 参数需要符合搜索引擎的要求，num_results需要根据实际问题的复杂程度来估算，最大25，最小1；'
                f'\n4. location参数用于指定搜索位置，如"Austin,Texas"，如不需要特定位置可设为null')

    def create_request(
            self, search_request_d: Dict[str, Any]) -> SerpApiSearchRequest:
        return SerpApiSearchRequest(**search_request_d)


class ArxivSearchRequestGenerator(SearchRequestGenerator):

    def get_args_template(self) -> str:
        return '{"query": "xxx", "num_results": 20}'

    def get_rewrite_prompt(self) -> str:
        return (
            f'你是一位顶尖的学术研究助手，精通arXiv搜索引擎的高级语法。'
            f'\n你的任务是将用户的中文日常语言查询，转换成一个为arXiv API准备的、结构化、精确且高效的英文搜索请求。请严格遵循以下步骤和原则：'
            f'\n第一步：**核心概念提炼与翻译**'
            f'\n1. **识别核心概念**：分析用户的原始输入: "{self.user_prompt}"，找出其中关键的学术概念、技术术语或研究方向。'
            f'\n2. **转换为英文术语**：将这些中文核心概念准确地翻译成国际学术界公认的、标准的英文术语。例如，"大语言模型"应转换为"large language model"。'
            f'\n第二步：**构建高效的arXiv查询语句**'
            f'\n运用arXiv的高级搜索语法来组合英文术语，以实现最大程度的精确召回，同时避免返回不相关的结果。关键语法包括：'
            f'\n1. **字段前缀 (Field Prefixes)**：在每个关键词前加 `all:`，或按需使用 `ti:` (标题), `au:` (作者), `abs:` (摘要) 来限定搜索范围'
            f'\n2. **布尔运算符 (Boolean Operators)**：使用 `AND`, `OR`, `ANDNOT` 来构建逻辑关系。`AND` 用于缩小范围，`OR` 用于扩大范围。'
            f'\n3. **精确短语 (Exact Phrases)**：将由多个单词组成的术语放入双引号 `""` 中。'
            f'\n4. **简洁性**：查询语句应简洁有力，去除口语化的、不必要的词汇，并且避免使用过于复杂的语法组合导致无法召回。'
            f'\n第三步：**生成最终请求**'
            f'\n现在，基于以上所有原则和范例，为用户的原始输入"{self.user_prompt}"生成最终的搜索请求。'
            f'\n1. 将你构建的、最优的英文查询语句填入query参数。'
            f'\n2. num_results参数的值必须在1到25之间，请选择一个适合问题复杂程度的值，比如10。'
            f'\n3. 必须严格按照以下JSON格式模板返回结果: {self.get_args_template()}')

    def create_request(self,
                       search_request_d: Dict[str, Any]) -> ArxivSearchRequest:
        return ArxivSearchRequest(**search_request_d)


def get_search_request_generator(engine_type: SearchEngineType,
                                 user_prompt: str) -> SearchRequestGenerator:
    """
    Get the corresponding search request generator

    Args:
        engine_type (SearchEngineType): The type of search engine
        user_prompt (str): User prompt text

    Returns:
        SearchRequestGenerator: Instance of a search request generator

    Raises:
        ValueError: When an unsupported search engine type is provided
    """
    if engine_type == SearchEngineType.EXA:
        return ExaSearchRequestGenerator(user_prompt)
    elif engine_type == SearchEngineType.SERPAPI:
        return SerpApiSearchRequestGenerator(user_prompt)
    elif engine_type == SearchEngineType.ARXIV:
        return ArxivSearchRequestGenerator(user_prompt)
    else:
        raise ValueError(f'Unsupported search engine type: {engine_type}')
