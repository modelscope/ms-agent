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
    message = message or f'Cannot find the pypi package: {package}, please install it by `pip install -U {package}`'
    assert importlib.util.find_spec(package), message


def strtobool(val) -> bool:
    val = val.lower()
    if val in {'y', 'yes', 't', 'true', 'on', '1'}:
        return True
    if val in {'n', 'no', 'f', 'false', 'off', '0'}:
        return False
    raise ValueError(f'invalid truth value {val!r}')


def str_to_md5(text: str) -> str:
    text_bytes = text.encode('utf-8')
    md5_hash = hashlib.md5(text_bytes)
    return md5_hash.hexdigest()


def escape_yaml_string(text: str) -> str:
    text = text.replace('\\', '\\\\')
    text = text.replace('$', '\\$')
    text = text.replace('"', '\\"')
    return text


def save_history(query: str, task: str, config: DictConfig,
                 messages: List['Message']):
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
