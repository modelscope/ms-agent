"""
Deep Research 调用器实现
通过subprocess调用projects/deep_research模块，实现无侵入式集成
"""
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


class DeepResearchCaller:
    """
    Deep Research 调用器
    通过subprocess调用projects/deep_research，传入用户query
    """

    def __init__(self, timeout: int = 600):
        """
        初始化DeepResearchCaller

        Args:
            timeout: subprocess调用的超时时间（秒）
        """
        self.timeout = timeout

    def run(self,
            query: str,
            output_dir: Path,
            model: Optional[str] = None,
            max_results: Optional[int] = None) -> Dict[str, Any]:
        """
        通过subprocess调用deep_research进行研究

        Args:
            query: 研究查询
            output_dir: 输出目录路径
            model: 指定使用的模型（可选）
            max_results: 最大结果数量（可选）

        Returns:
            包含执行结果的字典
        """
        # 确保输出目录存在
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 准备deep_research运行所需的参数
        deep_research_path = Path(
            __file__).parent.parent / 'projects' / 'deep_research' / 'run.py'

        if not deep_research_path.exists():
            raise FileNotFoundError(
                f'Deep Research入口文件不存在: {deep_research_path}')

        # 构建命令参数
        cmd = [
            sys.executable,
            str(deep_research_path), '--query', query, '--output_dir',
            str(output_dir)
        ]

        if model:
            cmd.extend(['--model', model])

        if max_results:
            cmd.extend(['--max_results', str(max_results)])

        # 设置环境变量，传递API key等配置
        env = os.environ.copy()

        try:
            # 执行deep_research
            result = subprocess.run(
                cmd,
                cwd=output_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout)

            return {
                'success':
                result.returncode == 0,
                'returncode':
                result.returncode,
                'stdout':
                result.stdout,
                'stderr':
                result.stderr,
                'output_dir':
                output_dir,
                'report_path':
                output_dir / 'report.md' if
                (output_dir / 'report.md').exists() else None
            }

        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr':
                f'Deep Research execution timed out after {self.timeout} seconds',
                'output_dir': output_dir,
                'report_path': None
            }
        except Exception as e:
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': str(e),
                'output_dir': output_dir,
                'report_path': None
            }
