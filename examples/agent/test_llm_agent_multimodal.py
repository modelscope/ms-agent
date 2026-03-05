"""
LLMAgent 多模态对话测试

从 LLMAgent 层面测试多模态功能，覆盖 stream 和非 stream 两种模式。
"""
import asyncio
import os
import sys
import uuid

from ms_agent import LLMAgent
from ms_agent.config import Config
from ms_agent.llm.utils import Message

# 获取脚本所在目录
path = os.path.dirname(os.path.abspath(__file__))
agent_config = os.path.join(path, '..', '..', 'ms_agent', 'agent', 'agent.yaml')


async def test_llm_agent_multimodal_non_stream():
    """
    测试 LLMAgent 非 stream 模式的多模态对话
    """
    print("=" * 70)
    print("测试 1: LLMAgent 非 stream 模式 - 多模态对话 (URL 图片)")
    print("=" * 70)

    # 创建配置
    config = Config.from_task(agent_config)

    # 配置多模态模型
    config.llm.model = 'qwen3.5-plus'
    config.llm.service = 'dashscope'
    config.llm.dashscope_api_key = os.environ.get('DASHSCOPE_API_KEY', '')
    config.llm.modelscope_base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

    # 禁用 stream、load_cache 和 callbacks（避免交互式输入问题）
    config.generation_config.stream = False
    config.load_cache = False
    config.callbacks = []

    if not config.llm.dashscope_api_key:
        print("[错误] 未设置 DASHSCOPE_API_KEY 环境变量")
        print("请先设置: export DASHSCOPE_API_KEY='your-api-key'")
        return False

    # 创建 LLMAgent，使用唯一 tag 避免历史记录的干扰
    tag = f"multimodal_test_{uuid.uuid4().hex[:8]}"
    agent = LLMAgent(config=config, tag=tag)

    # 测试图片 URL
    test_image_url = "https://dashscope.oss-cn-beijing.aliyuncs.com/images/dog_and_girl.jpeg"

    # 构建多模态内容
    multimodal_content = [
        {"type": "text", "text": "请详细描述这张图片中的内容。"},
        {"type": "image_url", "image_url": {"url": test_image_url}}
    ]

    try:
        print(f"\n[发送] 请描述这张图片: {test_image_url}")
        print("-" * 70)

        messages = [
            Message(role="system", content="你是一个多模态助手。"),
            Message(role="user", content=multimodal_content)
        ]

        response = await agent.run(messages=messages)

        print(f"\n[回复] {response[-1].content}")
        print("-" * 70)
        print(f"\n[Token使用] 输入: {response[-1].prompt_tokens}, 输出: {response[-1].completion_tokens}")

        return True
    except Exception as e:
        print(f"\n[错误] 非 stream 多模态对话失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_llm_agent_multimodal_stream():
    """
    测试 LLMAgent stream 模式的多模态对话
    """
    print("\n" + "=" * 70)
    print("测试 2: LLMAgent stream 模式 - 多模态对话 (URL 图片)")
    print("=" * 70)

    # 创建配置
    config = Config.from_task(agent_config)

    # 配置多模态模型
    config.llm.model = 'qwen3.5-plus'
    config.llm.service = 'dashscope'
    config.llm.dashscope_api_key = os.environ.get('DASHSCOPE_API_KEY', '')
    config.llm.modelscope_base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

    # 启用 stream，禁用 load_cache 和 callbacks
    config.generation_config.stream = True
    config.load_cache = False
    config.callbacks = []

    if not config.llm.dashscope_api_key:
        print("[错误] 未设置 DASHSCOPE_API_KEY 环境变量")
        return False

    # 创建 LLMAgent，使用唯一 tag
    tag = f"multimodal_stream_{uuid.uuid4().hex[:8]}"
    agent = LLMAgent(config=config, tag=tag)

    # 测试图片 URL
    test_image_url = "https://dashscope.oss-cn-beijing.aliyuncs.com/images/dog_and_girl.jpeg"

    # 构建多模态内容
    multimodal_content = [
        {"type": "text", "text": "请用中文描述这张图片中的内容。"},
        {"type": "image_url", "image_url": {"url": test_image_url}}
    ]

    try:
        print(f"\n[发送] 请描述这张图片: {test_image_url}")
        print("-" * 70)
        print("[回复开始]")

        messages = [
            Message(role="system", content="你是一个多模态助手。"),
            Message(role="user", content=multimodal_content)
        ]

        # stream 模式调用
        generator = await agent.run(messages=messages, stream=True)

        full_response = ""
        async for response_chunk in generator:
            if response_chunk and len(response_chunk) > 0:
                last_msg = response_chunk[-1]
                if last_msg.content and len(last_msg.content) > len(full_response):
                    # 流式输出新增内容
                    sys.stdout.write(last_msg.content[len(full_response):])
                    sys.stdout.flush()
                    full_response = last_msg.content

        print("\n" + "-" * 70)
        print(f"\n[完整回复长度] {len(full_response)} 字符")
        return True
    except Exception as e:
        print(f"\n[错误] stream 多模态对话失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_llm_agent_multimodal_base64_non_stream():
    """
    测试 LLMAgent 非 stream 模式 - Base64 编码图片
    """
    print("\n" + "=" * 70)
    print("测试 3: LLMAgent 非 stream 模式 - Base64 编码图片")
    print("=" * 70)

    import base64

    # 创建配置
    config = Config.from_task(agent_config)
    config.llm.model = 'qwen3.5-plus'
    config.llm.service = 'dashscope'
    config.llm.dashscope_api_key = os.environ.get('DASHSCOPE_API_KEY', '')
    config.llm.modelscope_base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    config.generation_config.stream = False
    config.load_cache = False
    config.callbacks = []

    if not config.llm.dashscope_api_key:
        print("[错误] 未设置 DASHSCOPE_API_KEY 环境变量")
        return False

    # 创建 LLMAgent，使用唯一 tag
    tag = f"multimodal_base64_{uuid.uuid4().hex[:8]}"
    agent = LLMAgent(config=config, tag=tag)

    # 一个简单的测试图片 base64 (1x1 像素)
    test_image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mNk+M9Qz0AEYBxVSF+FABJADq0/8ZEPAAAAAElFTkSuQmCC"

    multimodal_content = [
        {"type": "text", "text": "这是一个什么颜色的图片？请用中文简短回答。"},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{test_image_base64}"
            }
        }
    ]

    try:
        print("\n[发送] 这是什么颜色的图片？(Base64 编码)")
        print("-" * 70)

        messages = [
            Message(role="system", content="你是一个多模态助手。"),
            Message(role="user", content=multimodal_content)
        ]

        response = await agent.run(messages=messages)

        print(f"\n[回复] {response[-1].content}")
        print("-" * 70)
        return True
    except Exception as e:
        print(f"\n[错误] Base64 多模态对话失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_llm_agent_multimodal_conversation():
    """
    测试 LLMAgent 多轮对话中的多模态功能
    """
    print("\n" + "=" * 70)
    print("测试 4: LLMAgent 多轮对话 - 多模态 + 文本混合")
    print("=" * 70)

    # 创建配置
    config = Config.from_task(agent_config)
    config.llm.model = 'qwen3.5-plus'
    config.llm.service = 'dashscope'
    config.llm.dashscope_api_key = os.environ.get('DASHSCOPE_API_KEY', '')
    config.llm.modelscope_base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    config.generation_config.stream = False
    config.load_cache = False
    config.callbacks = []

    if not config.llm.dashscope_api_key:
        print("[错误] 未设置 DASHSCOPE_API_KEY 环境变量")
        return False

    # 创建 LLMAgent，使用唯一 tag
    tag = f"multimodal_conv_{uuid.uuid4().hex[:8]}"
    agent = LLMAgent(config=config, tag=tag)

    # 测试图片 URL
    test_image_url = "https://dashscope.oss-cn-beijing.aliyuncs.com/images/dog_and_girl.jpeg"

    try:
        # 第一轮：发送图片
        print("\n[第一轮] 发送图片并询问")
        print("-" * 70)

        multimodal_content = [
            {"type": "text", "text": "这张图片里有几个人？"},
            {"type": "image_url", "image_url": {"url": test_image_url}}
        ]

        messages = [
            Message(role="system", content="你是一个多模态助手。"),
            Message(role="user", content=multimodal_content)
        ]
        response = await agent.run(messages=messages)
        print(f"\n[第一轮回复] {response[-1].content[:200]}...")

        # 第二轮：继续追问（纯文本）
        print("\n[第二轮] 继续追问")
        print("-" * 70)

        # 保留历史记录，添加新的用户消息
        messages = response
        messages.append(Message(role="user", content="图片中的场景是在室内还是室外？"))
        response = await agent.run(messages=messages)
        print(f"\n[第二轮回复] {response[-1].content[:200]}...")

        # 第三轮：再次追问（纯文本）
        print("\n[第三轮] 再次追问")
        print("-" * 70)

        messages = response
        messages.append(Message(role="user", content="用一句话总结这张图片。"))
        response = await agent.run(messages=messages)
        print(f"\n[第三轮回复] {response[-1].content[:200]}...")

        print("-" * 70)
        return True
    except Exception as e:
        print(f"\n[错误] 多轮对话失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行所有测试"""
    print("\n" + "=" * 70)
    print("LLMAgent 多模态对话测试套件")
    print("=" * 70)
    print("\n请确保已设置环境变量: export DASHSCOPE_API_KEY='your-api-key'\n")

    results = []

    # 测试 1: 非 stream 模式
    result1 = await test_llm_agent_multimodal_non_stream()
    results.append(("非 stream 模式 (URL图片)", result1))

    # 测试 2: stream 模式
    result2 = await test_llm_agent_multimodal_stream()
    results.append(("stream 模式 (URL图片)", result2))

    # 测试 3: Base64 非 stream
    result3 = await test_llm_agent_multimodal_base64_non_stream()
    results.append(("非 stream 模式 (Base64)", result3))

    # 测试 4: 多轮对话
    result4 = await test_llm_agent_multimodal_conversation()
    results.append(("多轮对话", result4))

    # 总结
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)
    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"  {status} - {name}")

    passed = sum(1 for _, r in results if r)
    total = len(results)
    print(f"\n总计: {passed}/{total} 测试通过")

    return passed == total


if __name__ == '__main__':
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
