import subprocess
from pathlib import Path
from typing import Tuple


def run_pytest(tests_dir: Path, workdir: Path) -> Tuple[int, str, str]:
    """
    在工作区运行 pytest。

    Args:
        tests_dir: 包含测试文件的目录。
        workdir: 运行测试的工作目录 (通常是 workspace root, 以便正确 import src)。

    Returns:
        (exit_code, stdout, stderr)
    """
    try:
        # 确保 tests_dir 是相对于 workdir 的
        # 或者直接在 workdir 运行 "pytest tests/"
        cmd = ['pytest', str(tests_dir)]

        # 设置 PYTHONPATH 包含 src
        # env = os.environ.copy()
        # env["PYTHONPATH"] = str(workdir)

        result = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=60  # 超时设置
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return -1, '', str(e)
