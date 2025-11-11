# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio

from ms_agent.llm.openai import OpenAIChat
from ms_agent.tools.search.search_base import SearchEngine
from ms_agent.tools.search_engine import get_web_search_tool
from ms_agent.workflow.deep_research.principle import MECEPrinciple
from ms_agent.workflow.deep_research.research_workflow import ResearchWorkflow
from ms_agent.workflow.deep_research.research_workflow_beta import \
    ResearchWorkflowBeta


def run_workflow(user_prompt: str,
                 task_dir: str,
                 chat_client: OpenAIChat,
                 search_engine: SearchEngine,
                 reuse: bool,
                 use_ray: bool = False):
    """
    Run the deep research workflow, which follows a lightweight and efficient pipeline:
    1. Receive a user prompt and generate search queries.
    2. Search the web, extract hierarchical key information, and preserve multimodal content.
    3. Generate a report summarizing the research results.

    Args:
        user_prompt: The user prompt.
        task_dir: The task directory where the research results will be saved.
        chat_client: The chat client.
        search_engine: The search engine.
        reuse: Whether to reuse the previous research results.
        use_ray: Whether to use Ray for document parsing/extraction.
    """

    research_workflow = ResearchWorkflow(
        client=chat_client,
        principle=MECEPrinciple(),
        search_engine=search_engine,
        workdir=task_dir,
        reuse=reuse,
        use_ray=use_ray,
    )

    research_workflow.run(user_prompt=user_prompt)


def run_deep_workflow(user_prompt: str,
                      task_dir: str,
                      chat_client: OpenAIChat,
                      search_engine: SearchEngine,
                      breadth: int = 4,
                      depth: int = 2,
                      is_report: bool = True,
                      show_progress: bool = True,
                      use_ray: bool = False):
    """
    Run the expandable deep research workflow (beta version).
    This version is more flexible and scalable than the original deep research workflow.
    It follows a recursive pipeline:
    1. Receive a user prompt and generate questions to clarify the research direction.
    2. Generate search queries and research goals based on the questions and previous research results.
    3. Search the web, extract the information, and preserve multimodal content.
    4. Generate follow-up questions and dense learnings based on the extracted information.
    5. Repeat the process until the research depth is reached or the follow-up questions are empty.
    6. Generate a multimodal report or a summary of the research results.

    Args:
        user_prompt: The user prompt.
        task_dir: The task directory where the research results will be saved.
        chat_client: The chat client.
        search_engine: The search engine.
        breadth: The number of search queries to generate per depth level.
        In order to avoid the explosion of the search space,
        we divide the breadth by 2 for each depth level.
        depth: The maximum research depth.
        is_report: Whether to generate a report.
        show_progress: Whether to show the progress.
        use_ray: Whether to use Ray for document parsing/extraction.
    """

    research_workflow = ResearchWorkflowBeta(
        client=chat_client,
        search_engine=search_engine,
        workdir=task_dir,
        use_ray=use_ray,
        enable_multimodal=True)

    asyncio.run(
        research_workflow.run(
            user_prompt=user_prompt,
            breadth=breadth,
            depth=depth,
            is_report=is_report,
            show_progress=show_progress))


if __name__ == '__main__':

    query: str = 'Survey of the AI Agent within the recent 3 month, including the latest research papers, open-source projects, and industry applications.'  # noqa
    task_workdir: str = '/path/to/your_workdir'  # Specify your task work directory here
    reuse: bool = False

    # Get chat client OpenAI compatible api
    # Free API Inference Calls - Every registered ModelScope user receives a set number of free API inference calls daily, refer to https://modelscope.cn/docs/model-service/API-Inference/intro for details.  # noqa
    """
    * `api_key` (str), your API key, replace `xxx-xxx` with your actual key. Alternatively, you can use ModelScope API key, refer to https://modelscope.cn/my/myaccesstoken  # noqa
    * `base_url`: (str), the base URL for API requests, `https://api-inference.modelscope.cn/v1/` for ModelScope API-Inference
    * `model`: (str), the model ID for inference, `Qwen/Qwen3-235B-A22B-Instruct-2507` can be recommended for document research tasks.
    """
    chat_client = OpenAIChat(
        api_key='xxx-xxx',
        base_url='https://api-inference.modelscope.cn/v1/',
        model='Qwen/Qwen3-235B-A22B-Instruct-2507',
        generation_config={'extra_body': {
            'enable_thinking': False
        }})

    # Get web-search engine client
    # For the ExaSearch, you can get your API key from https://exa.ai
    # Please specify your config file path, the default is `conf.yaml` in the current directory.
    search_engine = get_web_search_tool(config_file='conf.yaml')

    # Enable Ray with `use_ray=True` to speed up document parsing.
    # It uses multiple CPU cores for faster processing,
    # but also increases CPU usage and may cause temporary stutter on your machine.
    run_workflow(
        user_prompt=query,
        task_dir=task_workdir,
        reuse=reuse,
        chat_client=chat_client,
        search_engine=search_engine,
        use_ray=False,
    )
