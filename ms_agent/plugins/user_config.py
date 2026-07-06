"""userConfig schema validation and persistence for plugin data dirs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ALLOWED_TYPES = frozenset({'string', 'boolean', 'number', 'integer', 'array', 'object'})


class UserConfigError(ValueError):
    """Raised when userConfig schema or values are invalid."""


def validate_schema(schema: dict[str, Any]) -> list[str]:
    """Validate manifest ``userConfig`` field definitions."""
    errors: list[str] = []
    if not isinstance(schema, dict):
        return ['userConfig must be an object']
    for key, field in schema.items():
        if not isinstance(key, str) or not key.strip():
            errors.append('userConfig keys must be non-empty strings')
            continue
        if not isinstance(field, dict):
            errors.append(f'userConfig.{key} must be an object')
            continue
        field_type = field.get('type')
        if field_type not in _ALLOWED_TYPES:
            errors.append(
                f'userConfig.{key}.type must be one of {sorted(_ALLOWED_TYPES)}')
    return errors


def validate_values(
    schema: dict[str, Any],
    values: dict[str, Any],
) -> list[str]:
    """Validate submitted config values against a userConfig schema."""
    errors = validate_schema(schema)
    if errors:
        return errors
    if not isinstance(values, dict):
        return ['config values must be an object']
    for key, field in schema.items():
        if key not in values:
            if field.get('required'):
                errors.append(f'Missing required userConfig field: {key}')
            continue
        value = values[key]
        field_type = field.get('type')
        if field_type == 'string' and not isinstance(value, str):
            errors.append(f'userConfig.{key} must be a string')
        elif field_type == 'boolean' and not isinstance(value, bool):
            errors.append(f'userConfig.{key} must be a boolean')
        elif field_type in {'number', 'integer'} and not isinstance(value, (int, float)):
            errors.append(f'userConfig.{key} must be a number')
        elif field_type == 'array' and not isinstance(value, list):
            errors.append(f'userConfig.{key} must be an array')
        elif field_type == 'object' and not isinstance(value, dict):
            errors.append(f'userConfig.{key} must be an object')
    for key in values:
        if key not in schema:
            errors.append(f'Unknown userConfig field: {key}')
    return errors


def load_user_config(data_dir: str | Path) -> dict[str, Any]:
    path = Path(data_dir) / 'config.json'
    if not path.is_file():
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_user_config(
    data_dir: str | Path,
    schema: dict[str, Any],
    values: dict[str, Any],
) -> dict[str, Any]:
    errors = validate_values(schema, values)
    if errors:
        raise UserConfigError('; '.join(errors))
    path = Path(data_dir)
    path.mkdir(parents=True, exist_ok=True)
    config_path = path / 'config.json'
    tmp = config_path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(values, f, indent=2, ensure_ascii=False)
    tmp.rename(config_path)
    return values


def default_values(schema: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, field in schema.items():
        if not isinstance(field, dict):
            continue
        if 'default' in field:
            values[key] = field['default']
    return values
