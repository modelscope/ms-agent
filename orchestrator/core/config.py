import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

# 如果存在 .env 文件，则加载环境变量
load_dotenv()


@dataclass
class OrchestratorConfig:
    """
    编排器配置类。
    从环境变量加载配置值，或使用默认值。
    """
    # LLM 配置
    openai_api_key: Optional[str] = os.getenv('OPENAI_API_KEY')
    modelscope_api_key: Optional[str] = os.getenv('MODELSCOPE_API_KEY')
    openai_base_url: str = os.getenv(
        'OPENAI_BASE_URL', 'https://api-inference.modelscope.cn/v1/')
    model_name: str = os.getenv('MODEL_NAME',
                                'Qwen/Qwen2.5-Coder-32B-Instruct')

    # 编排器逻辑配置
    max_retries: int = int(os.getenv('MAX_RETRIES', '3'))
    workspace_root: str = os.getenv('WORKSPACE_ROOT', 'workspace')

    # Research 模块配置
    search_engine_api_key: Optional[str] = os.getenv(
        'EXA_API_KEY') or os.getenv('SERPAPI_API_KEY')

    def validate(self):
        """验证关键配置项。"""
        if not self.openai_api_key and not self.modelscope_api_key:
            # 某些用户可能依赖本地模型或隐式认证，但通常我们需要一个 Key。
            # 这里可以添加警告日志。
            pass

    @classmethod
    def load(cls) -> 'OrchestratorConfig':
        """加载配置的工厂方法。"""
        return cls()
