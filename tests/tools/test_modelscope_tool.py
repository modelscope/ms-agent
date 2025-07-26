import os

import pytest

IS_FORKED_PR = os.getenv('IS_FORKED_PR', 'false') == 'true'


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_modelscope_speech_generation():
    from modelscope_agent.tools.modelscope_tools.text_to_speech_tool import TexttoSpeechTool
    kwargs = """{'input': '北京今天天气怎样?', 'voice': 'zhitian_emo'}"""
    txt2speech = TexttoSpeechTool()
    res = txt2speech.call(kwargs)
    assert isinstance(res, str)


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_modelscope_speech_generation_with_tool_api():
    from modelscope_agent.tools.modelscope_tools.text_to_speech_tool import TexttoSpeechTool
    params = """{'input': '北京今天天气怎样?', 'voice': 'zhitian_emo'}"""
    kwargs = {'use_tool_api': True}
    txt2speech = TexttoSpeechTool()
    res = txt2speech.call(params, **kwargs)
    assert res.startswith('<audio src="https://')


@pytest.mark.skip
def test_modelscope_video_generation():
    from modelscope_agent.tools.modelscope_tools.text_to_video_tool import TextToVideoTool
    params = "{'input': '一个正在打篮球的人'}"
    video_gen = TextToVideoTool()
    res = video_gen.call(params)
    assert isinstance(res, str)


@pytest.mark.skip
def test_modelscope_video_generation_with_use_tool():
    from modelscope_agent.tools.modelscope_tools.text_to_video_tool import TextToVideoTool
    params = "{'input': '一个正在打篮球的人'}"
    video_gen = TextToVideoTool()
    kwargs = {'use_tool_api': True}
    res = video_gen.call(params, **kwargs)
    assert isinstance(res, str)


@pytest.mark.skip
def test_modelscope_text_address():
    from modelscope_agent.tools.modelscope_tools.text_address_tool import TextAddressTool
    kwargs = """{'input': '北京朝阳望京东金辉大厦'}"""
    txt_addr = TextAddressTool()
    res = txt_addr.call(kwargs)
    assert isinstance(res, str)


@pytest.mark.skip
def test_modelscope_text_ner_remote():
    from modelscope_agent.tools.modelscope_tools.text_ner_tool import TextNerTool
    kwargs = """{'input': '多数新生儿甲亢在出生时即有症状，表现为突眼、甲状腺肿大、烦躁、多动、心动过速、呼吸急促，严重可出现心力衰竭，血T3、T4升高，TSH下降。'}"""
    txt_ner = TextNerTool()
    res = txt_ner.call(kwargs)
    assert isinstance(res, str)


@pytest.mark.skipif(IS_FORKED_PR, reason='only run modelscope-agent main repo')
def test_modelscope_text_ner_local():
    from modelscope_agent.tools.modelscope_tools.text_ner_tool import TextNerTool
    kwargs = """{'input': '多数新生儿甲亢在出生时即有症状，表现为突眼、甲状腺肿大、烦躁、多动、心动过速、呼吸急促，严重可出现心力衰竭，血T3、T4升高，TSH下降。'}"""
    cfg = {
        'text-ner': {
            'is_remote_tool': False,
        }
    }
    txt_ner = TextNerTool(cfg)
    res = txt_ner.call(kwargs)
    assert isinstance(res, str)


@pytest.mark.skip
def test_modelscope_text_ie():
    from modelscope_agent.tools.modelscope_tools.text_ie_tool import TextInfoExtractTool
    kwargs = """{'input': '很满意，音质很好，发货速度快，值得购买', 'schema': {'属性词': {'情感词': null}}}"""
    txt_ie = TextInfoExtractTool()
    res = txt_ie.call(kwargs)
    assert isinstance(res, str)
