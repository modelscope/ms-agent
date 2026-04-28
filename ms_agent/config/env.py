# Copyright (c) ModelScope Contributors. All rights reserved.
import os
from copy import copy
from typing import Dict, Optional

from dotenv import load_dotenv


class Env:

    @staticmethod
    def load_dotenv_into_environ(dotenv_path: Optional[str] = None) -> None:
        """Load key=value pairs from a .env file into ``os.environ``.

        Does not override variables already set in the process environment.

        If ``dotenv_path`` is given, loads that file; it must exist.
        If ``dotenv_path`` is None, loads ``<cwd>/.env`` when that file exists;
        a missing default file is a no-op.
        """
        if dotenv_path is not None:
            path = os.path.abspath(os.path.expanduser(dotenv_path))
            if not os.path.isfile(path):
                raise FileNotFoundError(f'Env file not found: {path}')
            load_dotenv(path, override=False)
        else:
            default = os.path.join(os.getcwd(), '.env')
            if os.path.isfile(default):
                load_dotenv(default, override=False)

    @staticmethod
    def load_env(envs: Dict[str, str] = None,
                 dotenv_path: Optional[str] = None) -> Dict[str, str]:
        """Load .env into the process env, then merge with ``envs`` and return."""
        Env.load_dotenv_into_environ(dotenv_path)
        _envs = copy(os.environ)
        _envs.update(envs or {})
        return _envs
