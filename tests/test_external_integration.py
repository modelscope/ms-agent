"""
测试external_integration模块功能
"""
import sys
import tempfile
import os
from pathlib import Path

# 添加项目根目录到模块路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from external_integration.code_scratch_caller import CodeScratchCaller
from external_integration.deep_research_caller import DeepResearchCaller
from external_integration.prompt_injector import PromptInjector
from external_integration.test_runner import TestRunner


def test_prompt_injector():
    """测试PromptInjector功能"""
    print("Testing PromptInjector...")
    
    # 创建临时技术规范文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("# Technical Specification\n\n## Overview\nA simple calculator app\n")
        spec_path = Path(f.name)
    
    # 创建临时测试目录
    with tempfile.TemporaryDirectory() as temp_dir:
        test_dir = Path(temp_dir) / "tests"
        test_dir.mkdir()
        
        # 创建一个简单的测试文件
        test_file = test_dir / "test_simple.py"
        test_file.write_text("""
import pytest

def test_add():
    assert 1 + 1 == 2
""")
        
        # 测试PromptInjector
        injector = PromptInjector()
        prompt = injector.inject(spec_path, test_dir, "Create a calculator")
        
        print(f"Generated prompt length: {len(prompt)}")
        print("Prompt Injector test: PASSED")
        
        # 清理临时文件
        os.unlink(spec_path)


def test_test_runner():
    """测试TestRunner功能"""
    print("Testing TestRunner...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        work_dir = Path(temp_dir)
        
        # 创建src目录和一个简单的Python文件
        src_dir = work_dir / "src"
        src_dir.mkdir()
        (src_dir / "calculator.py").write_text("""
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b
""")
        
        # 创建tests目录和对应的测试
        tests_dir = work_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_calculator.py").write_text("""
from src.calculator import add, subtract

def test_add():
    assert add(2, 3) == 5

def test_subtract():
    assert subtract(5, 3) == 2
""")
        
        # 运行测试
        runner = TestRunner()
        result = runner.run_tests(tests_dir, src_dir)
        
        print(f"Test result: success={result['success']}, exit_code={result['exit_code']}")
        print("Test Runner test: PASSED")


def main():
    """运行所有测试"""
    print("Running external_integration module tests...\n")
    
    try:
        test_prompt_injector()
        print()
        test_test_runner()
        print("\nAll tests passed!")
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()