from dataclasses import dataclass
from typing import Dict, Optional

# The default output dir
DEFAULT_OUTPUT_DIR = './output'

# The key of user defined tools in the agent.yaml
TOOL_PLUGIN_NAME = 'plugins'

# Default agent config file
AGENT_CONFIG_FILE = 'agent.yaml'

# Default agent code file
DEFAULT_AGENT_FILE = 'agent.py'

# DEFAULT_WORKFLOW_YAML
WORKFLOW_CONFIG_FILE = 'workflow.yaml'

# A base config of ms-agent
DEFAULT_YAML = 'ms-agent/simple_agent'

# The default tag of agent
DEFAULT_TAG = 'Agent-default'

# The default id of user
DEFAULT_USER = 'User-default'

DEFAULT_RETRY_COUNT = 3


@dataclass
class ServiceConfig:
    base_url: Optional[str] = None


@dataclass
class ModelscopeConfig(ServiceConfig):

    def __init__(self):
        super().__init__(base_url='https://api-inference.modelscope.cn/v1')


@dataclass
class DashscopeConfig(ServiceConfig):

    def __init__(self):
        super().__init__(
            base_url='https://dashscope.aliyuncs.com/compatible-mode/v1')


@dataclass
class DeepseekConfig(ServiceConfig):

    def __init__(self):
        super().__init__(base_url='https://api.deepseek.com/v1')


@dataclass
class AnthropicConfig(ServiceConfig):

    def __init__(self):
        # without /v1, using Anthropic API
        super().__init__(base_url='https://api.anthropic.com')


class OpenaiConfig(ServiceConfig):

    def __init__(self):
        super().__init__(base_url='https://api.openai.com/v1')


SERVICE_MAPPING: Dict[str, ServiceConfig] = {
    'modelscope': ModelscopeConfig(),
    'dashscope': DashscopeConfig(),
    'deepseek': DeepseekConfig(),
    'Anthropic': AnthropicConfig(),
    'openai': OpenaiConfig(),
}


def get_service_config(service_name: str) -> ServiceConfig:
    if service_name.lower() in SERVICE_MAPPING:
        return SERVICE_MAPPING[service_name.lower()]
    else:
        return ServiceConfig()
