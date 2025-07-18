# Copyright (c) Alibaba, Inc. and its affiliates.

from ms_agent.llm.openai import OpenAIChat
from ms_agent.tools.exa import ExaSearch
from ms_agent.workflow.principle import MECEPrinciple
from ms_agent.workflow.research_workflow import ResearchWorkflow


def run_workflow(user_prompt: str, task_dir: str, reuse: bool,
                 chat_client: OpenAIChat, search_engine: ExaSearch):

    research_workflow = ResearchWorkflow(
        client=chat_client,
        principle=MECEPrinciple(),
        search_engine=search_engine,
        workdir=task_dir,
        reuse=reuse,
    )

    research_workflow.run(user_prompt=user_prompt)


if __name__ == '__main__':

    query: str = 'Survey of the Deep Research on the AI Agent within the recent 3 month, including the latest research papers, open-source projects, and industry applications.'  # noqa
    task_workdir: str = '/path/to/your_task_dir'
    reuse: bool = False

    # Get chat client OpenAI compatible api
    chat_client = OpenAIChat(
        api_key='sk-xxx',
        base_url='https://your_base_url',
        model='gemini-2.5-pro',
    )

    # Get web-search engine client
    # For the ExaSearch, you can get your API key from https://exa.ai/
    exa_search = ExaSearch(api_key='xxx-xxx')

    run_workflow(
        user_prompt=query,
        task_dir=task_workdir,
        reuse=reuse,
        chat_client=chat_client,
        search_engine=exa_search,
    )
