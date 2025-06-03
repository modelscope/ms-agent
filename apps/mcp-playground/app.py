# flake8: noqa: E501
import os

import gradio as gr
import json
import modelscope_studio.components.antd as antd
import modelscope_studio.components.antdx as antdx
import modelscope_studio.components.base as ms
import modelscope_studio.components.pro as pro
from app_mcp_client import get_mcp_prompts
from config import (bot_avatars, bot_config, default_locale,
                    default_mcp_config, default_mcp_prompts,
                    default_mcp_servers, default_theme, mcp_prompt_model,
                    model_options, model_options_map, primary_color,
                    user_config, welcome_config)
from env import api_key, internal_mcp_config
from exceptiongroup import ExceptionGroup
from modelscope_agent.agents.agent_with_mcp import AgentWithMCP
from modelscope_agent.tools.mcp.utils import merge_mcp_config, parse_mcp_config
from modelscope_studio.components.pro.multimodal_input import \
    MultimodalInputUploadConfig
from openai import AsyncOpenAI
from tools.oss import file_path_to_oss_url
from ui_components.config_form import ConfigForm
from ui_components.mcp_servers_button import McpServersButton


def run_install(command: str):
    import subprocess
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, shell=True, check=True)
        print('STDOUT:', result.stdout)
        print('STDERR:', result.stderr)
        print(f"'{command}' executed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error executing '{command}':")
        print('STDOUT:', e.stdout)
        print('STDERR:', e.stderr)
        print('Return code:', e.returncode)
    except Exception as e:
        print(f'An unexpected error occurred: {e} for command: {command}')


if os.getenv('LOCAL_RUN', 'true').lower() not in ['true', '1']:
    print(f'>>Installing npm...')
    run_install('sudo apt update')
    run_install('sudo apt install -y npm')


def format_messages(messages, oss_cache):
    formatted_messages = []
    for message in messages:
        if message['role'] == 'user':
            contents = ''
            for content in message['content']:
                if content['type'] == 'text':
                    contents += content['content']
                elif content['type'] == 'file':
                    files = []
                    for file_path in content['content']:
                        file_url = oss_cache.get(
                            file_path, file_path_to_oss_url(file_path))
                        oss_cache[file_path] = file_url
                        files.append(file_url)
                    contents += f"\n\nAttachment links: [{','.join(files)}]\n\n"

            formatted_messages.append({'role': 'user', 'content': contents})

        elif message['role'] == 'assistant':
            formatted_messages.append({
                'role':
                'assistant',
                'content':
                '\n'.join([
                    content['content'] for content in message['content']
                    if content['type'] == 'text'
                ])
            })

    return formatted_messages


def format_chatbot_header(model, model_config):
    tag_label = model_config.get('tag', {}).get('label')
    model_name = model.split('/')[1]
    if tag_label:
        return f'{model_name} `{tag_label}`'
    else:
        return model_name


def submit(input_value, config_form_value, mcp_config_value,
           mcp_servers_btn_value, chatbot_value, oss_state_value):
    model_value = config_form_value.get('model', '')
    model = model_value.split(':')[0]
    model_config = next(
        (x for x in model_options if x['value'] == model_value))
    model_params = model_config.get('model_params', {})
    sys_prompt = config_form_value.get('sys_prompt', '')
    history_config = config_form_value.get('history_config', [])

    enabled_mcp_servers = [
        item['name'] for item in mcp_servers_btn_value['data_source']
        if item.get('enabled') and not item.get('disabled')
    ]
    if input_value:
        chatbot_value.append({
            'role':
            'user',
            'content': [{
                'type': 'text',
                'content': input_value['text']
            }] + ([{
                'type': 'file',
                'content': [file for file in input_value['files']]
            }] if len(input_value['files']) > 0 else []),
            'class_names':
            dict(content='user-message-content')
        })

    chatbot_value.append({
        'role': 'assistant',
        'loading': True,
        'content': [],
        'header': format_chatbot_header(model, model_config),
        'avatar': bot_avatars.get(model.split('/')[0], None),
        'status': 'pending'
    })
    yield gr.update(
        loading=True, value=None), gr.update(disabled=True), gr.update(
            value=chatbot_value,
            bot_config=bot_config(
                disabled_actions=['edit', 'retry', 'delete']),
            user_config=user_config(disabled_actions=['edit', 'delete']))
    try:
        prev_chunk_type = None
        tool_name = ''
        tool_args = ''
        tool_content = ''

        in_api_config = {
            'model': model,
            'model_server': 'https://api-inference.modelscope.cn/v1/',
            'api_key': api_key,
        }
        mcp_config = merge_mcp_config(
            json.loads(mcp_config_value), internal_mcp_config)
        mcp_config = parse_mcp_config(mcp_config, enabled_mcp_servers)

        agent_executor = AgentWithMCP(
            llm=in_api_config,
            mcp_config=mcp_config,
            instruction=sys_prompt,
        )

        agent_messages = format_messages(chatbot_value[:-1],
                                         oss_state_value['oss_cache'])
        # response = agent_executor.run(agent_messages[-1]["content"], history=history_config["history"])
        response = agent_executor.run(agent_messages, history=history_config)
        text = ''
        tool_name = ''
        tool_args = ''
        tool_content = ''
        use_tool = False
        for chunk in response:
            msg = chunk[-1]
            # text += chunk
            chatbot_value[-1]['loading'] = False
            current_content = chatbot_value[-1]['content']
            # 这里用来判断是否划分新的框类
            # if prev_chunk_type is None:
            #     current_content.append({})
            #     prev_chunk_type = "text"
            # for msg in chunk:
            if msg['role'] == 'assistant':
                if msg.get('reasoning_content'):
                    msg_type = 'think'
                    if prev_chunk_type != msg_type:
                        current_content.append({})
                    assert isinstance(msg['reasoning_content'],
                                      str), 'Now only supports text messages'
                    if not isinstance(current_content[-1].get('content'), str):
                        current_content[-1]['content'] = ''
                    current_content[-1]['type'] = 'text'
                    current_content[-1]['content'] = msg['reasoning_content']
                    prev_chunk_type = msg_type
                if msg.get('content'):
                    msg_type = 'text'
                    if prev_chunk_type != msg_type:
                        current_content.append({})
                    assert isinstance(msg['content'],
                                      str), 'Now only supports text messages'
                    if not isinstance(current_content[-1].get('content'), str):
                        current_content[-1]['content'] = ''
                    current_content[-1]['type'] = 'text'
                    current_content[-1]['content'] = msg['content']
                    prev_chunk_type = msg_type
                if msg.get('function_call'):
                    msg_type = 'tool_call'
                    if prev_chunk_type != msg_type:
                        current_content.append({})

                    current_content[-1]['type'] = 'tool'
                    current_content[-1]['editable'] = False
                    current_content[-1]['copyable'] = False
                    if not isinstance(current_content[-1].get('options'),
                                      dict):
                        current_content[-1]['options'] = {
                            'title': '',
                            'status': 'pending'
                        }
                    if use_tool:
                        last_tool = tool_name.split(' ')[-1]
                        # deepseek api 存在多返回'}\n</tool'后又在下一chunk删除的情况
                        if (msg['function_call']['name']
                                and last_tool != msg['function_call']['name']
                            ) or (tool_args
                                  not in msg['function_call']['arguments']
                                  and tool_args.strip('}\n</tool') !=
                                  msg['function_call']['arguments'].strip(
                                      '}\n</tool').strip('}')):
                            tool_name = tool_name + ' ' + msg['function_call'][
                                'name']
                            tool_content = tool_content + f'**📝 参数**\n```json\n{tool_args}\n```\n\n'
                            tool_args = ''
                            current_content[-1]['options'][
                                'title'] = f'**🔧 调用 MCP 工具** `{tool_name}`'
                    elif msg['function_call']['name']:
                        tool_name = msg['function_call']['name']
                        current_content[-1]['options'][
                            'title'] = f'**🔧 调用 MCP 工具** `{tool_name}`'
                    if msg['function_call']['arguments']:
                        tool_args = msg['function_call']['arguments']
                        current_content[-1][
                            'content'] = tool_content + f'**📝 参数**\n```json\n{tool_args}\n```\n\n'
                    if msg['function_call']['name']:
                        use_tool = True
                    prev_chunk_type = msg_type
            if msg['role'] == 'function':
                use_tool = False
                chunk_content = msg['content']
                current_content[-1]['content'] = current_content[-1][
                    'content'] + f'\n\n**🎯 结果**\n```\n{chunk_content}\n```'
                prev_chunk_type = 'function'
                tool_name = ''
                tool_args = ''
                tool_content = ''
                current_content[-1]['options']['status'] = 'done'
                # faca_dic["content"] = faca_dic["content"] + f'\n\n**🎯 结果**\n```\n{chunk_content}\n```'
            yield gr.skip(), gr.skip(), gr.update(value=chatbot_value)
        print('ok')
        # yield gr.skip(), gr.skip(), gr.update(value=chatbot_value)
    except ExceptionGroup as eg:
        e = eg.exceptions[0]
        chatbot_value[-1]['loading'] = False
        chatbot_value[-1]['content'] += [{
            'type':
            'text',
            'content':
            f'<span style="color: var(--color-red-500)">{str(e)}</span>'
        }]
        print('Error: ', e)
        raise gr.Error(str(e))
    except Exception as e:
        chatbot_value[-1]['loading'] = False
        chatbot_value[-1]['content'] += [{
            'type':
            'text',
            'content':
            f'<span style="color: var(--color-red-500)">{str(e)}</span>'
        }]
        print('Error: ', e)
        raise gr.Error(str(e))
    finally:
        chatbot_value[-1]['status'] = 'done'
        yield gr.update(loading=False), gr.update(disabled=False), gr.update(
            value=chatbot_value,
            bot_config=bot_config(),
            user_config=user_config())


def cancel(chatbot_value):
    chatbot_value[-1]['loading'] = False
    chatbot_value[-1]['status'] = 'done'
    chatbot_value[-1]['footer'] = '对话已暂停'
    yield gr.update(loading=False), gr.update(disabled=False), gr.update(
        value=chatbot_value,
        bot_config=bot_config(),
        user_config=user_config())


async def retry(config_form_value, mcp_config_value, mcp_servers_btn_value,
                chatbot_value, oss_state_value, e: gr.EventData):
    index = e._data['payload'][0]['index']
    chatbot_value = chatbot_value[:index]

    async for chunk in submit(None, config_form_value, mcp_config_value,
                              mcp_servers_btn_value, chatbot_value,
                              oss_state_value):
        yield chunk


def clear():
    return gr.update(value=None)


def select_welcome_prompt(input_value, e: gr.EventData):
    input_value['text'] = e._data['payload'][0]['value']['description']
    return gr.update(value=input_value)


def select_model(e: gr.EventData):
    return gr.update(visible=e._data['payload'][1].get('thought', False))


async def reset_mcp_config(mcp_servers_btn_value):
    mcp_servers_btn_value['data_source'] = default_mcp_servers
    return gr.update(value=default_mcp_config), gr.update(
        value=mcp_servers_btn_value), gr.update(
            welcome_config=welcome_config(default_mcp_prompts)), gr.update(
                value={
                    'mcp_config': default_mcp_config,
                    'mcp_prompts': default_mcp_prompts,
                    'mcp_servers': default_mcp_servers
                })


def has_mcp_config_changed(old_config: dict, new_config: dict) -> bool:
    old_servers = old_config.get('mcpServers', {})
    new_servers = new_config.get('mcpServers', {})

    if set(old_servers.keys()) != set(new_servers.keys()):
        return True

    for server_name in old_servers:
        old_server = old_servers[server_name]
        new_server = new_servers.get(server_name)
        if new_server is None:
            return True

        if old_server.get('type') == 'sse' and new_server.get('type') == 'sse':
            if old_server.get('url') != new_server.get('url'):
                return True
        else:
            return True
    return False


def save_mcp_config_wrapper(initial: bool):

    async def save_mcp_config(mcp_config_value, mcp_servers_btn_value,
                              browser_state_value):
        mcp_config = json.loads(mcp_config_value)
        prev_mcp_config = json.loads(browser_state_value['mcp_config'])
        browser_state_value['mcp_config'] = mcp_config_value
        if has_mcp_config_changed(prev_mcp_config, mcp_config):
            mcp_servers_btn_value['data_source'] = [{
                'name': mcp_name,
                'enabled': True
            } for mcp_name in mcp_config.get('mcpServers', {}).keys()
                                                    ] + default_mcp_servers
            browser_state_value['mcp_servers'] = mcp_servers_btn_value[
                'data_source']
            yield gr.update(
                welcome_config=welcome_config({}, loading=True)), gr.update(
                    value=mcp_servers_btn_value), gr.skip()
            if not initial:
                gr.Success('保存成功')
            prompts = await get_mcp_prompts(
                mcp_config=merge_mcp_config(mcp_config, internal_mcp_config),
                model=mcp_prompt_model,
                openai_client=AsyncOpenAI(
                    api_key=api_key,
                    base_url='https://api-inference.modelscope.cn/v1/'))

            browser_state_value['mcp_prompts'] = prompts
            yield gr.update(
                welcome_config=welcome_config(prompts)), gr.skip(), gr.update(
                    value=browser_state_value)
        else:
            yield gr.skip(), gr.skip(), gr.update(value=browser_state_value)
            if not initial:
                gr.Success('保存成功')

    return save_mcp_config


def save_mcp_servers(mcp_servers_btn_value, browser_state_value):
    browser_state_value['mcp_servers'] = mcp_servers_btn_value['data_source']
    return gr.update(value=browser_state_value)


def load(mcp_servers_btn_value, browser_state_value, url_mcp_config_value):
    if browser_state_value:
        mcp_servers_btn_value['data_source'] = browser_state_value[
            'mcp_servers']
        try:
            url_mcp_config = json.loads(url_mcp_config_value)
        except:
            url_mcp_config = {}
        return gr.update(
            value=json.dumps(
                merge_mcp_config(
                    json.loads(browser_state_value['mcp_config']),
                    url_mcp_config),
                indent=4)), gr.update(
                    welcome_config=welcome_config(
                        browser_state_value['mcp_prompts'])), gr.update(
                            value=mcp_servers_btn_value)
    elif url_mcp_config_value:
        try:
            url_mcp_config = json.loads(url_mcp_config_value)
        except:
            url_mcp_config = {}
        return gr.update(
            value=json.dumps(merge_mcp_config(url_mcp_config, {}),
                             indent=4)), gr.skip(), gr.skip()
    return gr.skip()


def lighten_color(hex_color, factor=0.2):
    hex_color = hex_color.lstrip('#')

    # 解析RGB值
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    # 向白色方向调整
    r = min(255, r + int((255 - r) * factor))
    g = min(255, g + int((255 - g) * factor))
    b = min(255, b + int((255 - b) * factor))

    # 转回十六进制
    return f'{r:02x}{g:02x}{b:02x}'


lighten_primary_color = lighten_color(primary_color, 0.4)

css = f"""
@media (max-width: 768px) {{
    .mcp-playground-header {{
        margin-top: 36px;
    }}
}}

.ms-gr-auto-loading-default-antd {{
    z-index: 1001 !important;
}}

.user-message-content {{
    background-color: #{lighten_primary_color};
}}
"""

js = 'function init() { window.MODEL_OPTIONS_MAP=' + json.dumps(
    model_options_map) + '}'

with gr.Blocks(css=css, js=js) as demo:
    browser_state = gr.BrowserState(
        {
            'mcp_config': default_mcp_config,
            'mcp_prompts': default_mcp_prompts,
            'mcp_servers': default_mcp_servers
        },
        storage_key='mcp_config')
    oss_state = gr.State({'oss_cache': {}})

    with ms.Application(), antdx.XProvider(
            locale=default_locale, theme=default_theme), ms.AutoLoading():

        with antd.Badge.Ribbon(placement='start'):
            with ms.Slot('text'):
                with antd.Typography.Link(
                        elem_style=dict(color='#fff'),
                        type='link',
                        href='https://modelscope.cn/mcp',
                        href_target='_blank'):
                    with antd.Flex(
                            align='center', gap=2, elem_style=dict(padding=2)):
                        antd.Icon(
                            'ExportOutlined', elem_style=dict(marginRight=4))
                        ms.Text('前往')
                        antd.Image(
                            './assets/modelscope-mcp.png',
                            preview=False,
                            width=20,
                            height=20)
                        ms.Text('ModelScope MCP 广场')
            with ms.Div(elem_style=dict(overflow='hidden')):
                with antd.Flex(
                        justify='center',
                        gap='small',
                        align='center',
                        elem_classes='mcp-playground-header'):
                    with ms.Div(elem_style=dict(flexShrink=0, display='flex')):
                        antd.Image(
                            './assets/logo.png',
                            preview=False,
                            elem_style=dict(backgroundColor='#fff'),
                            width=50,
                            height=50)
                    antd.Typography.Title(
                        'MCP Playground',
                        level=1,
                        elem_style=dict(fontSize=28, margin=0))

        with antd.Tabs():
            with antd.Tabs.Item(label='实验场'):
                with antd.Flex(
                        vertical=True,
                        gap='middle',
                        elem_style=dict(
                            height=
                            'calc(100vh - 46px - 16px - 50px - 16px - 16px - 21px - 16px)',
                            maxHeight=1500)):
                    with antd.Card(
                            elem_style=dict(
                                flex=1,
                                height=0,
                                display='flex',
                                flexDirection='column'),
                            styles=dict(
                                body=dict(
                                    flex=1,
                                    height=0,
                                    display='flex',
                                    flexDirection='column'))):
                        chatbot = pro.Chatbot(
                            height=0,
                            bot_config=bot_config(),
                            user_config=user_config(),
                            welcome_config=welcome_config(default_mcp_prompts),
                            elem_style=dict(flex=1))
                    with pro.MultimodalInput(
                            upload_config=MultimodalInputUploadConfig(
                                placeholder={
                                    'inline': {
                                        'title': '上传文件',
                                        'description': '拖拽文件到此处或点击录音按钮开始录音'
                                    },
                                    'drop': {
                                        'title': '将文件拖放到此处',
                                    }
                                },
                                title=
                                '上传附件（只对部分支持远程文件 URL 的 MCP Server 生效，文件个数上限: 10）',
                                multiple=True,
                                allow_paste_file=True,
                                allow_speech=True,
                                max_count=10)) as input:
                        with ms.Slot('prefix'):
                            with antd.Button(
                                    value=None, variant='text',
                                    color='default') as clear_btn:
                                with ms.Slot('icon'):
                                    antd.Icon('ClearOutlined')
                            mcp_servers_btn = McpServersButton(
                                data_source=default_mcp_servers)

            with antd.Tabs.Item(label='配置'):
                with antd.Flex(vertical=True, gap='small'):
                    with antd.Card():
                        config_form, mcp_config_confirm_btn, reset_mcp_config_btn, mcp_config = ConfigForm(
                        )

    url_mcp_config = gr.Textbox(visible=False)
    load_event = demo.load(
        fn=load,
        js=
        "(mcp_servers_btn_value, browser_state_value) => [mcp_servers_btn_value, browser_state_value, decodeURIComponent(new URLSearchParams(window.location.search).get('studio_additional_params') || '') || null]",
        inputs=[mcp_servers_btn, browser_state, url_mcp_config],
        outputs=[mcp_config, chatbot, mcp_servers_btn])

    chatbot.welcome_prompt_select(
        fn=select_welcome_prompt, inputs=[input], outputs=[input], queue=False)
    retry_event = chatbot.retry(
        fn=retry,
        inputs=[config_form, mcp_config, mcp_servers_btn, chatbot, oss_state],
        outputs=[input, clear_btn, chatbot])
    clear_btn.click(fn=clear, outputs=[chatbot], queue=False)
    mcp_servers_btn.change(
        fn=save_mcp_servers,
        inputs=[mcp_servers_btn, browser_state],
        outputs=[browser_state])

    load_success_save_mcp_config_event = load_event.success(
        fn=save_mcp_config_wrapper(initial=True),
        inputs=[mcp_config, mcp_servers_btn, browser_state],
        outputs=[chatbot, mcp_servers_btn, browser_state])
    save_mcp_config_event = mcp_config_confirm_btn.click(
        fn=save_mcp_config_wrapper(initial=False),
        inputs=[mcp_config, mcp_servers_btn, browser_state],
        cancels=[load_success_save_mcp_config_event],
        outputs=[chatbot, mcp_servers_btn, browser_state])
    reset_mcp_config_btn.click(
        fn=reset_mcp_config,
        inputs=[mcp_servers_btn],
        outputs=[mcp_config, mcp_servers_btn, chatbot, browser_state],
        cancels=[save_mcp_config_event, load_success_save_mcp_config_event])
    submit_event = input.submit(
        fn=submit,
        inputs=[
            input, config_form, mcp_config, mcp_servers_btn, chatbot, oss_state
        ],
        outputs=[input, clear_btn, chatbot])
    input.cancel(
        fn=cancel,
        inputs=[chatbot],
        outputs=[input, clear_btn, chatbot],
        cancels=[submit_event, retry_event],
        queue=False)

demo.queue(
    default_concurrency_limit=100, max_size=100).launch(
        ssr_mode=False, max_threads=100)
