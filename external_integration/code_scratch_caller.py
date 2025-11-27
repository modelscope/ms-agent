"""
Code Scratch 调用器实现
通过subprocess调用projects/code_scratch模块，实现无侵入式集成
"""
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional


class CodeScratchCaller:
    """
    Code Scratch 调用器
    通过subprocess调用projects/code_scratch，使用预设的spec和tests
    """

    def __init__(self, timeout: int = 300):
        """
        初始化CodeScratchCaller

        Args:
            timeout: subprocess调用的超时时间（秒）
        """
        self.timeout = timeout

    def run(self,
            prompt: str,
            work_dir: Path,
            model: Optional[str] = None) -> Dict[str, Any]:
        """
        通过subprocess调用code_scratch生成代码

        Args:
            prompt: 用于code_scratch的提示词
            work_dir: 工作目录路径
            model: 指定使用的模型（可选）

        Returns:
            包含执行结果的字典
        """
        # 确保工作目录存在
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        # 创建一个临时脚本来运行CLI命令
        temp_script = work_dir / '_temp_run_code_scratch.py'
        script_content = f'''
import sys
import os

# 添加项目根目录到Python路径
project_root = '{Path(__file__).parent.parent}'
sys.path.insert(0, project_root)

# 设置环境变量
os.environ['PYTHONPATH'] = project_root

# 设置命令行参数
sys.argv = ['cli.py', 'run', '--config', 'projects/code_scratch', '--query', {repr(prompt)!r}, '--trust_remote_code', 'true']

# 运行CLI
from ms_agent.cli.cli import run_cmd
run_cmd()
'''
        temp_script.write_text(script_content, encoding='utf-8')

        # 构建命令参数
        cmd = [sys.executable, str(temp_script)]

        # 设置环境变量，传递API key等配置
        env = os.environ.copy()
        # 添加PYTHONPATH以确保能够找到ms_agent模块
        if 'PYTHONPATH' in env:
            env['PYTHONPATH'] = f"{Path(__file__).parent.parent}:{env['PYTHONPATH']}"
        else:
            env['PYTHONPATH'] = str(Path(__file__).parent.parent)

        # 添加API密钥到环境变量
        if os.getenv('MODELSCOPE_API_KEY'):
            env['MODELSCOPE_API_KEY'] = os.getenv('MODELSCOPE_API_KEY')
        if os.getenv('OPENAI_API_KEY'):
            env['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY')
        if os.getenv('OPENAI_BASE_URL'):
            env['OPENAI_BASE_URL'] = os.getenv('OPENAI_BASE_URL')

        try:
            # 执行code_scratch
            result = subprocess.run(
                cmd,
                cwd=work_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout)

            # 删除临时脚本
            try:
                temp_script.unlink()
            except:
                pass  # 忽略删除失败

            return {
                'success': result.returncode == 0,
                'returncode': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'work_dir': work_dir
            }

        except subprocess.TimeoutExpired:
            # 删除临时脚本
            try:
                temp_script.unlink()
            except:
                pass  # 忽略删除失败

            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr':
                f'Code Scratch execution timed out after {self.timeout} seconds',
                'work_dir': work_dir
            }
        except Exception as e:
            # 删除临时脚本
            try:
                temp_script.unlink()
            except:
                pass  # 忽略删除失败

            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': str(e),
                'work_dir': work_dir
            }
