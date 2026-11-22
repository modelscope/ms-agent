# Copyright (c) ModelScope Contributors. All rights reserved.
"""Field encryption for managed configuration and runtime snapshots.

Persistence keeps ciphertext. Only credential consumers decrypt it. The
instance key lives beside, rather than inside, the SDK home by default.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from ms_agent.utils.atomic_file import atomic_write_json, atomic_write_text
from ms_agent.utils.file_lock import file_lock

PREFIX = 'enc:v1:'
HOME_FIELD = '_secret_home'
SECRET_ENV_VARS = frozenset(
    {'MS_AGENT_SECRET_KEY', 'MS_AGENT_SECRET_KEY_FILE'})
_FIELDS = {
    'providers.*.api_key',
    'llm.api_key',
    'llm.*_api_key',
    'llm.vision.api_key',
    'tools.web_search.api_key',
    'tools.web_search.exa_api_key',
    'tools.web_search.exa_api_keys',
    'tools.web_search.tavily_api_key',
    'tools.web_search.serpapi_api_key',
    'tools.web_search.summarizer_api_key',
    'memory.*.llm.config.api_key',
    'memory.*.embedder.config.api_key',
    'memory.*.config.llm.config.api_key',
    'memory.*.config.embedder.config.api_key',
    'memory.*.mem0.llm.config.api_key',
    'memory.*.mem0.embedder.config.api_key',
}


class SecretError(ValueError):
    """A safe diagnostic: never include a credential, key or ciphertext."""


class SecretInputError(SecretError):
    pass


def register_secret_field(path: str) -> None:
    """Register a dotted config path; its consumer must also use resolve_secret."""
    if not path or any(not part for part in path.split('.')):
        raise ValueError('A nonempty dotted secret field path is required')
    _FIELDS.add(path)


def secret_home(config: Any = None, home: str | Path | None = None) -> Path:
    if home is None and config is not None:
        home = config.get(HOME_FIELD) if hasattr(config, 'get') else None
    if home is None:
        from ms_agent.project.paths import global_home
        home = global_home()
    return Path(home).expanduser().resolve()


def _plain_config(config: Any) -> Any:
    from omegaconf import OmegaConf
    if OmegaConf.is_config(config):
        return OmegaConf.to_container(config, resolve=False)
    return copy.deepcopy(config)


def _leaves(value: Any, path: tuple[str, ...] = ()):
    if isinstance(value, dict):
        for key, child in value.items():
            parts = path + (str(key), )
            if any(
                    len(pattern.split('.')) == len(parts) and all(
                        fnmatchcase(part, token)
                        for part, token in zip(parts, pattern.split('.')))
                    for pattern in _FIELDS):
                yield value, key
            else:
                yield from _leaves(child, parts)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaves(child, path + (str(index), ))


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def contains_ciphertext(config: Any) -> bool:
    data = _plain_config(config)
    return any(
        text.startswith('enc:') for parent, key in _leaves(data)
        for text in _strings(parent[key]))


def _fernet(key: bytes):
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise SecretError('Credential encryption requires cryptography. '
                          'Reinstall or upgrade ms-agent.') from None
    try:
        return Fernet(key)
    except (ValueError, TypeError):
        raise SecretError(
            'The instance master key has an invalid format.') from None


class SecretStore:

    def __init__(self, home: str | Path | None = None):
        self.home = secret_home(home=home)
        if not self.home.name:
            raise SecretError(
                'MS_AGENT_HOME must be a data directory, not a filesystem root.'
            )
        key_env = 'MS_AGENT_SECRET_KEY' in os.environ
        file_env = 'MS_AGENT_SECRET_KEY_FILE' in os.environ
        if key_env and file_env:
            raise SecretError(
                'Set only one of MS_AGENT_SECRET_KEY and MS_AGENT_SECRET_KEY_FILE.'
            )
        self.external = key_env or file_env
        self.key_value = os.environ.get(
            'MS_AGENT_SECRET_KEY') if key_env else None
        self.key_file = (
            Path(
                os.environ['MS_AGENT_SECRET_KEY_FILE']).expanduser().resolve()
            if file_env and os.environ['MS_AGENT_SECRET_KEY_FILE'] else
            self.home.parent / (self.home.name + '.secrets') / 'master.key')
        if (key_env and not self.key_value) or (
                file_env and not os.environ['MS_AGENT_SECRET_KEY_FILE']):
            raise SecretError(
                'The explicitly configured instance master key is empty.')

    def _global_has_ciphertext(self) -> bool:
        try:
            path = self.home / 'settings.json'
            if path.is_file() and contains_ciphertext(_read_file(path)):
                return True
            for project in _known_projects(self.home):
                if any(
                        contains_ciphertext(_read_file(path))
                        for path in project_secret_files(project)):
                    return True
            return False
        except (OSError, ValueError):
            raise SecretError(
                'Cannot inspect existing credential storage; repair settings.json first.'
            ) from None

    def _read_key(self) -> bytes:
        if self.key_value is not None:
            try:
                key = self.key_value.encode('ascii', errors='strict')
            except UnicodeError:
                raise SecretError(
                    'The instance master key has an invalid format.') from None
        else:
            try:
                if not self.external and (self.key_file.is_symlink() or
                                          self.key_file.parent.is_symlink()):
                    raise SecretError(
                        'The default master key must not be a symbolic link.')
                key = self.key_file.read_bytes()
            except OSError:
                raise SecretError(
                    'The instance master key is missing or unreadable. '
                    'Restore the original key, or explicitly reset managed credentials.'
                ) from None
        _fernet(key)
        return key

    def _key(self,
             *,
             create: bool = False,
             existing_ciphertext: bool = False) -> bytes:
        if not self.external and (self.key_file.is_symlink()
                                  or self.key_file.parent.is_symlink()):
            raise SecretError(
                'The default master key must not be a symbolic link.')
        if self.external or self.key_file.exists():
            return self._read_key()
        if not create:
            return self._read_key()
        if existing_ciphertext or self._global_has_ciphertext():
            raise SecretError(
                'Existing encrypted credentials have no instance master key. '
                'Restore the original key, or explicitly reset managed credentials.'
            )
        try:
            directory = self.key_file.parent
            if directory.is_symlink():
                raise SecretError(
                    'The default master key directory must not be a symbolic link.'
                )
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name != 'nt':
                directory.chmod(0o700)
            with file_lock(self.key_file):
                if self.key_file.exists():
                    return self._read_key()
                from cryptography.fernet import Fernet
                key = Fernet.generate_key()
                fd, temporary = tempfile.mkstemp(
                    dir=directory, prefix='.master.', suffix='.tmp')
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(key)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, self.key_file)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
                return self._read_key()
        except OSError:
            raise SecretError(
                'Cannot create the independent master key directory. '
                'Set MS_AGENT_SECRET_KEY_FILE to a persistent key file.'
            ) from None

    def encrypt(self, value: str, *, existing_ciphertext: bool = False) -> str:
        if not value:
            return value
        if value.startswith('enc:'):
            self._validate_envelope(value)
            return value
        key = self._key(create=True, existing_ciphertext=existing_ciphertext)
        return PREFIX + _fernet(key).encrypt(
            value.encode('utf-8')).decode('ascii')

    @staticmethod
    def _validate_envelope(value: str) -> None:
        if not value.startswith(PREFIX) or not value[len(PREFIX):]:
            raise SecretError(
                'The encrypted credential format is invalid or unsupported.')

    def decrypt(self, value: str) -> str:
        if not value or not value.startswith('enc:'):
            return value
        self._validate_envelope(value)
        box = _fernet(self._key())
        try:
            from cryptography.fernet import InvalidToken
            return box.decrypt(
                value[len(PREFIX):].encode('ascii')).decode('utf-8')
        except (InvalidToken, UnicodeError, ValueError) as exc:
            if isinstance(exc, SecretError):
                raise
            raise SecretError(
                'This credential cannot be decrypted with the instance master key. '
                'Restore the original key or replace this credential.'
            ) from None

    def view(self, value: str | None) -> tuple[str, str]:
        if not value:
            return 'unset', ''
        if not isinstance(value, str):
            return 'unavailable', ''
        try:
            plain = self.decrypt(value)
        except SecretError:
            return 'unavailable', ''
        masked = '****' if len(plain) <= 8 else f'{plain[:4]}****{plain[-4:]}'
        return 'configured', masked

    def fingerprint(self) -> str:
        import hashlib
        try:
            return hashlib.sha256(self._read_key()).hexdigest()
        except SecretError:
            return 'unavailable'


def resolve_secret(value: Any,
                   *,
                   config: Any = None,
                   home: str | Path | None = None) -> Any:
    from omegaconf import ListConfig
    if isinstance(value, (list, ListConfig)):
        return [
            resolve_secret(item, config=config, home=home) for item in value
        ]
    if value is not None and not isinstance(value, str):
        raise SecretError(
            'A credential must be a string or a list of strings.')
    if value is None or not value.startswith('enc:'):
        return value
    return SecretStore(secret_home(config, home)).decrypt(value)


def credential_view(value: Any,
                    *,
                    home: str | Path | None = None) -> tuple[str, str]:
    if not value:
        return 'unset', ''
    try:
        return SecretStore(home).view(value)
    except SecretError:
        return 'unavailable', ''


def master_fingerprint(home: str | Path | None = None) -> str:
    try:
        return SecretStore(home).fingerprint()
    except SecretError:
        return 'unavailable'


def protect_config(config: Any,
                   *,
                   home: str | Path | None = None,
                   existing_ciphertext: bool = False) -> Any:
    directory = secret_home(config, home)
    data = _plain_config(config)
    store = SecretStore(directory)
    has_ciphertext = existing_ciphertext or contains_ciphertext(data)
    for parent, key in _leaves(data):
        value = parent[key]
        if isinstance(value, str):
            # Environment/config references contain no literal credential;
            # retain their existing runtime resolution semantics.
            if not value.startswith('enc:') and not (value.startswith('${')
                                                     and value.endswith('}')):
                parent[key] = store.encrypt(
                    value, existing_ciphertext=has_ciphertext)
        elif isinstance(value, list):
            if any(
                    item is not None and not isinstance(item, str)
                    for item in value):
                raise SecretError(
                    'Sensitive config fields must contain strings, not nested objects.'
                )
            parent[key] = [
                store.encrypt(item, existing_ciphertext=has_ciphertext)
                if isinstance(item, str) and not item.startswith('enc:')
                and not (item.startswith('${') and item.endswith('}')) else
                item for item in value
            ]
        elif value is not None:
            raise SecretError(
                'Sensitive config fields must be strings or lists of strings.')
    if isinstance(data, dict):
        data.pop(HOME_FIELD, None)
    return data


def resolve_config_secrets(config: Any,
                           *,
                           home: str | Path | None = None) -> Any:
    """Resolve a selected consumer's config copy, never a persistence object."""
    data = _plain_config(config)
    directory = secret_home(config, home)
    for parent, key in _leaves(data):
        parent[key] = resolve_secret(parent[key], home=directory)
    return data


def clear_secrets(config: Any) -> Any:
    data = _plain_config(config)
    for parent, key in _leaves(data):
        parent[key] = [] if isinstance(parent[key], list) else ''
    if isinstance(data, dict):
        data.pop(HOME_FIELD, None)
    return data


def write_managed_config(path: str | Path,
                         config: Any,
                         *,
                         home: str | Path | None = None) -> None:
    path = Path(path)
    with file_lock(path):
        old = _read_file(path) if path.exists() else {}
        protected = protect_config(
            config, home=home, existing_ciphertext=contains_ciphertext(old))
        _write_file(path, protected)


def _read_file(path: Path) -> Any:
    from omegaconf import OmegaConf
    from omegaconf.errors import OmegaConfBaseException
    from yaml import YAMLError
    try:
        if path.suffix == '.json':
            return json.loads(path.read_text(encoding='utf-8'))
        return OmegaConf.to_container(OmegaConf.load(path), resolve=False)
    except (ValueError, UnicodeError, YAMLError, OmegaConfBaseException):
        raise SecretError(
            'Cannot parse a managed configuration file. '
            'Repair its JSON/YAML before writing credentials.') from None


def _write_file(path: Path, data: Any) -> None:
    if path.suffix == '.json':
        atomic_write_json(path, data, fsync=True)
    else:
        from omegaconf import OmegaConf
        atomic_write_text(
            path, OmegaConf.to_yaml(OmegaConf.create(data)), fsync=True)


def migrate_file(path: str | Path, *, home: str | Path | None = None) -> bool:
    path = Path(path)
    if not path.is_file():
        return False
    with file_lock(path):
        old = _read_file(path)
        values = [
            text for parent, key in _leaves(old)
            for text in _strings(parent[key])
        ]
        if any(
                text and not text.startswith(('enc:', '${'))
                for text in values):
            store = SecretStore(secret_home(home=home))
            for text in values:
                if text.startswith('enc:'):
                    store.decrypt(text)
        protected = protect_config(old, home=home)
        if protected == old:
            return False
        _write_file(path, protected)
        return True


def project_secret_files(project: str | Path) -> list[Path]:
    project = Path(project).expanduser().resolve()
    paths = []
    for name in ('.ms_agent', '.ms-agent'):
        directory = project / name
        paths.extend(directory / name
                     for name in ('config.yaml', 'settings.local.json'))
        paths.extend(sorted((directory / 'memory').glob('*.yaml')))
    paths.extend(sorted((project / '.memory').glob('*.yaml')))
    return [path for path in paths if path.is_file()]


def migrate_project(project: str | Path,
                    *,
                    home: str | Path | None = None) -> None:
    for path in project_secret_files(project):
        migrate_file(path, home=home)


def _known_projects(home: Path) -> list[str]:
    from ms_agent.project.manager import ProjectManager
    return [
        project.path
        for project in ProjectManager(str(home), auto_initialize=False).list()
    ]


def migrate_home(home: str | Path | None = None) -> None:
    """Migrate all registered projects, including ones not opened this boot."""
    directory = secret_home(home=home)
    paths = [directory / 'settings.json']
    for project in _known_projects(directory):
        paths.extend(project_secret_files(project))
    failed = 0
    for path in paths:
        try:
            migrate_file(path, home=directory)
        except (SecretError, OSError):
            failed += 1
    if failed:
        raise SecretError(
            f'Credential migration is incomplete in {failed} managed file(s). '
            'Restore the master key or repair the affected configuration before sharing.'
        )


def reset_credentials(home: str | Path | None = None,
                      *,
                      projects=(),
                      confirm: bool = False) -> list[str]:
    """Explicitly discard managed credentials; keep definitions and messages.

    The original master key is never replaced. If it was lost, clearing the
    selected files permits a subsequent first credential write to initialize
    a new local key. External key configuration must still be repaired.
    """
    if not confirm:
        raise SecretError(
            'Resetting credentials requires explicit confirmation.')
    directory = secret_home(home=home)
    paths = [directory / 'settings.json']
    for project in dict.fromkeys([*_known_projects(directory), *projects]):
        paths.extend(project_secret_files(project))
    changed = []
    for path in dict.fromkeys(paths):
        if not path.is_file():
            continue
        with file_lock(path):
            old = _read_file(path)
            cleaned = clear_secrets(old)
            if old != cleaned:
                _write_file(path, cleaned)
                changed.append(str(path))
    return changed


def subprocess_env(env: dict[str, str] | None = None) -> dict[str, str]:
    return {
        key: value
        for key, value in (os.environ if env is None else env).items()
        if key not in SECRET_ENV_VARS
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=
        'Explicitly clear managed credentials before reconfiguration.')
    parser.add_argument('action', choices=['reset'])
    parser.add_argument('--home')
    parser.add_argument('--project', action='append', default=[])
    parser.add_argument(
        '--confirm',
        action='store_true',
        help='Discard the selected saved credentials')
    args = parser.parse_args()
    paths = reset_credentials(
        args.home, projects=args.project, confirm=args.confirm)
    print(
        f'Cleared managed credentials in {len(paths)} file(s). Definitions and messages were retained.'
    )


if __name__ == '__main__':
    main()
