#!/usr/bin/env python
"""
测试External Integration模块功能
"""

import tempfile
import shutil
from pathlib import Path
from external_integration.code_scratch_caller import CodeScratchCaller
from external_integration.deep_research_caller import DeepResearchCaller
from external_integration.prompt_injector import PromptInjector
from external_integration.test_runner import TestRunner


def test_deep_research_caller():
    """测试Deep Research调用器"""
    print("=== 测试 Deep Research 调用器 ===")
    
    caller = DeepResearchCaller(timeout=30)  # 30秒超时
    
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        
        # 测试调用（使用简单查询，可能由于API认证失败，但应返回适当错误）
        result = caller.run(
            query="什么是人工智能？",
            output_dir=output_dir
        )
        
        print(f"Deep Research 调用结果: {result['success']}")
        print(f"返回码: {result['returncode']}")
        if result['stderr']:
            print(f"错误信息: {result['stderr'][:200]}...")  # 只显示前200个字符
    
    print("Deep Research 调用器测试完成\n")


def test_prompt_injector():
    """测试Prompt注入器"""
    print("=== 测试 Prompt 注入器 ===")
    
    injector = PromptInjector()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        work_dir = Path(temp_dir)
        
        # 创建测试技术规范
        spec_path = work_dir / "tech_spec.md"
        spec_content = """
# 技术规范：简单计算器

## 功能要求
- 实现加法、减法、乘法、除法功能
- 支持整数和浮点数运算
- 处理除零错误
        """
        spec_path.write_text(spec_content, encoding='utf-8')
        
        # 创建测试目录和测试文件
        test_dir = work_dir / "tests"
        test_dir.mkdir()
        
        test_file = test_dir / "test_calculator.py"
        test_content = """
def test_add():
    assert 1 + 1 == 2

def test_divide_by_zero():
    try:
        result = 1 / 0
        assert False, "应该抛出异常"
    except ZeroDivisionError:
        pass
        """
        test_file.write_text(test_content, encoding='utf-8')
        
        # 测试prompt注入
        base_query = "实现一个简单计算器"
        full_prompt = injector.inject(spec_path, test_dir, base_query)
        
        print(f"生成的完整Prompt长度: {len(full_prompt)} 字符")
        print(f"Prompt包含技术规范: {'技术规范' in full_prompt}")
        print(f"Prompt包含测试用例: {'test_add' in full_prompt}")
        
    print("Prompt 注入器测试完成\n")


def test_test_runner():
    """测试测试运行器"""
    print("=== 测试 测试运行器 ===")
    
    runner = TestRunner(timeout=30)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        work_dir = Path(temp_dir)
        
        # 创建src目录
        src_dir = work_dir / "src"
        src_dir.mkdir()
        
        # 创建一个简单的源代码文件
        main_file = src_dir / "main.py"
        main_content = """
def add(a, b):
    return a + b

def divide(a, b):
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return a / b
        """
        main_file.write_text(main_content, encoding='utf-8')
        
        # 创建测试目录和测试文件
        test_dir = work_dir / "tests"
        test_dir.mkdir()
        
        test_file = test_dir / "test_main.py"
        test_content = """
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from main import add, divide

def test_add():
    assert add(2, 3) == 5

def test_divide():
    assert divide(6, 2) == 3

def test_divide_by_zero():
    try:
        divide(1, 0)
        assert False, "Should raise ZeroDivisionError"
    except ZeroDivisionError:
        pass
        """
        test_file.write_text(test_content, encoding='utf-8')
        
        # 运行测试
        result = runner.run_tests(test_dir, src_dir)
        
        print(f"测试执行结果: {'通过' if result['success'] else '失败'}")
        print(f"返回码: {result['exit_code']}")
        print(f"发现错误数: {len(result['parsed_errors'])}")
        
        # 运行带反馈的测试
        feedback = runner.run_tests_with_feedback(work_dir)
        print(f"反馈结果: {'需要重试' if feedback['should_retry'] else '无需重试'}")
    
    print("测试运行器测试完成\n")


def test_code_scratch_caller():
    """测试Code Scratch调用器"""
    print("=== 测试 Code Scratch 调用器 ===")

    caller = CodeScratchCaller(timeout=30)  # 30秒超时

    with tempfile.TemporaryDirectory() as temp_dir:
        work_dir = Path(temp_dir)

        # 测试调用（使用简单提示，可能由于API认证失败，但应返回适当错误）
        print("注意：由于API密钥问题，Code Scratch可能会失败，但这表明模块能处理错误")
        result = caller.run(
            prompt="创建一个简单的Python程序，打印'Hello World'",
            work_dir=work_dir
        )

        print(f"Code Scratch 调用结果: {result['success']}")
        print(f"返回码: {result['returncode']}")
        if result['stderr']:
            error_preview = result['stderr'][:200] if len(result['stderr']) > 200 else result['stderr']
            print(f"错误信息预览: {error_preview}...")
        else:
            print("无错误信息")

    print("Code Scratch 调用器测试完成\n")


def main():
    """主测试函数"""
    print("开始测试 External Integration 模块功能\n")
    
    try:
        test_deep_research_caller()
        test_prompt_injector()
        test_test_runner()
        test_code_scratch_caller()
        
        print("所有测试完成！")
        print("\n注意：API认证相关的模块（Deep Research和Code Scratch）可能会由于API密钥问题失败，")
        print("但这表明模块能够正确处理错误并返回适当的错误信息。")
        
    except Exception as e:
        print(f"测试过程中出现异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()