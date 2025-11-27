from pathlib import Path
from typing import Any, Dict, List

from external_integration.code_scratch_caller import CodeScratchCaller
from external_integration.prompt_injector import PromptInjector
from external_integration.test_runner import TestRunner
from orchestrator.adapters.base import BaseAdapter
from orchestrator.core.const import DIR_SRC


class CodeAdapter(BaseAdapter):
    """
    Code Adapter (Role C)
    负责调用 Code Scratch 生成代码，并执行验证。
    """

    def __init__(self, config, workspace):
        super().__init__(config, workspace)
        self.code_caller = CodeScratchCaller()
        self.prompt_injector = PromptInjector()
        self.test_runner = TestRunner()

    def run(self,
            query: str,
            spec_path: Path,
            tests_dir: Path,
            error_log: str = '') -> Dict[str, Any]:
        """
        执行代码生成和验证。

        Args:
            query: 原始需求。
            spec_path: Spec 文件路径。
            tests_dir: 测试文件夹路径。
            error_log: (Outer Loop) 上一次运行失败的错误日志。

        Returns:
            {'src_dir': Path(...), 'success': bool}
        """
        # 使用PromptInjector构造包含spec和tests的元指令
        if error_log:
            # 如果有错误日志，包含修复指导
            full_prompt = self.prompt_injector.inject_with_error_feedback(
                spec_path, tests_dir, query, error_log)
        else:
            # 正常情况下的prompt注入
            full_prompt = self.prompt_injector.inject(spec_path, tests_dir,
                                                      query)

        # 调用CodeScratchCaller执行代码生成
        result = self.code_caller.run(
            prompt=full_prompt,
            work_dir=self.workspace.work_dir,
            model=getattr(self.config, 'model', None))

        # 检查代码生成是否成功
        if not result['success']:
            # 即使代码生成失败，也要确保src目录存在，以便后续流程
            src_dir = self.workspace.work_dir / DIR_SRC
            src_dir.mkdir(exist_ok=True)
            return {
                'src_dir': src_dir,
                'success': False,
                'error_message': result['stderr'],
                'test_feedback': None
            }

        # 验证生成的代码目录
        src_dir = self.workspace.work_dir / DIR_SRC
        if not src_dir.exists():
            # 如果code_scratch没有生成src目录，创建一个空目录
            src_dir.mkdir(exist_ok=True)

        # 执行测试验证
        test_feedback = self.test_runner.run_tests_with_feedback(
            work_dir=self.workspace.work_dir)

        success = test_feedback['test_results']['success']

        return {
            'src_dir': src_dir,
            'success': success,
            'test_feedback': test_feedback
        }
