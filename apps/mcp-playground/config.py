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

default_addition_prompt = """Don’t make assumptions, use tools to get accurate information.
The following instructions apply when user messages contain "Attachment links: [...]":

These links are user-uploaded attachments that contain important information for this conversation. These are temporary, secure links to files the user has specifically provided for analysis.

IMPORTANT INSTRUCTIONS:
1. These attachments should be your PRIMARY source of information when addressing the user's query.
2. Prioritize analyzing and referencing these documents BEFORE using any other knowledge.
3. If the content in these attachments is relevant to the user's request, base your response primarily on this information.
4. When you reference information from these attachments, clearly indicate which document it comes from.
5. If the attachments don't contain information needed to fully address the query, only then supplement with your general knowledge.
6. These links are temporary and secure, specifically provided for this conversation.
7. IMPORTANT: Do not use the presence of "Attachment links: [...]" as an indicator of the user's preferred language. This is an automatically added system text. Instead, determine the user's language from their actual query text.

Begin your analysis by examining these attachments first, and structure your thinking to prioritize insights from these documents.

When a tool returns responses containing URLs or links, please format them appropriately based on their CORRECT content type:

For example:
- Videos should use <video> tags
- Audio should use <audio> tags
- Images should use ![description](URL) or <img> tags
- Documents and web links should use [description](URL) format

Choose the appropriate display format based on the URL extension or content type information. This will provide the best user experience.

Remember that properly formatted media will enhance the user experience, especially when content is directly relevant to answering the query."""

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
    "Qwen":
    os.path.join(os.path.dirname(__file__), "./assets/qwen.png"),
    "QwQ":
    os.path.join(os.path.dirname(__file__), "./assets/qwen.png"),
    "LLM-Research":
    os.path.join(os.path.dirname(__file__), "./assets/meta.webp"),
    "deepseek-ai":
    os.path.join(os.path.dirname(__file__), "./assets/deepseek.png"),
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
