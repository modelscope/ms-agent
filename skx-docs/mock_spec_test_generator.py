# Mock Spec和Test生成器实现

# 创建一个mock目录来存放mock实现
import os
from pathlib import Path

import json


class MockSpecGenerator:
    """
    Mock实现：将report.md转换为tech_spec.md
    在真实Spec Adapter就位前，生成一个基本的技术规范文档
    """

    @staticmethod
    def generate_spec(report_path, output_path):
        """
        从report.md生成tech_spec.md的Mock实现
        """
        # 读取report内容
        with open(report_path, 'r', encoding='utf-8') as f:
            report_content = f.read()

        # 生成基本的tech_spec.md模板
        tech_spec_content = f"""# Technical Specification

## Overview
This document outlines the technical specifications derived from the research report.

## Original Research Report Summary
{report_content[:500]}...  # 截取报告前500字符作为摘要

## System Architecture
- Define system components here
- Specify interactions between components

## API Definitions
### Endpoints
- `GET /api/endpoint`: Description of endpoint
- `POST /api/endpoint`: Description of endpoint

## Data Models
### Model Name
- field1: description
- field2: description

## Implementation Plan
1. Phase 1: Initial setup
2. Phase 2: Core functionality
3. Phase 3: Testing and validation

## Dependencies
- Python 3.x
- Required libraries

## Testing Strategy
- Unit tests for each component
- Integration tests
- Performance tests
"""

        # 写入tech_spec.md
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(tech_spec_content)

        # 同时生成api_definitions.json（空的）
        api_defs_path = output_path.replace('tech_spec.md',
                                            'api_definitions.json')
        with open(api_defs_path, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=2)

        print(f'Mock tech_spec.md created at {output_path}')
        print(f'Mock api_definitions.json created at {api_defs_path}')


class MockTestGenerator:
    """
    Mock实现：从tech_spec.md生成tests目录下的测试文件
    在真实Test Generator就位前，生成基本的测试用例
    """

    @staticmethod
    def generate_tests(spec_path, tests_dir):
        """
        从tech_spec.md生成测试用例的Mock实现
        """
        # 确保tests目录存在
        Path(tests_dir).mkdir(parents=True, exist_ok=True)

        # 生成一个基本的测试文件
        test_content = '''import pytest
import sys
import os

# Add src directory to path to import the generated code
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_placeholder():
    """
    Placeholder test - to be replaced by real tests
    generated from tech_spec.md
    """
    # This is a placeholder test that always passes
    # Real tests will be generated from tech_spec.md
    assert True

def test_example_api():
    """
    Example test for API functionality
    """
    # This is an example test that would check actual API behavior
    # based on the requirements in tech_spec.md
    assert True

if __name__ == "__main__":
    pytest.main()
'''

        # 写入测试文件
        test_file_path = os.path.join(tests_dir, 'test_core.py')
        with open(test_file_path, 'w', encoding='utf-8') as f:
            f.write(test_content)

        print(f'Mock test file created at {test_file_path}')

        # 可以生成更多特定的测试文件
        # 这里生成一个conftest.py用于pytest配置
        conftest_content = '''import pytest

@pytest.fixture
def sample_data():
    """Sample data fixture for tests"""
    return {"key": "value", "number": 42}

'''
        conftest_path = os.path.join(tests_dir, 'conftest.py')
        with open(conftest_path, 'w', encoding='utf-8') as f:
            f.write(conftest_content)

        print(f'Mock conftest.py created at {conftest_path}')


# 示例用法
if __name__ == '__main__':
    # 示例：在当前目录下创建mock文件
    import tempfile

    # 创建临时报告文件用于演示
    with tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False) as temp_report:
        temp_report.write(
            '# Research Report\n\nThis is a sample research report.\n\n## Key Findings\n- Finding 1\n- Finding 2\n'
        )
        report_path = temp_report.name

    # 使用MockSpecGenerator生成spec
    output_spec_path = 'tech_spec.md'
    MockSpecGenerator.generate_spec(report_path, output_spec_path)

    # 使用MockTestGenerator生成测试
    tests_directory = 'tests'
    MockTestGenerator.generate_tests(output_spec_path, tests_directory)

    # 清理临时文件
    os.unlink(report_path)

    print('Mock implementation completed!')
