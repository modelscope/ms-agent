import os

import json
from modelscope_studio.components.pro.chatbot import (ChatbotActionConfig,
                                                      ChatbotBotConfig,
                                                      ChatbotUserConfig,
                                                      ChatbotWelcomeConfig)

max_mcp_server_count = 10

default_mcp_config = json.dumps({'mcpServers': {}},
                                indent=4,
                                ensure_ascii=False)

default_history_config = json.dumps(
    {
        'history': [{
            'role': 'user',
            'content': '介绍一下你自己',
            'sent_from': '',
            'send_to': 'all'
        }, {
            'role': 'assistant',
            'content': '我是一个能够调用工具的智能ai',
            'sent_from': '',
            'send_to': 'all'
        }]
    },
    indent=4,
    ensure_ascii=False)

default_sys_prompt = 'You are a helpful assistant.'

# for internal
default_mcp_prompts = {
    # "arxiv": ["查找最新的5篇关于量子计算的论文并简要总结", "根据当前时间，找到近期关于大模型的论文，得到研究趋势"],
    '高德地图': ['北京今天天气怎么样', '基于今天的天气，帮我规划一条从北京到杭州的路线'],
    'time': ['帮我查一下北京时间', '现在是北京时间 2025-04-01 12:00:00，对应的美西时间是多少？'],
    'fetch':
    ['从中国新闻网获取最新的新闻', '获取 https://www.example.com 的内容，并提取为Markdown格式'],
}

# for internal
default_mcp_servers = [{
    'name': mcp_name,
    'enabled': True,
    'internal': True
} for mcp_name in default_mcp_prompts.keys()]

bot_avatars = {
    'Qwen/Qwen2.5-72B-Instruct':
    os.path.join(os.path.dirname(__file__), './assets/qwen.png'),
    'Qwen/Qwen3-235B-A22B':
    os.path.join(os.path.dirname(__file__), './assets/qwen.png'),
    'Qwen/QwQ-32B':
    os.path.join(os.path.dirname(__file__), './assets/qwen.png'),
    'LLM-Research/Llama-4-Maverick-17B-128E-Instruct':
    os.path.join(os.path.dirname(__file__), './assets/meta.webp'),
    'deepseek-ai/DeepSeek-V3-0324':
    os.path.join(os.path.dirname(__file__), './assets/deepseek.png'),
}

mcp_prompt_model = 'Qwen/Qwen3-235B-A22B'

model_options = [
    {
        'label': 'Qwen3-235B-A22B',
        'value': 'Qwen/Qwen3-235B-A22B',
        'model_params': {
            'extra_body': {
                'enable_thinking': False,
            }
        },
        'tag': {
            'label': '正常模式',
            'color': '#54C1FA'
        }
    },
    {
        'label': 'Qwen3-235B-A22B',
        'value': 'Qwen/Qwen3-235B-A22B:thinking',
        'thought': True,
        'model_params': {
            'extra_body': {
                'enable_thinking': True,
            }
        },
        'tag': {
            'label': '深度思考',
            'color': '#36CFD1'
        }
    },
    {
        'label': 'Qwen3-32B',
        'value': 'Qwen/Qwen3-32B',
        'model_params': {
            'extra_body': {
                'enable_thinking': False,
            }
        },
        'tag': {
            'label': '正常模式',
            'color': '#54C1FA'
        }
    },
    {
        'label': 'Qwen3-32B',
        'value': 'Qwen/Qwen3-32B:thinking',
        'thought': True,
        'model_params': {
            'extra_body': {
                'enable_thinking': True,
            }
        },
        'tag': {
            'label': '深度思考',
            'color': '#36CFD1'
        }
    },
    {
        'label': 'Qwen2.5-72B-Instruct',
        'value': 'Qwen/Qwen2.5-72B-Instruct'
    },
    {
        'label': 'DeepSeek-V3-0324',
        'value': 'deepseek-ai/DeepSeek-V3-0324',
    },
    {
        'label': 'Llama-4-Maverick-17B-128E-Instruct',
        'value': 'LLM-Research/Llama-4-Maverick-17B-128E-Instruct',
    },
    {
        'label': 'QwQ-32B',
        'value': 'Qwen/QwQ-32B',
        'thought': True,
        'tag': {
            'label': '推理模型',
            'color': '#624AFF'
        }
    },
]

model_options_map = {model['value']: model for model in model_options}

primary_color = '#816DF8'

default_locale = 'zh_CN'

default_theme = {'token': {'colorPrimary': primary_color}}


def user_config(disabled_actions=None):
    return ChatbotUserConfig(
        actions=[
            'copy', 'edit',
            ChatbotActionConfig(
                action='delete',
                popconfirm=dict(
                    title='删除消息',
                    description='确认删除该消息?',
                    okButtonProps=dict(danger=True)))
        ],
        disabled_actions=disabled_actions)


def bot_config(disabled_actions=None):
    return ChatbotBotConfig(
        actions=[
            'copy', 'edit',
            ChatbotActionConfig(
                action='retry',
                popconfirm=dict(
                    title='重新生成消息',
                    description='重新生成消息会删除所有后续消息。',
                    okButtonProps=dict(danger=True))),
            ChatbotActionConfig(
                action='delete',
                popconfirm=dict(
                    title='删除消息',
                    description='确认删除该消息?',
                    okButtonProps=dict(danger=True)))
        ],
        disabled_actions=disabled_actions)


def welcome_config(prompts: dict, loading=False):
    return ChatbotWelcomeConfig(
        icon='./assets/mcp.png',
        title='MCP 实验场',
        styles=dict(icon=dict(borderRadius='50%', overflow='hidden')),
        description='调用 MCP 工具以拓展模型能力',
        prompts=dict(
            title='用例生成中...' if loading else None,
            wrap=True,
            styles=dict(item=dict(flex='1 0 200px')),
            items=[{
                'label': mcp_name,
                'children': [{
                    'description': prompt
                } for prompt in prompts]
            } for mcp_name, prompts in prompts.items()]))
