from pathlib import Path
from typing import Any, Dict

from orchestrator.adapters.base import BaseAdapter
from orchestrator.core.const import FILE_REPORT, FILE_TECH_SPEC
from orchestrator.core.templates import TECH_SPEC_TEMPLATE


class SpecAdapter(BaseAdapter):
    """
    [Mock] Spec Adapter (Role B)
    负责将 Report 转化为 Technical Specification。
    """

    def run(self, report_path: Path) -> Dict[str, Any]:
        """
        执行 Spec 生成。

        Args:
            report_path: Report.md 的路径。

        Returns:
            {'spec_path': Path(...)}
        """
        if not report_path.exists():
            raise FileNotFoundError(f'Report file not found: {report_path}')

        # Mock 逻辑: 读取 Report，套用模板生成 Spec
        report_content = report_path.read_text(encoding='utf-8')

        # 这里只是简单的字符串格式化，真实实现会调用 LLM
        spec_content = TECH_SPEC_TEMPLATE.format(
            project_name='Demo Project',
            # 实际中这里会提取 report 摘要
        )

        spec_content += '\n\n<!-- Based on Report Content -->\n'
        spec_content += f'Original Report Summary: {report_content[:200]}...\n'

        spec_path = self.workspace.ensure_file(FILE_TECH_SPEC, spec_content)

        return {'spec_path': spec_path}
