from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional


class BaseAdapter(ABC):
    """
    所有适配器的基类。
    定义了标准的 run 接口，强制实现者处理输入并产生输出。
    """

    def __init__(self, config, workspace_manager):
        """
        初始化适配器。

        Args:
            config (OrchestratorConfig): 全局配置对象。
            workspace_manager (WorkspaceManager): 工作区管理器，用于文件读写。
        """
        self.config = config
        self.workspace = workspace_manager

    @abstractmethod
    def run(self, **kwargs) -> Dict[str, Any]:
        """
        执行适配器逻辑。

        Returns:
            Dict: 执行结果，通常包含生成的关键文件路径。
                  例如: {'report_path': Path(...)}
        """
        pass
