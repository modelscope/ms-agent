"""Reconciling model-emitted JSON with a tool's declared schema.

The rule throughout: rewrite only where the reading cannot change. Anything
ambiguous is left for the tool to judge on its own terms.
"""
import pytest

from ms_agent.tools.arg_coercion import coerce_arguments

NUMERIC = {
    'type': 'object',
    'properties': {
        'a': {
            'anyOf': [{
                'type': 'number'
            }, {
                'type': 'integer'
            }]
        },
        'b': {
            'type': 'integer'
        },
        'flag': {
            'type': 'boolean'
        },
        'name': {
            'type': 'string'
        },
    },
}


@pytest.mark.parametrize('given, expected', [
    ({'a': '19.5'}, {'a': 19.5}),
    ({'b': '2'}, {'b': 2}),
    ({'flag': 'true'}, {'flag': True}),
])
def test_quoted_scalars_are_unquoted_to_match_the_schema(given, expected):
    assert coerce_arguments(given, NUMERIC) == expected


@pytest.mark.parametrize('given', [
    {'name': '19.5'},          # schema says string: the quotes ARE the value
    {'a': 'nineteen'},         # not a number in any reading
    {'a': ''},
    {'unknown': '5'},          # not in the schema; nothing is claimed about it
])
def test_ambiguous_values_are_left_alone(given):
    assert coerce_arguments(given, NUMERIC) == given


def test_unchanged_arguments_are_returned_by_identity():
    args = {'name': 'x', 'a': 1}
    assert coerce_arguments(args, NUMERIC) is args


def test_booleans_are_not_read_as_numbers():
    schema = {'type': 'object', 'properties': {'n': {'type': 'integer'}}}
    assert coerce_arguments({'n': True}, schema) == {'n': True}


def test_structured_text_is_parsed_and_walked():
    schema = {
        'type': 'object',
        'properties': {
            'items': {
                'type': 'array',
                'items': {
                    'type': 'integer'
                }
            },
            'cfg': {
                'type': 'object',
                'properties': {
                    'depth': {
                        'type': 'integer'
                    }
                },
            },
        },
    }
    given = {'items': '["1", "2"]', 'cfg': {'depth': '3'}}
    assert coerce_arguments(given, schema) == {
        'items': [1, 2],
        'cfg': {
            'depth': 3
        },
    }


def test_int_widens_only_where_integer_is_not_accepted():
    schema = {
        'type': 'object',
        'properties': {
            'only_float': {
                'type': 'number'
            },
            'either': {
                'type': ['number', 'integer']
            },
        },
    }
    out = coerce_arguments({'only_float': 3, 'either': 3}, schema)
    assert isinstance(out['only_float'], float)
    assert isinstance(out['either'], int)


@pytest.mark.parametrize('schema', [None, 'nonsense'])
def test_a_missing_or_broken_schema_is_not_an_error(schema):
    args = {'a': '1'}
    assert coerce_arguments(args, schema) is args
