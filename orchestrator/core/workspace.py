import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional


class WorkspaceManager:
    """
    工作区管理器。
    负责为每次运行创建独立的目录，并管理其中的文件路径。
    """

    def __init__(self, root_path: str, run_id: Optional[str] = None):
        """
        初始化工作区管理器。

        Args:
            root_path: 所有工作区的根目录路径。
            run_id: 本次运行的唯一标识符（通常是时间戳）。如果未提供，自动生成。
        """
        self.root_path = Path(root_path)
        if run_id:
            self.run_id = run_id
        else:
            self.run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        self.work_dir = self.root_path / self.run_id
        self.create()

    def create(self):
        """创建工作区目录。"""
        self.work_dir.mkdir(parents=True, exist_ok=True)
        # 创建常用的子目录
        (self.work_dir / 'tests').mkdir(exist_ok=True)
        (self.work_dir / 'src').mkdir(exist_ok=True)
        (self.work_dir / 'logs').mkdir(exist_ok=True)

    def get_path(self, filename: str) -> Path:
        """
        获取工作区内文件的绝对路径。

        Args:
            filename: 文件名（相对于工作区根目录）。

        Returns:
            Path 对象。
        """
        return self.work_dir / filename

    def ensure_file(self, filename: str, content: str = '') -> Path:
        """
        确保文件存在。如果文件不存在，创建它并写入初始内容。

        Args:
            filename: 文件名。
            content: 初始内容。

        Returns:
            Path 对象。
        """
        file_path = self.get_path(filename)
        if not file_path.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding='utf-8')
        return file_path

    def list_files(self, pattern: str = '*') -> List[Path]:
        """
        列出工作区内匹配模式的文件。

        Args:
            pattern: Glob 模式。

        Returns:
            文件路径列表。
        """
        return list(self.work_dir.rglob(pattern))

    def clean(self):
        """清理工作区（慎用）。"""
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)

    @property
    def logs_dir(self) -> Path:
        """返回日志目录路径。"""
        return self.work_dir / 'logs'
