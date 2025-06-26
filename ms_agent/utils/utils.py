# Copyright (c) Alibaba, Inc. and its affiliates.
import hashlib
import importlib
import os.path
from typing import List, Optional

import json
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
