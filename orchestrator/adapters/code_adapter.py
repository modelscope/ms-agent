from pathlib import Path
from typing import Any, Dict, List

from orchestrator.adapters.base import BaseAdapter
from orchestrator.core.const import DIR_SRC


class CodeAdapter(BaseAdapter):
    """
    [Mock] Code Adapter (Role C)
    负责调用 Code Scratch 生成代码。
    """

    def run(self,
            query: str,
            spec_path: Path,
            tests_dir: Path,
            error_log: str = '') -> Dict[str, Any]:
        """
        执行代码生成。

        Args:
            query: 原始需求。
            spec_path: Spec 文件路径。
            tests_dir: 测试文件夹路径。
            error_log: (Outer Loop) 上一次运行失败的错误日志。

        Returns:
            {'src_dir': Path(...)}
        """
        # Mock 逻辑: 生成一个简单的 Python 脚本
        src_content = f"""
def main():
    print("Hello from Generated Code!")
    print("Query: {query}")

if __name__ == "__main__":
    main()
"""
        src_file = self.workspace.work_dir / DIR_SRC / 'main.py'
        src_file.parent.mkdir(exist_ok=True)
        src_file.write_text(src_content, encoding='utf-8')

        return {'src_dir': src_file.parent}
