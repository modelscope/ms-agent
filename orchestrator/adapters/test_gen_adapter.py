from pathlib import Path
from typing import Any, Dict

from orchestrator.adapters.base import BaseAdapter
from orchestrator.core.const import DIR_TESTS, FILE_TECH_SPEC, FILE_TEST_MAIN


class TestGenAdapter(BaseAdapter):
    """
    [Mock] Test Generator Adapter (Role B)
    负责基于 Spec 生成测试用例。
    """

    def run(self, spec_path: Path) -> Dict[str, Any]:
        """
        执行测试生成。

        Returns:
            {'tests_dir': Path(...)}
        """
        if not spec_path.exists():
            raise FileNotFoundError(f'Spec file not found: {spec_path}')

        # Mock 逻辑: 生成一个简单的 pytest 文件
        test_content = """
import pytest

def test_example():
    assert 1 + 1 == 2

def test_from_spec():
    # This is a placeholder test generated from spec
    pass
"""
        test_file_path = self.workspace.work_dir / DIR_TESTS / FILE_TEST_MAIN
        test_file_path.parent.mkdir(exist_ok=True)
        test_file_path.write_text(test_content, encoding='utf-8')

        return {'tests_dir': test_file_path.parent}
