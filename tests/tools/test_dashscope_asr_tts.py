import os

import pytest
from modelscope_agent.constants import DEFAULT_CODE_INTERPRETER_DIR
from modelscope_agent.tools.dashscope_tools.paraformer_asr_tool import \
    ParaformerAsrTool
from modelscope_agent.tools.dashscope_tools.sambert_tts_tool import \
    SambertTtsTool
from modelscope_agent.utils.base64_utils import encode_files_to_base64

from modelscope_agent.agents.role_play import RolePlay  # NOQA

IS_FORKED_PR = os.getenv('IS_FORKED_PR', 'false') == 'true'


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_paraformer_asr():
    params = """{'audio_path': '34aca18b-17a1-4558-9064-22fdfcef7a94.wav'}"""
    asr_tool = ParaformerAsrTool()
    res = asr_tool.call(params)
    assert res.lower() == 'today is a beautiful day. '


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_base64_paraformer_asr():
    work_dir = os.getenv('CODE_INTERPRETER_WORK_DIR',
                         DEFAULT_CODE_INTERPRETER_DIR)
    params = """{'audio_path': '34aca18b-17a1-4558-9064-22fdfcef7a94.wav'}"""

    file_paths = '34aca18b-17a1-4558-9064-22fdfcef7a94.wav'.split(',')
    for i, file_path in enumerate(file_paths):
        file_path = os.path.join(work_dir, file_path)
        file_paths[i] = file_path

    base64_files = encode_files_to_base64(file_paths)

    asr_tool = ParaformerAsrTool()
    kwargs = {}
    kwargs['base64_files'] = base64_files
    res = asr_tool.call(params, **kwargs)
    print(res)
    assert res.lower() == 'today is a beautiful day. '


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_sambert_tts():
    params = """{'text': '今天天气怎么样？'}"""
    tts_tool = SambertTtsTool()
    res = tts_tool.call(params)
    assert res.endswith('.wav"/>')


@pytest.mark.skip
def test_sambert_tts_with_tool_api():
    params = """{'text': '今天天气怎么样？'}"""
    tts_tool = SambertTtsTool()
    kwargs = {'use_tool_api': True}
    res = tts_tool.call(params, **kwargs)
    assert res.startswith('<audio src="http://')


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_paraformer_asr_agent():
    role_template = '你扮演一个语音专家，用尽可能丰富的描述调用工具处理语音。'

    llm_config = {'model': 'qwen-max', 'model_server': 'dashscope'}

    function_list = ['paraformer_asr']

    bot = RolePlay(
        function_list=function_list, llm=llm_config, instruction=role_template)

    response = bot.run(
        '[上传文件 "34aca18b-17a1-4558-9064-22fdfcef7a94.wav"], 将上面的音频识别出来')

    text = ''
    for chunk in response:
        text += chunk
    print(text)
    assert isinstance(text, str)


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_sambert_tts_agent():
    role_template = '你扮演一个语音专家，能够调用工具合成语音。'

    llm_config = {'model': 'qwen-max', 'model_server': 'dashscope'}

    function_list = ['sambert_tts']

    bot = RolePlay(
        function_list=function_list, llm=llm_config, instruction=role_template)

    response = bot.run('合成语音，语音内容为：“今天天气怎么样？会下雨吗？”')

    text = ''
    for chunk in response:
        text += chunk
    print(text)
    assert isinstance(text, str)
