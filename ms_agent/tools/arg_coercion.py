# Copyright (c) ModelScope Contributors. All rights reserved.
"""Reconcile the JSON a model emitted with the JSON a tool's schema asks for.

Models routinely quote scalars — ``{"a": "19.5"}`` where the schema says
``number`` — and a tool validating strictly (Pydantic ``StrictFloat``, say)
rejects that. The model cannot see why: it gets a validator's internal
complaint, tries again, and produces the same quoting, so the round repeats
until something gives up.

Only rewrites that cannot change meaning are made. ``"19.5"`` is 19.5 in every
reading; ``"nineteen"`` is left exactly as it is, for the tool to refuse on its
own terms. Where the schema says ``string``, nothing is touched at all — the
quotes are the answer there.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

__all__ = ['coerce_arguments']

_TRUE = frozenset({'true', 'True', 'TRUE', 'yes', 'on', '1'})
_FALSE = frozenset({'false', 'False', 'FALSE', 'no', 'off', '0'})


def _schema_types(schema: Any) -> set:
    """The JSON Schema types a value may take, flattened across combinators."""
    if not isinstance(schema, dict):
        return set()
    out: set = set()
    declared = schema.get('type')
    if isinstance(declared, str):
        out.add(declared)
    elif isinstance(declared, list):
        out.update(t for t in declared if isinstance(t, str))
    for key in ('anyOf', 'oneOf', 'allOf'):
        for branch in schema.get(key) or ():
            out |= _schema_types(branch)
    return out


def _to_number(text: str, types: set) -> Any:
    stripped = text.strip()
    if not stripped:
        return None
    if 'integer' in types:
        try:
            return int(stripped, 10)
        except ValueError:
            pass
    if 'number' in types:
        try:
            value = float(stripped)
        except ValueError:
            return None
        # An integer-valued float where the schema also allows int keeps the
        # narrower type, which is what a StrictInt branch is waiting for.
        if 'integer' in types and value.is_integer():
            return int(value)
        return value
    return None


def _coerce_value(value: Any, schema: Any) -> Any:
    types = _schema_types(schema)
    if not types:
        return value

    if isinstance(value, str):
        # A schema that accepts a string means the string IS the answer.
        if 'string' in types:
            return value
        if {'number', 'integer'} & types:
            number = _to_number(value, types)
            if number is not None:
                return number
        if 'boolean' in types:
            token = value.strip()
            if token in _TRUE:
                return True
            if token in _FALSE:
                return False
        if 'null' in types and value.strip() in ('null', 'None', ''):
            return None
        if {'object', 'array'} & types:
            # Some models serialize a whole nested argument as JSON text.
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                return value
            if isinstance(parsed, dict) and 'object' in types:
                return _coerce_value(parsed, schema)
            if isinstance(parsed, list) and 'array' in types:
                return _coerce_value(parsed, schema)
        return value

    if isinstance(value, dict) and 'object' in types:
        properties = schema.get('properties') if isinstance(schema,
                                                            dict) else None
        if not isinstance(properties, dict):
            for key in ('anyOf', 'oneOf', 'allOf'):
                for branch in (schema.get(key) or ()) if isinstance(
                        schema, dict) else ():
                    if isinstance(branch, dict) and isinstance(
                            branch.get('properties'), dict):
                        properties = branch['properties']
                        break
                if properties:
                    break
        if isinstance(properties, dict):
            return {
                k: (_coerce_value(v, properties[k]) if k in properties else v)
                for k, v in value.items()
            }
        return value

    if isinstance(value, list) and 'array' in types:
        items = schema.get('items') if isinstance(schema, dict) else None
        if isinstance(items, dict):
            return [_coerce_value(item, items) for item in value]
        return value

    # An int where the schema wants a float is already valid JSON-schema-wise,
    # but a StrictFloat branch disagrees; widen only when int is not accepted.
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and 'number' in types and 'integer' not in types:
        return float(value)
    return value


def coerce_arguments(
    arguments: Dict[str, Any],
    schema: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return ``arguments`` with values reshaped to fit ``schema``.

    Returns the original object when there is nothing to do, so callers can
    tell "unchanged" by identity. A malformed schema is not an error — it just
    means no rewriting is possible.
    """
    if not isinstance(arguments, dict) or not arguments:
        return arguments
    if not isinstance(schema, dict):
        return arguments
    properties = schema.get('properties')
    if not isinstance(properties, dict):
        return arguments

    out: Dict[str, Any] = {}
    changed = False
    for key, value in arguments.items():
        if key in properties:
            new_value = _coerce_value(value, properties[key])
            if new_value is not value and new_value != value:
                changed = True
            elif type(new_value) is not type(value):
                changed = True
            out[key] = new_value
        else:
            out[key] = value
    return out if changed else arguments
