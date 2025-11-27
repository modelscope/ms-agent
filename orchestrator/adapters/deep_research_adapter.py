import asyncio
import os
from typing import Any, Dict, List

from ms_agent.llm.openai import OpenAIChat
from ms_agent.tools.exa import ExaSearch
from ms_agent.tools.search.arxiv import ArxivSearch
from ms_agent.tools.search.serpapi import SerpApiSearch
from ms_agent.workflow.deep_research.research_workflow_beta import \
    ResearchWorkflowBeta
from orchestrator.adapters.base import BaseAdapter
from orchestrator.core.const import FILE_REPORT


class DeepResearchAdapter(BaseAdapter):
    """
    适配器：用于调用 projects.deep_research (Beta) 进行深度网络搜索研究。
    """

    def run(self, query: str) -> Dict[str, Any]:
        """
        执行深度研究任务。

        Args:
            query (str): 研究主题。

        Returns:
            Dict: {'report_path': Path(...)}
        """
        # 1. 初始化 LLM Client
        llm_config = {
            'api_key': self.config.openai_api_key
            or self.config.modelscope_api_key,
            'base_url': self.config.openai_base_url,
            'model': self.config.model_name,
        }

        if not llm_config['api_key']:
            raise ValueError(
                'API Key is missing. Please set OPENAI_API_KEY or MODELSCOPE_API_KEY.'
            )

        client = OpenAIChat(
            api_key=llm_config['api_key'],
            base_url=llm_config['base_url'],
            model=llm_config['model'],
            generation_config={'extra_body': {
                'enable_thinking': True
            }})

        # 2. 初始化搜索引擎
        search_engine = self._create_search_engine()

        # 3. 准备工作目录
        workdir = str(self.workspace.work_dir)

        # 4. 初始化 Workflow (Beta)
        # 使用 beta 版本因为其支持更深度的递归搜索
        workflow = ResearchWorkflowBeta(
            client=client,
            search_engine=search_engine,
            workdir=workdir,
            use_ray=False,  # 默认关闭 Ray 以避免依赖复杂性
            enable_multimodal=True)

        # 5. 执行 Run (异步)
        # 需要在同步环境中运行异步代码
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # 配置参数 (可以后续移入 Config)
        run_params = {
            'user_prompt': query,
            'breadth': 4,  # 广度
            'depth': 2,  # 深度
            'is_report': True,
            'show_progress': True
        }

        loop.run_until_complete(workflow.run(**run_params))

        # 6. 验证输出
        # ResearchWorkflowBeta 生成的报告默认命名可能包含前缀或在子目录中
        # 但通常最终汇总报告是 report.md
        report_path = self.workspace.get_path(FILE_REPORT)
        if not report_path.exists():
            # Beta 版可能会生成 intermediate 文件，我们需要确认最终文件名为 report.md
            # 如果不是，这里可能需要重命名或查找
            raise RuntimeError(
                f'DeepResearch failed to generate {FILE_REPORT}')

        return {'report_path': report_path}

    def _create_search_engine(self):
        """根据环境变量创建合适的搜索引擎实例"""
        exa_key = os.getenv('EXA_API_KEY')
        serp_key = os.getenv('SERPAPI_API_KEY')

        if exa_key:
            return ExaSearch(api_key=exa_key)
        elif serp_key:
            return SerpApiSearch(api_key=serp_key)
        else:
            # 默认使用 Arxiv，无需 Key，适合科研场景
            return ArxivSearch()
