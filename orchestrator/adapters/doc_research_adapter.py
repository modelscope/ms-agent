import os
from pathlib import Path
from typing import Any, Dict, List

from ms_agent.llm.openai import OpenAIChat
from ms_agent.workflow.deep_research.research_workflow import ResearchWorkflow
from orchestrator.adapters.base import BaseAdapter
from orchestrator.core.const import FILE_REPORT


class DocResearchAdapter(BaseAdapter):
    """
    适配器：用于调用 ms_agent.workflow.deep_research.ResearchWorkflow 进行文档分析。
    """

    def run(self, query: str, files: List[str],
            urls: List[str]) -> Dict[str, Any]:
        """
        执行文档研究任务。

        Args:
            query (str): 用户的研究问题或指令。
            files (List[str]): 本地文件路径列表 (绝对路径)。
            urls (List[str]): URL 列表。

        Returns:
            Dict: {'report_path': Path(...)}
        """
        # 1. 准备输入列表 (files + urls)
        urls_or_files = files + urls
        if not urls_or_files:
            raise ValueError(
                'DocResearchAdapter requires at least one file or URL.')

        # 2. 初始化 LLM Client
        # 使用 config 中的配置
        llm_config = {
            'api_key': self.config.openai_api_key
            or self.config.modelscope_api_key,
            'base_url': self.config.openai_base_url,
            'model': self.config.model_name,
        }

        # 确保 API Key 存在
        if not llm_config['api_key']:
            raise ValueError(
                'API Key is missing. Please set OPENAI_API_KEY or MODELSCOPE_API_KEY.'
            )

        client = OpenAIChat(
            api_key=llm_config['api_key'],
            base_url=llm_config['base_url'],
            model=llm_config['model'],
            # 启用思维链 (如果支持)
            generation_config={'extra_body': {
                'enable_thinking': True
            }})

        # 3. 准备工作目录
        # ResearchWorkflow 会在 workdir 下生成 report.md
        # 我们直接使用当前 workspace 的路径
        workdir = str(self.workspace.work_dir)

        # 4. 初始化并运行 Workflow
        # 注意：ResearchWorkflow 内部会自动处理 OCR 模型下载 (如果 ms_agent 版本较新且包含相关逻辑)
        # 如果运行报错缺少模型，我们需要手动补充下载代码
        workflow = ResearchWorkflow(
            client=client,
            workdir=workdir,
            verbose=True,
            # 可以传入 use_ray=True 如果环境支持 Ray
            use_ray=False)

        # 5. 执行 Run
        # user_prompt 对应 query
        # urls_or_files 对应文档列表
        # report_prefix 默认为空，所以输出文件是 report.md
        workflow.run(user_prompt=query, urls_or_files=urls_or_files)

        # 6. 验证输出
        report_path = self.workspace.get_path(FILE_REPORT)
        if not report_path.exists():
            raise RuntimeError(
                f'ResearchWorkflow failed to generate {FILE_REPORT}')

        return {'report_path': report_path}
