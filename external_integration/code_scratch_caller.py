"""
Code Scratch 调用器实现
通过subprocess调用projects/code_scratch模块，实现无侵入式集成
"""
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional


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

    def run(self, prompt: str, work_dir: Path, model: Optional[str] = None) -> Dict[str, Any]:
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
        
        # 准备code_scratch运行所需的参数
        code_scratch_path = Path(__file__).parent.parent / "projects" / "code_scratch" / "run.py"
        
        if not code_scratch_path.exists():
            raise FileNotFoundError(f"Code Scratch入口文件不存在: {code_scratch_path}")
        
        # 构建命令参数
        cmd = [
            sys.executable,
            str(code_scratch_path),
            "--query", prompt,
            "--output_dir", str(work_dir)
        ]
        
        if model:
            cmd.extend(["--model", model])
        
        # 设置环境变量，传递API key等配置
        env = os.environ.copy()
        
        try:
            # 执行code_scratch
            result = subprocess.run(
                cmd,
                cwd=work_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            return {
                'success': result.returncode == 0,
                'returncode': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'work_dir': work_dir
            }
            
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': f'Code Scratch execution timed out after {self.timeout} seconds',
                'work_dir': work_dir
            }
        except Exception as e:
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': str(e),
                'work_dir': work_dir
            }