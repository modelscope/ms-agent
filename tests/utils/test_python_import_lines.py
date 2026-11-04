# Copyright (c) ModelScope Contributors. All rights reserved.
"""Project imports must not consume subsequent Python statements."""
import ast

import pytest
from ms_agent.utils.parser_utils import parse_imports


@pytest.fixture
def project(tmp_path):
    for name in ('first_module.py', 'second_module.py', 'main.py'):
        (tmp_path / name).touch()
    return tmp_path


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
@pytest.mark.parametrize('lines, expected', [
    (['import first_module', 'import second_module'],
     {'first_module.py': ('first_module', None),
      'second_module.py': ('second_module', None)}),
    (['import first_module as first', 'import second_module as second'],
     {'first_module.py': ('first_module', 'first'),
      'second_module.py': ('second_module', 'second')}),
    (['import first_module', 'from second_module import helper'],
     {'first_module.py': ('first_module', None),
      'second_module.py': ('helper', None)}),
    (['import first_module', '', 'first_module.run()'],
     {'first_module.py': ('first_module', None)}),
])
def test_import_stops_at_line_end(project, newline, lines, expected):
    content = newline.join(lines) + newline
    ast.parse(content)

    imports = parse_imports(str(project / 'main.py'), content, str(project))

    assert len(imports) == len(expected)
    assert {item.source_file: (item.imported_items[0], item.alias)
            for item in imports} == expected


@pytest.mark.parametrize('whitespace', [' ', '\t', '\f'])
def test_comma_separated_imports_keep_aliases(project, whitespace):
    content = f'import{whitespace}first_module as first, second_module as second'
    ast.parse(content)

    imports = parse_imports(str(project / 'main.py'), content, str(project))

    assert [(item.source_file, item.imported_items, item.alias)
            for item in imports] == [
                ('first_module.py', ['first_module'], 'first'),
                ('second_module.py', ['second_module'], 'second'),
            ]
