# Copyright (c) Alibaba, Inc. and its affiliates.
import base64
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


def save_history(output_dir: str, task: str, config: DictConfig,
                 messages: List['Message']):
    """
    Saves the specified configuration and conversation history to a cache directory for later retrieval or restoration.

    This function  saves the provided configuration object as a YAML file and serializes the list of conversation
    messages into a JSON file for storage.

    The generated cache structure is as follows:
        <output_dir>
            └── memory
                ├── <task>.yaml     <- Configuration
                └── <task>.json     <- Message history

    Args:
        output_dir (str): Base directory where the cache folder will be created.
        task (str): The current task name, used to name the corresponding .yaml and .json cache files.
        config (DictConfig): The configuration object to be saved, typically constructed using OmegaConf.
        messages (List[Message]): A list of Message instances representing the conversation history. Each message must
                                  support the `to_dict()` method for serialization.

    Returns:
        None: No return value. The result of the operation is the writing of cache files to disk.

    Raises:
        OSError: If there are issues creating directories or writing files (e.g., permission errors).
        TypeError / ValueError: If the config or messages cannot be serialized properly.
        AttributeError: If any message in the list does not implement the `to_dict()` method.
    """
    cache_dir = os.path.join(output_dir, 'memory')
    os.makedirs(cache_dir, exist_ok=True)
    config_file = os.path.join(cache_dir, f'{task}.yaml')
    message_file = os.path.join(cache_dir, f'{task}.json')
    with open(config_file, 'w') as f:
        OmegaConf.save(config, f)
    with open(message_file, 'w') as f:
        json.dump([message.to_dict() for message in messages], f)


def read_history(output_dir: str, task: str):
    """
    Reads configuration information and conversation history associated with the given task from the cache directory.

    This function attempts to locate cached files using a subdirectory under `<output_dir>/memory`. It then tries
    to load two files:
        - `<task>.yaml`: A YAML-formatted configuration file.
        - `<task>.json`: A JSON-formatted list of Message objects.

    If either file does not exist, the corresponding return value will be `None`. The configuration object is
    enhanced by filling in any missing default fields before being returned. The message list is deserialized into
    actual `Message` instances.

    Args:
        output_dir (str): Base directory where the cache folder is located.
        task (str): The current task name, used to match the corresponding `.yaml` and `.json` cache files.

    Returns:
        Tuple[Optional[Config], Optional[List[Message]]]: A tuple containing:
            - Config object or None: Loaded and optionally enriched configuration.
            - List of Message instances or None: Deserialized conversation history.

    Raises:
        FileNotFoundError: If the expected cache directory exists but required files cannot be found.
        json.JSONDecodeError: If the JSON file contains invalid syntax.
        omegaconf.errors.ConfigValidationError: If the loaded YAML config has incorrect structure.
        TypeError / AttributeError: If the deserialized JSON data lacks expected keys or structure for Message
                                    objects.
    """
    from ms_agent.llm import Message
    from ms_agent.config import Config
    cache_dir = os.path.join(output_dir, 'memory')
    os.makedirs(cache_dir, exist_ok=True)
    config_file = os.path.join(cache_dir, f'{task}.yaml')
    message_file = os.path.join(cache_dir, f'{task}.json')
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
    Parses an input string into a JSON object. Supports standard JSON and some non-standard formats
    (e.g., JSON with comments), falling back to json5 for lenient parsing when necessary.

    This function automatically strips leading and trailing newline characters and attempts to remove possible Markdown
    code block delimiters (```json ... \n```). It first tries to parse the string using the standard json module. If
    that fails, it uses the json5 module for more permissive parsing.

    Args:
        text (str): The JSON string to be parsed, which may be wrapped in a Markdown code block or contain formatting
                    issues.

    Returns:
        dict: The parsed Python dictionary object.

    Raises:
        json.decoder.JSONDecodeError: If the string cannot be parsed into valid JSON after all attempts, a standard
                                      JSON decoding error is raised.
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
    Removes all <resource_info>...</resource_info> tags and their enclosed content from the given text.

    Args:
        text (str): The original text to be processed.

    Returns:
        str: The text with <resource_info> tags and their contents removed.
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


def load_image_from_uri_to_pil(uri: str) -> tuple:
    """
    Load image from URI as a PIL Image object and extract its format extension.
    URI format: data:[<mime>][;base64],<encoded>

    Args:
        uri (str): The image data URI

    Returns:
        tuple: (PIL Image object, file extension string) or None if failed
    """
    from PIL import Image
    try:
        header, encoded = uri.split(',', 1)
        if ';base64' in header:
            raw = base64.b64decode(encoded)
        else:
            raw = encoded.encode('utf-8')
        m = re.match(r'data:(image/[^;]+)', header)
        ext = m.group(1).split('/')[-1] if m else 'bin'
        img = Image.open(BytesIO(raw))
        return img, ext
    except ValueError as e:
        print(f'Error parsing URI format: {e}')
        return None
    except base64.binascii.Error as e:
        print(f'Error decoding base64 data: {e}')
        return None
    except IOError as e:
        print(f'Error opening image: {e}')
        return None
    except Exception as e:
        print(f'Unexpected error loading image from URI: {e}')
        return None


def validate_url(
        img_url: str,
        backend: 'docling.backend.html_backend.HTMLDocumentBackend') -> str:
    """
    Validates and resolves a relative image URL using the base URL from the HTML document's metadata.

    This function attempts to resolve relative image URLs by looking for base URLs in the following order:
    1. <base href="..."> tag
    2. <link rel="canonical" href="..."> tag
    3. <meta property="og:url" content="..."> tag

    Args:
        img_url (str): The image URL to validate/resolve
        backend (HTMLDocumentBackend): The HTML document backend containing the parsed document

    Returns:
        str: The resolved absolute URL if successful, None otherwise
    """
    from urllib.parse import urljoin, urlparse

    # Check if we have a valid soup object in the backend
    if not backend or not hasattr(
            backend, 'soup') or not backend.soup or not backend.soup.head:
        return None

    # Potential sources of base URLs to try
    base_url = None
    sources = [
        # Try base tag
        lambda: backend.soup.head.find('base', href=True)['href']
        if backend.soup.head.find('base', href=True) else None,
        # Try canonical link
        lambda: backend.soup.head.find('link', rel='canonical', href=True)[
            'href'] if backend.soup.head.find(
                'link', rel='canonical', href=True) else None,
        # Try OG URL meta tag
        lambda: backend.soup.head.find(
            'meta', property='og:url', content=True)['content'] if backend.soup
        .head.find('meta', property='og:url', content=True) else None
    ]

    # Try each source until we find a valid base URL
    for source_fn in sources:
        try:
            base_url = source_fn()
            if base_url:
                valid_url = urljoin(base_url, img_url)
                return valid_url
        except Exception as e:
            print(f'Error resolving base URL: {e}')
            continue  # Silently try the next source

    # No valid base URL found
    return img_url
