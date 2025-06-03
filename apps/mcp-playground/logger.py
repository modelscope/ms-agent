import logging
import time
import os
from contextvars import ContextVar

request_id_var = ContextVar("request_id", default="")


class RequestIdFilter(logging.Filter):

    def filter(self, record):
        record.request_id = request_id_var.get("")
        record.timestamp = int(time.time() * 1000)
        return True


# 设置日志格式
formatter = logging.Formatter(
    '[%(asctime)s] [REQ:%(request_id)s] [%(filename)s:%(lineno)d] [%(levelname)s] %(message)s'
)

# 配置日志记录器
logger = logging.getLogger('modelscope-mcp-playground')
logger.setLevel(logging.DEBUG)  # 设置为DEBUG级别以捕获所有日志

logs_dir = 'mnt/workspace/logs'

os.makedirs(logs_dir, exist_ok=True)

# 文件处理器 - 信息和错误日志
info_file_handler = logging.FileHandler(logs_dir + '/info.log')
info_file_handler.setLevel(logging.INFO)
info_file_handler.addFilter(RequestIdFilter())
info_file_handler.setFormatter(formatter)

# 文件处理器 - 仅错误日志
error_file_handler = logging.FileHandler(logs_dir + '/error.log')
error_file_handler.setLevel(logging.ERROR)
error_file_handler.addFilter(RequestIdFilter())
error_file_handler.setFormatter(formatter)

# 文件处理器 - 调试日志
debug_file_handler = logging.FileHandler(logs_dir + '/debug.log')
debug_file_handler.setLevel(logging.DEBUG)
debug_file_handler.addFilter(RequestIdFilter())
debug_file_handler.setFormatter(formatter)

# 控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.addFilter(RequestIdFilter())
console_handler.setFormatter(formatter)

# 添加所有处理器
logger.addHandler(info_file_handler)
logger.addHandler(error_file_handler)
logger.addHandler(debug_file_handler)
logger.addHandler(console_handler)
