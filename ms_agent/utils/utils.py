# Copyright (c) Alibaba, Inc. and its affiliates.
import hashlib
import importlib
import os.path
import re
from io import BytesIO
from typing import List, Optional

import json
import requests
from omegaconf import DictConfig, OmegaConf

from modelscope.hub.utils.utils import get_cache_dir


def assert_package_exist(package, message: Optional[str] = None):
    """
    Checks whether a specified Python package is available in the current environment.

    If the package is not found, an AssertionError is raised with a customizable message.
    This is useful for ensuring that required dependencies are installed before proceeding
    with operations that depend on them.

    Args:
        package (str): The name of the package to check.
        message (Optional[str]): A custom error message to display if the package is not found.
                                 If not provided, a default message will be used.

    Raises:
        AssertionError: If the specified package is not found in the current environment.

    Example:
        >>> assert_package_exist('numpy')
        # Proceed only if numpy is installed; otherwise, raises AssertionError
    """
    message = message or f'Cannot find the pypi package: {package}, please install it by `pip install -U {package}`'
    assert importlib.util.find_spec(package), message


def strtobool(val) -> bool:
    """
    Convert a string representation of truth to `True` or `False`.

    True values are: 'y', 'yes', 't', 'true', 'on', and '1'.
    False values are: 'n', 'no', 'f', 'false', 'off', and '0'.
    The input is case-insensitive.

    Args:
        val (str): A string representing a boolean value.

    Returns:
        bool: `True` if the string represents a true value, `False` if it represents a false value.

    Raises:
        ValueError: If the input string does not match any known truth value.

    Example:
        >>> strtobool('Yes')
        True
        >>> strtobool('0')
        False
    """
    val = val.lower()
    if val in {'y', 'yes', 't', 'true', 'on', '1'}:
        return True
    if val in {'n', 'no', 'f', 'false', 'off', '0'}:
        return False
    raise ValueError(f'invalid truth value {val!r}')


def str_to_md5(text: str) -> str:
    """
    Converts a given string into its corresponding MD5 hash.

    This function encodes the input string using UTF-8 and computes the MD5 hash,
    returning the result as a 32-character hexadecimal string.

    Args:
        text (str): The input string to be hashed.

    Returns:
        str: The MD5 hash of the input string, represented as a hexadecimal string.

    Example:
        >>> str_to_md5("hello world")
        '5eb63bbbe01eeed093cb22bb8f5acdc3'
    """
    text_bytes = text.encode('utf-8')
    md5_hash = hashlib.md5(text_bytes)
    return md5_hash.hexdigest()


def escape_yaml_string(text: str) -> str:
    """
    Escapes special characters in a string to make it safe for use in YAML documents.

    This function escapes backslashes, dollar signs, and double quotes by adding
    a backslash before each of them. This is useful when dynamically inserting
    strings into YAML content to prevent syntax errors or unintended behavior.

    Args:
        text (str): The input string that may contain special characters.

    Returns:
        str: A new string with special YAML characters escaped.

    Example:
        >>> escape_yaml_string('Path: C:\\Program Files\\App, value="$VAR"')
        'Path: C:\\\\Program Files\\\\App, value=\\\"$VAR\\\"'
    """
    text = text.replace('\\', '\\\\')
    text = text.replace('$', '\\$')
    text = text.replace('"', '\\"')
    return text


def save_history(query: str, task: str, config: DictConfig,
                 messages: List['Message']):
    """
        将指定的配置和对话历史保存到缓存目录中，用于后续读取或恢复。

        该函数会根据输入的查询语句生成一个 MD5 哈希值作为唯一标识符，
        并据此创建对应的缓存文件夹。随后将传入的配置对象保存为 YAML 文件，
        对话消息列表序列化为 JSON 文件进行存储。

        Args:
            query (str): 用户输入的原始查询语句，用于生成缓存文件夹名的唯一标识（MD5 哈希）。
            task (str): 当前任务名称，用于命名对应的 .yaml 和 .json 缓存文件。
            config (DictConfig): 需要保存的配置对象，通常由 OmegaConf 构建。
            messages (List[Message]): 包含多个 Message 实例的对话记录列表，需支持 to_dict() 方法用于序列化。

        Returns:
            None: 无返回值。操作结果体现为磁盘上的缓存文件写入。

        Raises:
            可能抛出文件操作异常（如权限错误）或序列化异常（如对象无法被转换为字典）。
    """
    cache_dir = os.path.join(get_cache_dir(), 'workflow_cache')
    os.makedirs(cache_dir, exist_ok=True)
    folder = str_to_md5(query)
    os.makedirs(os.path.join(cache_dir, folder), exist_ok=True)
    config_file = os.path.join(cache_dir, folder, f'{task}.yaml')
    message_file = os.path.join(cache_dir, folder, f'{task}.json')
    with open(config_file, 'w') as f:
        OmegaConf.save(config, f)
    with open(message_file, 'w') as f:
        json.dump([message.to_dict() for message in messages], f)


def read_history(query: str, task: str):
    """
    从缓存目录中读取与给定查询和任务相关的配置信息和对话历史记录。

    该函数根据输入的 query 生成一个 MD5 哈希作为唯一标识符，用于定位缓存文件夹。
    然后尝试加载对应的 YAML 配置文件和 JSON 格式的对话消息历史文件（包含 Message 对象列表）。

    如果文件不存在，则对应返回值为 None。配置文件会经过字段补全处理，消息文件会反序列化为 Message 实例列表。

    Args:
        query (str): 用户输入的查询语句，用于生成缓存目录名的唯一标识（MD5 哈希）。
        task (str): 当前任务名称，用于匹配对应的 .yaml 和 .json 缓存文件。

    Returns:
        Tuple[Optional[Config], Optional[List[Message]]]: 包含两个元素的元组：
            - Config 对象或 None（若配置文件不存在）
            - Message 实例列表或 None（若消息文件不存在）

    Raises:
        可能抛出文件操作或反序列化异常（如 JSONDecodeError）。
    """
    from ms_agent.llm import Message
    from ms_agent.config import Config
    cache_dir = os.path.join(get_cache_dir(), 'workflow_cache')
    os.makedirs(cache_dir, exist_ok=True)
    folder = str_to_md5(query)
    config_file = os.path.join(cache_dir, folder, f'{task}.yaml')
    message_file = os.path.join(cache_dir, folder, f'{task}.json')
    config = None
    messages = None
    if os.path.exists(config_file):
        config = OmegaConf.load(config_file)
        config = Config.fill_missing_fields(config)
    if os.path.exists(message_file):
        with open(message_file, 'r') as f:
            messages = json.load(f)
            messages = [Message(**message) for message in messages]
    return config, messages


def text_hash(text: str, keep_n_chars: int = 8) -> str:
    """
    Encodes a given text using SHA256 and returns the last 8 characters
    of the hexadecimal representation.

    Args:
        text (str): The input string to be encoded.
        keep_n_chars (int): The number of characters to keep from the end of the hash.

    Returns:
        str: The last 8 characters of the SHA256 hash in hexadecimal,
             or an empty string if the input is invalid.
    """
    try:
        # Encode the text to bytes (UTF-8 is a common choice)
        text_bytes = text.encode('utf-8')

        # Calculate the SHA256 hash
        sha256_hash = hashlib.sha256(text_bytes)

        # Get the hexadecimal representation of the hash
        hex_digest = sha256_hash.hexdigest()

        # Return the last 8 characters
        return hex_digest[-keep_n_chars:]
    except Exception as e:
        print(f'An error occurred: {e}')
        return ''


def json_loads(text: str) -> dict:
    """
    将输入的字符串解析为 JSON 对象。支持标准 JSON 和部分非标准格式（如带有注释的 JSON），必要时使用 json5 进行兼容性解析。

    该函数会自动去除字符串两端的换行符，并尝试移除可能存在的 Markdown 代码块标记（```json ... \n```）。
    首先尝试使用标准 json 模块解析，若失败则使用 json5 模块进行更宽松的解析。

    Args:
        text (str): 待解析的 JSON 字符串，可能包含 Markdown 代码块包裹或格式问题。

    Returns:
        dict: 解析得到的 Python dict object。

    Raises:
        json.decoder.JSONDecodeError: 如果最终无法解析该字符串为有效 JSON，则抛出标准 JSON 解码错误。
    """
    import json5
    text = text.strip('\n')
    if text.startswith('```') and text.endswith('\n```'):
        text = '\n'.join(text.split('\n')[1:-1])
    try:
        return json.loads(text)
    except json.decoder.JSONDecodeError as json_err:
        try:
            return json5.loads(text)
        except ValueError:
            raise json_err


def download_pdf(url: str, out_file_path: str, reuse: bool = True):
    """
    Downloads a PDF from a given URL and saves it to a specified filename.

    Args:
        url (str): The URL of the PDF to download.
        out_file_path (str): The name of the file to save the PDF as.
        reuse (bool): If True, skips the download if the file already exists.
    """

    if reuse and os.path.exists(out_file_path):
        print(f"File '{out_file_path}' already exists. Skipping download.")
        return

    try:
        response = requests.get(url, stream=True)
        response.raise_for_status(
        )  # Raise an exception for bad status codes (4xx or 5xx)

        with open(out_file_path, 'wb') as pdf_file:
            for chunk in response.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
        print(f"PDF downloaded successfully to '{out_file_path}'")
    except requests.exceptions.RequestException as e:
        print(f'Error downloading PDF: {e}')


def remove_resource_info(text):
    """
    移除文本中所有 <resource_info>...</resource_info> 标签及其包含的内容。

    Args:
        text (str): 待处理的原始文本。

    Returns:
        str: 移除 <resource_info> 标签后的文本。
    """
    pattern = r'<resource_info>.*?</resource_info>'

    # 使用 re.sub() 替换匹配到的模式为空字符串
    cleaned_text = re.sub(pattern, '', text)
    return cleaned_text


def load_image_from_url_to_pil(url: str) -> 'Image.Image':
    """
    Loads an image from a given URL and converts it into a PIL Image object in memory.

    Args:
        url: The URL of the image.

    Returns:
        A PIL Image object if successful, None otherwise.
    """
    from PIL import Image
    try:
        response = requests.get(url)
        # Raise an HTTPError for bad responses (4xx or 5xx)
        response.raise_for_status()
        image_bytes = BytesIO(response.content)
        img = Image.open(image_bytes)
        return img
    except requests.exceptions.RequestException as e:
        print(f'Error fetching image from URL: {e}')
        return None
    except IOError as e:
        print(f'Error opening image with PIL: {e}')
        return None
