# Copyright (c) Alibaba, Inc. and its affiliates.
import os.path
from copy import copy
from typing import Dict

from dotenv import load_dotenv


class Env:

    @staticmethod
    def load_env(envs: Dict[str, str] = None) -> Dict[str, str]:
        """Load environment variables from .env file and merges with the input envs"""
        load_dotenv()
        _envs = copy(os.environ)
        _envs.update(envs or {})
        return _envs
