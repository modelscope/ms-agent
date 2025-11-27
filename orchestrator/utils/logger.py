import logging
import sys
from pathlib import Path


def setup_logger(workspace_path: Path) -> logging.Logger:
    """
    配置并返回一个 Logger 实例。
    日志同时输出到控制台（INFO级别）和文件（DEBUG级别）。

    Args:
        workspace_path: 工作区根目录 Path 对象，日志将保存在 workspace_path/logs/orchestrator.log。

    Returns:
        logging.Logger 实例。
    """
    # 创建 logger
    logger = logging.getLogger('Orchestrator')
    logger.setLevel(logging.DEBUG)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 格式化器
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 1. 控制台 Handler (INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 2. 文件 Handler (DEBUG)
    log_file = workspace_path / 'logs' / 'orchestrator.log'
    # 确保目录存在
    log_file.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger
