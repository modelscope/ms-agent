import os
import shutil
import tempfile
import unittest
from pathlib import Path

from ms_agent.utils.parser_utils import parse_imports


class TestPythonExternalPackageFiltering(unittest.TestCase):
    """Test that Python external packages are filtered out"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, 'test.py')
        Path(self.test_file).touch()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stdlib_filtered(self):
        """Test that stdlib imports are filtered out"""
        content = 'from typing import List, Dict'
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_import_os_filtered(self):
        """Test that 'import os' is filtered out"""
        content = 'import os'
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_import_with_alias_filtered(self):
        """Test that 'import numpy as np' is filtered out"""
        content = 'import numpy as np'
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_import_star_filtered(self):
        """Test that 'from typing import *' is filtered out"""
        content = 'from typing import *'
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_multiple_imports_filtered(self):
        """Test that 'import os, sys, json' are all filtered out"""
        content = 'import os, sys, json'
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_multiline_import_filtered(self):
        """Test that multiline external imports are filtered out"""
        content = '''
from typing import (
    List,
    Dict,
    Optional
)
'''
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_future_imports_filtered(self):
        """Test that __future__ imports are filtered out"""
        content = '''
from __future__ import annotations
from __future__ import division, print_function
'''
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)


class TestPythonProjectFileImports(unittest.TestCase):
    """Test that Python project files (relative imports) are kept"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        # Create package structure
        self.pkg_dir = os.path.join(self.temp_dir, 'mypackage')
        os.makedirs(self.pkg_dir)
        Path(os.path.join(self.pkg_dir, '__init__.py')).touch()

        self.test_file = os.path.join(self.pkg_dir, 'test.py')
        Path(self.test_file).touch()

        # Create utils module
        utils_file = os.path.join(self.pkg_dir, 'utils.py')
        Path(utils_file).touch()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_relative_import_single_dot(self):
        """Test that relative imports with . are kept"""
        content = 'from .utils import helper'
        imports = parse_imports(self.test_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0].import_type, 'named')
        self.assertIn('helper', imports[0].imported_items)

    def test_relative_import_double_dot(self):
        """Test that relative imports with .. are kept"""
        content = 'from ..config import settings'
        pkg_dir = os.path.join(self.temp_dir, 'config')
        os.makedirs(pkg_dir)
        Path(os.path.join(pkg_dir, '__init__.py')).touch()
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 1)
        self.assertIn('settings', imports[0].imported_items)
        self.assertEqual(imports[0].source_file, 'config/__init__.py')

    def test_relative_import_another_package(self):
        """Test that relative imports with .. are kept"""
        content = 'from ..config import settings'

        imports = parse_imports(self.test_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)
        self.assertIn('settings', imports[0].imported_items)
        self.assertEqual(imports[0].source_file, 'config.py')

    def test_relative_import_module(self):
        """Test that 'from . import module' is kept"""
        content = 'from . import utils'
        imports = parse_imports(self.test_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)
        self.assertIn('utils', imports[0].imported_items)

    def test_relative_import_with_alias(self):
        """Test that relative imports with alias are kept"""
        content = 'from .utils import helper as h'
        imports = parse_imports(self.test_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)
        self.assertIn('helper', imports[0].imported_items)

    def test_relative_output_dir_no_excessive_parent_dirs(self):
        """Test that relative output_dir doesn't cause excessive '../' in paths

        This is a regression test for the bug where:
        - output_dir is relative (e.g., './output')
        - current_file is absolute (e.g., /tmp/output/backend/app/api/sessions.py)
        - os.path.relpath(absolute_path, relative_output_dir) uses CWD as base
        - Results in paths like ../../../../../../../../tmp/output/backend/...

        Additionally tests the macOS symlink issue where:
        - /var is a symlink to /private/var
        - os.path.abspath() might return different prefixes
        - os.path.relpath() treats them as completely different paths

        The fix uses os.path.realpath() to resolve symlinks.
        """
        # Create output directory
        output_dir = './output_test'
        try:
            os.makedirs(output_dir)

            # Create directory structure inside output dir: backend/app/api/ and backend/app/models/
            backend_dir = os.path.join(output_dir, 'backend')
            api_dir = os.path.join(backend_dir, 'app', 'api')
            models_dir = os.path.join(backend_dir, 'app', 'models')
            os.makedirs(api_dir)
            os.makedirs(models_dir)

            # Create files inside output directory
            sessions_file = os.path.join(api_dir, 'session.py')
            session_model_file = os.path.join(models_dir, 'session.py')
            Path(sessions_file).touch()
            Path(session_model_file).touch()

            # Import: from ..models.session import SessionCreate
            content = 'from ..models.session import SessionCreate'

            # Parse with output_dir (absolute path)
            imports = parse_imports('backend/app/api/session.py', content,
                                    output_dir)

            self.assertEqual(len(imports), 1)

            source = imports[0].source_file.replace('\\', '/')
            self.assertEqual(source, 'backend/app/models/session.py')

            output_dir = os.path.abspath(output_dir)
            imports = parse_imports('backend/app/api/session.py', content,
                                    output_dir)

            self.assertEqual(len(imports), 1)

            source = imports[0].source_file.replace('\\', '/')
            self.assertEqual(source, 'backend/app/models/session.py')
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)


class TestJavaScriptExternalPackageFiltering(unittest.TestCase):
    """Test that JavaScript/TypeScript external packages are filtered out"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, 'test.ts')
        Path(self.test_file).touch()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_react_filtered(self):
        """Test that 'react' is filtered out"""
        content = "import React from 'react'"
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_react_hooks_filtered(self):
        """Test that react hooks are filtered out"""
        content = "import { useState, useEffect } from 'react'"
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_lodash_filtered(self):
        """Test that 'lodash' is filtered out"""
        content = "import _ from 'lodash'"
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_scoped_package_filtered(self):
        """Test that scoped packages like '@types/react' are filtered out"""
        content = "import { Component } from '@types/react'"
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_vue_filtered(self):
        """Test that '@vue/cli' is filtered out"""
        content = "import { createApp } from '@vue/cli'"
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_import_with_alias_filtered(self):
        """Test that external imports with alias are filtered out"""
        content = "import { useState as state } from 'react'"
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)


class TestJavaScriptProjectFileImports(unittest.TestCase):
    """Test that JavaScript/TypeScript project files are kept"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.src_dir = os.path.join(self.temp_dir, 'src')
        os.makedirs(self.src_dir)

        self.test_file = os.path.join(self.src_dir, 'App.tsx')
        Path(self.test_file).touch()

        # Create component files
        self.button_file = os.path.join(self.src_dir, 'Button.tsx')
        Path(self.button_file).touch()

        self.styles_file = os.path.join(self.src_dir, 'styles.css')
        Path(self.styles_file).touch()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_relative_import_with_extension(self):
        """Test that relative imports with extension are kept"""
        content = "import { Button } from './Button.tsx'"
        imports = parse_imports(self.test_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)
        self.assertIn('Button', imports[0].imported_items)

    def test_default_import(self):
        """Test that default imports from project files are kept"""
        # Create a module file
        utils_file = os.path.join(self.src_dir, 'utils.ts')
        Path(utils_file).touch()

        content = "import utils from './utils'"
        imports = parse_imports(self.test_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0].import_type, 'default')
        self.assertIn('utils', imports[0].imported_items)

    def test_relative_import_without_extension(self):
        """Test that relative imports without extension are kept"""
        content = "import { Button } from './Button'"
        imports = parse_imports(self.test_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)
        self.assertIn('Button', imports[0].imported_items)

    def test_side_effect_import(self):
        """Test that side-effect imports are kept"""
        content = "import './styles.css'"
        imports = parse_imports(self.test_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0].import_type, 'side-effect')

    def test_namespace_import(self):
        """Test that namespace imports are kept"""
        content = "import * as utils from './utils'"
        imports = parse_imports(self.test_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0].import_type, 'namespace')
        self.assertIn('*', imports[0].imported_items)

    def test_type_import(self):
        """Test that type imports are kept"""
        # Create types file
        types_file = os.path.join(self.src_dir, 'types.ts')
        Path(types_file).touch()

        content = "import type { User, Product } from './types'"
        imports = parse_imports(self.test_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)
        self.assertTrue(imports[0].is_type_only)
        self.assertIn('User', imports[0].imported_items)

    def test_inline_type_import(self):
        """Test that inline type imports (TS 4.5+) are correctly parsed"""
        # Create types file
        types_file = os.path.join(self.src_dir, 'types.ts')
        Path(types_file).touch()

        # Test 1: All inline types
        content1 = "import { type User, type Product } from './types'"
        imports1 = parse_imports(self.test_file, content1, self.temp_dir)

        self.assertEqual(len(imports1), 1)
        self.assertFalse(imports1[0].is_type_only)  # Not type-only import
        self.assertEqual(imports1[0].imported_items, ['User', 'Product'])
        # Ensure 'type' keyword is removed
        for item in imports1[0].imported_items:
            self.assertNotIn('type', item)

        # Test 2: Mixed value and type imports
        content2 = "import { Component, type Props } from './types'"
        imports2 = parse_imports(self.test_file, content2, self.temp_dir)

        self.assertEqual(len(imports2), 1)
        self.assertEqual(imports2[0].imported_items, ['Component', 'Props'])
        # Ensure 'type' keyword is removed from Props
        for item in imports2[0].imported_items:
            self.assertNotIn('type', item)

        # Test 3: Inline type with alias
        content3 = "import { type User as U, Component as C } from './types'"
        imports3 = parse_imports(self.test_file, content3, self.temp_dir)

        self.assertEqual(len(imports3), 1)
        self.assertEqual(imports3[0].imported_items, ['User', 'Component'])
        # Ensure extracted original names, not aliases
        for item in imports3[0].imported_items:
            self.assertNotIn('type', item)
            self.assertNotIn('as', item)

    def test_export_from(self):
        """Test that export from statements are kept"""
        # Create components directory
        components_dir = os.path.join(self.src_dir, 'components')
        os.makedirs(components_dir)
        Path(os.path.join(components_dir, 'index.ts')).touch()

        content = "export { Button, Input } from './components'"
        imports = parse_imports(self.test_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)
        self.assertIn('Button', imports[0].imported_items)

    def test_directory_import_with_index(self):
        """Test that directory imports resolve to index file"""
        # Create components directory with index
        components_dir = os.path.join(self.src_dir, 'components')
        os.makedirs(components_dir)
        Path(os.path.join(components_dir, 'index.ts')).touch()

        content = "import { Component } from './components'"
        imports = parse_imports(self.test_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)
        self.assertIn('index', imports[0].source_file)

    def test_mixed_default_and_named_import(self):
        """Test mixed import: import Default, { Named } from 'path'

        This is a common React pattern:
        import React, { useState, useEffect } from 'react'
        """
        # Create utils file
        utils_file = os.path.join(self.src_dir, 'utils.js')
        Path(utils_file).touch()

        # Test 1: Mixed import with project file
        content = "import utils, { useState, useEffect } from './utils'"
        imports = parse_imports(self.test_file, content, self.temp_dir)

        # Should return 2 separate ImportInfo objects
        self.assertEqual(len(imports), 2)

        # Find default and named imports
        default_import = next(
            (imp for imp in imports if imp.import_type == 'default'), None)
        named_import = next(
            (imp for imp in imports if imp.import_type == 'named'), None)

        # Verify default import
        self.assertIsNotNone(default_import, 'Should have default import')
        self.assertEqual(default_import.imported_items, ['utils'])
        self.assertIn('utils.js',
                      default_import.source_file.replace('\\', '/'))

        # Verify named import
        self.assertIsNotNone(named_import, 'Should have named import')
        self.assertEqual(
            sorted(named_import.imported_items), ['useEffect', 'useState'])
        self.assertIn('utils.js', named_import.source_file.replace('\\', '/'))

        # Both should point to the same source file
        self.assertEqual(
            default_import.source_file.replace('\\', '/'),
            named_import.source_file.replace('\\', '/'))

        # Test 2: Mixed import with external package (should be filtered)
        content2 = "import React, { useState } from 'react'"
        imports2 = parse_imports(self.test_file, content2, self.temp_dir)

        # External package should be filtered out
        self.assertEqual(
            len(imports2), 0, "External package 'react' should be filtered")

        # Test 3: Mixed import with type modifier
        types_file = os.path.join(self.src_dir, 'types.ts')
        Path(types_file).touch()

        content3 = "import type Component, { type Props, State } from './types'"
        imports3 = parse_imports(self.test_file, content3, self.temp_dir)

        # Should return 2 imports, both marked as type
        self.assertEqual(len(imports3), 2)
        default_type = next(
            (imp for imp in imports3 if imp.import_type == 'default'), None)
        named_type = next(
            (imp for imp in imports3 if imp.import_type == 'named'), None)

        self.assertIsNotNone(default_type)
        self.assertTrue(default_type.is_type_only)
        self.assertEqual(default_type.imported_items, ['Component'])

        self.assertIsNotNone(named_type)
        self.assertTrue(named_type.is_type_only)
        # 'Props' should have inline 'type' keyword removed
        self.assertIn('Props', named_type.imported_items)
        self.assertIn('State', named_type.imported_items)

    def test_relative_output_dir_js_no_excessive_parent_dirs(self):
        """Test that relative output_dir doesn't cause excessive '../' in JS/TS paths

        This is a regression test for the JS/TS bug where:
        - output_dir is relative (e.g., './output')
        - current_file is absolute (e.g., /tmp/output/src/components/Button.tsx)
        - os.path.relpath(absolute_path, relative_output_dir) uses CWD as base
        - Results in paths like ../../../../../../../../tmp/output/src/...

        Additionally tests the macOS symlink issue where:
        - /var is a symlink to /private/var
        - os.path.abspath() might return different prefixes
        - os.path.relpath() treats them as completely different paths

        The fix uses os.path.realpath() to resolve symlinks.
        """
        # Create output directory
        output_dir = './output_test_js'
        try:
            os.makedirs(output_dir)

            # Create directory structure inside output dir: src/components/
            src_dir = os.path.join(output_dir, 'src')
            components_dir = os.path.join(src_dir, 'components')
            os.makedirs(components_dir)

            # Create files inside output directory
            app_file = os.path.join(src_dir, 'App.tsx')
            button_file = os.path.join(components_dir, 'Button.tsx')
            Path(app_file).touch()
            Path(button_file).touch()

            # Import: import { Button } from './components/Button'
            content = "import { Button } from './components/Button'"

            # Test 1: Parse with relative output_dir
            imports = parse_imports('src/App.tsx', content, output_dir)

            self.assertEqual(len(imports), 1)

            source = imports[0].source_file.replace('\\', '/')
            self.assertEqual(
                source, 'src/components/Button.tsx',
                f"Expected 'src/components/Button.tsx', got: {source}")

            # Test 2: Parse with absolute output_dir (should give same result)
            abs_output_dir = os.path.abspath(output_dir)
            imports2 = parse_imports('src/App.tsx', content, abs_output_dir)

            self.assertEqual(len(imports2), 1)

            source2 = imports2[0].source_file.replace('\\', '/')
            self.assertEqual(
                source2, 'src/components/Button.tsx',
                f"Expected 'src/components/Button.tsx', got: {source2}")

            os.remove(button_file)
            content = "import { Button } from './components'"
            index_file = os.path.join(components_dir, 'index.tsx')
            Path(index_file).touch()
            imports3 = parse_imports('src/App.tsx', content, abs_output_dir)

            self.assertEqual(len(imports3), 1)

            source3 = imports3[0].source_file.replace('\\', '/')
            self.assertEqual(source3, 'src/components/index.tsx')
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)


class TestJavaScriptPathAlias(unittest.TestCase):
    """Test that path aliases are resolved correctly"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.src_dir = os.path.join(self.temp_dir, 'src')
        self.api_dir = os.path.join(self.src_dir, 'api')
        os.makedirs(self.api_dir)

        self.app_file = os.path.join(self.src_dir, 'App.tsx')
        Path(self.app_file).touch()

        self.user_file = os.path.join(self.api_dir, 'user.ts')
        Path(self.user_file).touch()

        # Create tsconfig.json
        import json
        tsconfig = {
            'compilerOptions': {
                'baseUrl': '.',
                'paths': {
                    '@api/*': ['src/api/*'],
                    '@/*': ['src/*']
                }
            }
        }
        with open(os.path.join(self.temp_dir, 'tsconfig.json'), 'w') as f:
            json.dump(tsconfig, f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_path_alias_resolved(self):
        """Test that path aliases like @api/user are resolved"""
        content = "import { getUser } from '@api/user'"
        imports = parse_imports(self.app_file, content, self.temp_dir)

        self.assertGreater(len(imports), 0)
        # Should resolve to actual file
        full_path = os.path.join(self.temp_dir, imports[0].source_file)
        self.assertTrue(os.path.exists(full_path))


class TestJavaExternalPackageFiltering(unittest.TestCase):
    """Test that Java external packages are filtered out"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, 'Test.java')
        Path(self.test_file).touch()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_java_util_filtered(self):
        """Test that 'java.util.List' is filtered out"""
        content = 'import java.util.List;'
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_java_wildcard_filtered(self):
        """Test that 'java.util.*' is filtered out"""
        content = 'import java.util.*;'
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_java_io_filtered(self):
        """Test that 'java.io.File' is filtered out"""
        content = 'import java.io.File;'
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_third_party_filtered(self):
        """Test that third-party packages are filtered out"""
        content = 'import com.example.MyClass;'
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_multiple_imports_filtered(self):
        """Test that multiple Java imports are all filtered out"""
        content = '''
import java.util.List;
import java.util.ArrayList;
import java.util.HashMap;
'''
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_static_import_filtered(self):
        """Test that static imports are filtered out"""
        content = 'import static java.lang.Math.PI;'
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_nested_class_filtered(self):
        """Test that nested class imports are filtered out"""
        content = 'import java.util.Map.Entry;'
        imports = parse_imports(self.test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)


class TestMixedImports(unittest.TestCase):
    """Test that external and project imports are correctly separated"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_absolute_output_dir_with_relative_paths(self):
        """Test that absolute output_dir correctly resolves relative import paths

        This is a regression test for the bug where:
        - output_dir is absolute (e.g., /tmp/xyz)
        - resolved path is relative (e.g., src/components/Button)
        - os.path.relpath(relative, absolute) treats relative as relative to cwd
        - Results in incorrect paths like ../../../../../../...

        The fix ensures both paths are converted to absolute before relpath.
        """
        # Create project structure with absolute output_dir
        src_dir = os.path.join(self.temp_dir, 'src')
        components_dir = os.path.join(src_dir, 'components')
        os.makedirs(components_dir)

        app_file = os.path.join(src_dir, 'App.tsx')
        Path(app_file).touch()

        button_file = os.path.join(components_dir, 'Button.tsx')
        Path(button_file).touch()

        # Import with relative path
        content = "import { Button } from './components/Button'"

        # Parse with absolute output_dir (temp_dir is always absolute)
        imports = parse_imports(app_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)

        # Verify the path is correct (relative to output_dir)
        source = imports[0].source_file.replace('\\', '/')

        # Should be src/components/Button.tsx (relative to output_dir)
        # NOT ../../../../../../... (which would indicate the bug)
        self.assertTrue(
            'src/components/Button.tsx' in source,
            f'Expected path relative to output_dir, got: {source}')

        # Should NOT contain multiple ../ (sign of the bug)
        self.assertFalse(
            source.count('../') > 2,
            f"Path has too many '../', indicates relpath bug: {source}")

        # Verify the full path exists when joined with output_dir
        full_path = os.path.join(self.temp_dir, imports[0].source_file)
        self.assertTrue(
            os.path.exists(full_path),
            f'Resolved path should exist: {full_path}')

    def test_javascript_mixed_imports(self):
        """Test that only project files are returned, external packages filtered"""
        # Create project structure
        src_dir = os.path.join(self.temp_dir, 'src')
        os.makedirs(src_dir)

        app_file = os.path.join(src_dir, 'App.tsx')
        Path(app_file).touch()

        button_file = os.path.join(src_dir, 'Button.tsx')
        Path(button_file).touch()

        styles_file = os.path.join(src_dir, 'styles.css')
        Path(styles_file).touch()

        content = '''
import React from 'react';
import { useState } from 'react';
import { Button } from './Button';
import './styles.css';
import lodash from 'lodash';
'''
        imports = parse_imports(app_file, content, self.temp_dir)

        # Should only have 2 project files (Button and styles.css)
        self.assertEqual(len(imports), 2)

        # Check that project files are present
        source_files = [imp.source_file for imp in imports]
        self.assertTrue(any('Button' in sf for sf in source_files))
        self.assertTrue(any('styles.css' in sf for sf in source_files))

    def test_python_mixed_imports(self):
        """Test that only relative imports are returned, external packages filtered"""
        # Create project structure
        pkg_dir = os.path.join(self.temp_dir, 'mypackage')
        os.makedirs(pkg_dir)
        Path(os.path.join(pkg_dir, '__init__.py')).touch()
        Path(os.path.join(pkg_dir, 'config.py')).touch()  # Create config file

        test_file = os.path.join(pkg_dir, 'test.py')
        Path(test_file).touch()

        utils_dir = os.path.join(pkg_dir, 'utils')
        os.makedirs(utils_dir)
        Path(os.path.join(utils_dir, 'helpers.py')).touch()

        content = '''
import os
import sys
from typing import List, Dict
from .utils.helpers import func1
from .config import settings
'''
        imports = parse_imports(test_file, content, self.temp_dir)

        # Should have 2 relative imports (utils.helpers and config)
        # External packages (os, sys, typing) are filtered out
        self.assertEqual(len(imports), 2)

        # Verify resolved file paths (normalized for cross-platform)
        source_files = [imp.source_file.replace('\\', '/') for imp in imports]
        self.assertIn('mypackage/utils/helpers.py', source_files)
        self.assertIn('mypackage/config.py', source_files)

        # Verify imported items
        all_items = []
        for imp in imports:
            all_items.extend(imp.imported_items)
        self.assertIn('func1', all_items)
        self.assertIn('settings', all_items)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_empty_file(self):
        """Test parsing an empty file"""
        test_file = os.path.join(self.temp_dir, 'empty.ts')
        Path(test_file).touch()

        imports = parse_imports(test_file, '', self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_no_imports(self):
        """Test file with no imports"""
        test_file = os.path.join(self.temp_dir, 'no_imports.ts')
        Path(test_file).touch()

        content = 'const x = 1;\nconst y = 2;\nconsole.log(x + y);'
        imports = parse_imports(test_file, content, self.temp_dir)
        self.assertEqual(len(imports), 0)

    def test_commented_imports_ignored(self):
        """Test that commented imports are ignored"""
        test_file = os.path.join(self.temp_dir, 'commented.ts')
        Path(test_file).touch()

        # Create component files in same directory
        Path(os.path.join(self.temp_dir, 'Button.tsx')).touch()
        Path(os.path.join(self.temp_dir, 'Input.tsx')).touch()
        Path(os.path.join(self.temp_dir, 'Component.tsx')).touch()

        content = '''
// import { Button } from './Button'
/* import { Input } from './Input' */
import { Component } from './Component'
'''
        imports = parse_imports(test_file, content, self.temp_dir)

        # Only Component should be imported
        all_items = []
        for imp in imports:
            all_items.extend(imp.imported_items)

        self.assertIn('Component', all_items)
        self.assertNotIn('Button', all_items)
        self.assertNotIn('Input', all_items)

    def test_catastrophic_backtracking_prevention(self):
        """Test that complex content doesn't cause catastrophic backtracking"""
        import time

        # Create actual files for the export statements
        contexts_dir = os.path.join(self.temp_dir, 'contexts')
        os.makedirs(contexts_dir)

        test_file = os.path.join(contexts_dir, 'index.js')
        Path(test_file).touch()

        # Create all context files
        context_files = [
            'AuthContext', 'ThemeContext', 'DataContext', 'ModalContext',
            'ToastContext', 'RouterContext', 'APIContext', 'StateContext',
            'ConfigContext', 'CacheContext'
        ]
        for ctx in context_files:
            Path(os.path.join(contexts_dir, f'{ctx}.js')).touch()

        # This type of content previously caused 30-minute hangs due to nested quantifiers
        # in the old regex pattern: (?:(\{[^}]*\}|\*\s+as\s+\w+|\w+)\s*,?\s*)*
        content = '''现在我了解了AuthContext的导出内容。根据项目结构，这个index.js文件应该作为contexts目录的统一导出入口。

export { AuthProvider, useAuth } from './AuthContext';
export { ThemeProvider, useTheme } from './ThemeContext';
export { DataProvider, useData } from './DataContext';
export { ModalProvider, useModal } from './ModalContext';
export { ToastProvider, useToast } from './ToastContext';
export { RouterProvider, useRouter } from './RouterContext';
export { APIProvider, useAPI } from './APIContext';
export { StateProvider, useState } from './StateContext';
export { ConfigProvider, useConfig } from './ConfigContext';
export { CacheProvider, useCache } from './CacheContext';
'''

        # Should complete in under 1 second (previously took 30 minutes)
        start_time = time.time()
        imports = parse_imports(test_file, content, self.temp_dir)
        elapsed_time = time.time() - start_time

        # Assert performance: should complete in under 1 second
        self.assertLess(
            elapsed_time, 1.0,
            f'Parsing took {elapsed_time:.2f}s, possible catastrophic backtracking'
        )

        # Verify we parsed all export statements correctly
        self.assertEqual(len(imports), 10)

        # Verify source files (normalized paths)
        source_files = {imp.source_file.replace('\\', '/') for imp in imports}
        expected_files = {f'contexts/{ctx}.js' for ctx in context_files}
        self.assertEqual(source_files, expected_files)

        # Verify all exported items are present
        all_items = []
        for imp in imports:
            all_items.extend(imp.imported_items)

        expected_items = [
            'AuthProvider', 'useAuth', 'ThemeProvider', 'useTheme',
            'DataProvider', 'useData', 'ModalProvider', 'useModal',
            'ToastProvider', 'useToast', 'RouterProvider', 'useRouter',
            'APIProvider', 'useAPI', 'StateProvider', 'useState',
            'ConfigProvider', 'useConfig', 'CacheProvider', 'useCache'
        ]
        self.assertEqual(sorted(all_items), sorted(expected_items))

    def test_barrel_export_with_english_description(self):
        """Test barrel export file with English description that previously caused hang"""
        import time

        # Create components directory and files
        components_dir = os.path.join(self.temp_dir, 'components')
        os.makedirs(components_dir)

        test_file = os.path.join(components_dir, 'index.js')
        Path(test_file).touch()

        # Create all component files
        component_files = [
            'Button', 'Input', 'Card', 'Modal', 'Navbar', 'Footer', 'Sidebar',
            'Header', 'Table', 'Form'
        ]
        for comp in component_files:
            Path(os.path.join(components_dir, f'{comp}.jsx')).touch()

        # Real-world content that previously caused catastrophic backtracking
        # This exact pattern was reported to hang for 30+ minutes
        content = """Now I have a clear understanding of all the components. I need to create an index.js file that exports all these components. This is a barrel export file that will make it easier to import components from other parts of the application.

<result>javascript: frontend/src/components/index.js

export { Button } from './Button';
export { Input } from './Input';
export { Card } from './Card';
export { Modal } from './Modal';
export { Navbar } from './Navbar';
export { Footer } from './Footer';
export { Sidebar } from './Sidebar';
export { Header } from './Header';
export { Table } from './Table';
export { Form } from './Form';
</result>
""" # noqa

        # Should complete in under 1 second (previously hung indefinitely)
        start_time = time.time()
        imports = parse_imports(test_file, content, self.temp_dir)
        elapsed_time = time.time() - start_time

        # Assert performance: must complete quickly
        self.assertLess(
            elapsed_time, 1.0,
            f'Parsing took {elapsed_time:.2f}s, catastrophic backtracking detected'
        )

        # Verify all exports are parsed correctly
        self.assertEqual(len(imports), 10)

        # Verify source files (note: imports resolve to .jsx files we created)
        source_files = {imp.source_file.replace('\\', '/') for imp in imports}
        expected_files = {f'components/{comp}.jsx' for comp in component_files}
        self.assertEqual(source_files, expected_files)

        # Verify all component names are exported
        all_items = [item for imp in imports for item in imp.imported_items]
        self.assertEqual(sorted(all_items), sorted(component_files))

    def test_very_long_import_statement(self):
        """Test that very long import statements are handled efficiently"""
        import time

        test_file = os.path.join(self.temp_dir, 'long.ts')
        Path(test_file).touch()

        # Create a very long import statement with many items
        items = ', '.join([f'Item{i}' for i in range(100)])
        content = f"import {{ {items} }} from 'external-package';"

        # Should complete quickly even with 100 imported items
        start_time = time.time()
        imports = parse_imports(test_file, content, self.temp_dir)
        elapsed_time = time.time() - start_time

        # Should complete in under 0.1 seconds
        self.assertLess(elapsed_time, 0.1,
                        f'Parsing long import took {elapsed_time:.2f}s')

        # External package should be filtered out
        self.assertEqual(len(imports), 0)

    def test_multiline_with_complex_formatting(self):
        """Test multiline imports with complex formatting and whitespace"""
        test_file = os.path.join(self.temp_dir, 'formatted.ts')
        Path(test_file).touch()

        # Create types file
        Path(os.path.join(self.temp_dir, 'types.ts')).touch()

        # Complex multiline formatting that could trigger backtracking
        content = '''import {
  type User,
  type Product,
  Component,

  Helper,
  type Config,

  Service
} from './types';
'''

        imports = parse_imports(test_file, content, self.temp_dir)

        # Should parse successfully
        self.assertEqual(len(imports), 1)
        # Should extract all items with 'type' keyword removed
        expected_items = [
            'User', 'Product', 'Component', 'Helper', 'Config', 'Service'
        ]
        self.assertEqual(
            sorted(imports[0].imported_items), sorted(expected_items))
        # Verify source file
        self.assertEqual(imports[0].source_file.replace('\\', '/'), 'types.ts')

    def test_python_multiline_import(self):
        """Test Python multiline import statements"""
        # Create project structure
        pkg_dir = os.path.join(self.temp_dir, 'mypackage')
        os.makedirs(pkg_dir)
        Path(os.path.join(pkg_dir, '__init__.py')).touch()

        test_file = os.path.join(pkg_dir, 'test.py')
        Path(test_file).touch()

        utils_file = os.path.join(pkg_dir, 'utils.py')
        Path(utils_file).touch()

        # Python multiline import with parentheses
        content = '''from .utils import (
    func1,
    func2,
    func3,
    func4
)
'''

        imports = parse_imports(test_file, content, self.temp_dir)

        # Should parse successfully
        self.assertEqual(len(imports), 1)

        # Verify all items extracted
        expected_items = ['func1', 'func2', 'func3', 'func4']
        self.assertEqual(
            sorted(imports[0].imported_items), sorted(expected_items))

        # Verify source file path
        self.assertEqual(imports[0].source_file.replace('\\', '/'),
                         'mypackage/utils.py')

    def test_javascript_multiline_import(self):
        """Test JavaScript multiline import statements"""
        test_file = os.path.join(self.temp_dir, 'app.js')
        Path(test_file).touch()

        # Create module file
        Path(os.path.join(self.temp_dir, 'utils.js')).touch()

        # JavaScript multiline import
        content = '''import {
    helper1,
    helper2,
    helper3,
    helper4,
    helper5
} from './utils';
'''

        imports = parse_imports(test_file, content, self.temp_dir)

        # Should parse successfully
        self.assertEqual(len(imports), 1)

        # Verify all items extracted
        expected_items = [
            'helper1', 'helper2', 'helper3', 'helper4', 'helper5'
        ]
        self.assertEqual(
            sorted(imports[0].imported_items), sorted(expected_items))

        # Verify source file path
        self.assertEqual(imports[0].source_file.replace('\\', '/'), 'utils.js')

    def test_python_multiline_with_comments(self):
        """Test Python multiline import with inline comments"""
        pkg_dir = os.path.join(self.temp_dir, 'mypackage')
        os.makedirs(pkg_dir)
        Path(os.path.join(pkg_dir, '__init__.py')).touch()

        test_file = os.path.join(pkg_dir, 'test.py')
        Path(test_file).touch()

        helpers_file = os.path.join(pkg_dir, 'helpers.py')
        Path(helpers_file).touch()

        # Multiline import with comments
        content = '''from .helpers import (
    func1,  # Main function
    func2,  # Helper function
    func3   # Utility function
)
'''

        imports = parse_imports(test_file, content, self.temp_dir)

        self.assertEqual(len(imports), 1)
        # Comments should be stripped
        expected_items = ['func1', 'func2', 'func3']
        self.assertEqual(
            sorted(imports[0].imported_items), sorted(expected_items))
        self.assertEqual(imports[0].source_file.replace('\\', '/'),
                         'mypackage/helpers.py')

    def test_barrel_export_relative_path_issue(self):
        """Test barrel export with relative paths doesn't produce ../ prefix

        This is a regression test for the issue where:
        - code_file: 'frontend/src/components/index.js' (relative path)
        - output_dir: './output' (relative path)
        - Previously returned: '../frontend/src/components/Layout' (WRONG)
        - Should return: 'frontend/src/components/Layout.js' (CORRECT)
        """
        # Create directory structure: frontend/src/components/
        frontend_dir = os.path.join(self.temp_dir, 'frontend', 'src',
                                    'components')
        os.makedirs(frontend_dir)

        # Create the barrel export index.js file
        index_file = os.path.join(frontend_dir, 'index.js')
        Path(index_file).touch()

        # Create component files (direct files)
        for component in ['Layout', 'Header', 'Footer', 'ModelCard']:
            component_file = os.path.join(frontend_dir, f'{component}.js')
            Path(component_file).touch()

        # Create component directories with index files
        for component in ['DatasetCard', 'CommentList']:
            component_dir = os.path.join(frontend_dir, component)
            os.makedirs(component_dir)
            index_jsx = os.path.join(component_dir, 'index.jsx')
            Path(index_jsx).touch()

        # Use temp_dir as output_dir (absolute paths)
        content = '''export { default as Layout } from './Layout';
export { default as Header } from './Header';
export { default as Footer } from './Footer';
export { default as ModelCard } from './ModelCard';
export { default as DatasetCard } from './DatasetCard';
export { default as CommentList } from './CommentList';
'''

        # Parse with absolute paths
        imports = parse_imports(index_file, content, self.temp_dir)

        # Should parse all exports
        self.assertEqual(len(imports), 6)

        # Verify source files have correct format
        for imp in imports:
            # Should have file extension or be a directory with index
            basename = os.path.basename(imp.source_file)
            self.assertTrue(
                '.' in basename
                or '/index.' in imp.source_file.replace('\\', '/'),
                f'Path should have extension or be index file: {imp.source_file}'
            )

        # Verify specific files
        source_files = {imp.source_file.replace('\\', '/') for imp in imports}

        # Direct files should have .js extension
        self.assertTrue(
            any('Layout.js' in f for f in source_files),
            'Layout.js should exist')
        self.assertTrue(
            any('Header.js' in f for f in source_files),
            'Header.js should exist')
        self.assertTrue(
            any('Footer.js' in f for f in source_files),
            'Footer.js should exist')
        self.assertTrue(
            any('ModelCard.js' in f for f in source_files),
            'ModelCard.js should exist')

        # Directory imports should resolve to index.jsx
        self.assertTrue(
            any('DatasetCard/index.jsx' in f for f in source_files),
            f'DatasetCard should resolve to index.jsx, got: {source_files}')
        self.assertTrue(
            any('CommentList/index.jsx' in f for f in source_files),
            f'CommentList should resolve to index.jsx, got: {source_files}')

        # Verify all import default
        for imp in imports:
            self.assertEqual(imp.imported_items, ['default'])

    def test_css_import_no_extra_extension(self):
        """Test that CSS imports don't get extra .js extension

        Regression test for the issue where:
        - import styles from './index.module.css'
        - Previously returned: 'index.module.css.js' (WRONG)
        - Should return: 'index.module.css' (CORRECT)
        """
        # Create directory structure
        pages_dir = os.path.join(self.temp_dir, 'frontend', 'src', 'pages',
                                 'Auth')
        os.makedirs(pages_dir)

        # Create Login.jsx file
        login_file = os.path.join(pages_dir, 'Login.jsx')
        Path(login_file).touch()

        # CSS file doesn't exist (common case - CSS might be in different location)
        # But we still want correct path resolution

        content = '''import React from 'react';
import styles from './index.module.css';
import data from './config.json';
import icon from './logo.svg';
'''

        imports = parse_imports(login_file, content, self.temp_dir)

        # Should parse 3 imports (React is filtered as external)
        self.assertEqual(len(imports), 3)

        # Verify file paths
        source_files = {imp.source_file.replace('\\', '/') for imp in imports}

        # CSS should NOT have .js appended
        css_import = [f for f in source_files if 'module.css' in f][0]
        self.assertTrue(
            css_import.endswith('.css'),
            f'CSS import should end with .css, got: {css_import}')
        self.assertFalse(
            css_import.endswith('.css.js'),
            f'CSS import should NOT have .js appended, got: {css_import}')

        # JSON should NOT have .js appended
        json_import = [f for f in source_files if 'config.json' in f][0]
        self.assertTrue(
            json_import.endswith('.json'),
            f'JSON import should end with .json, got: {json_import}')
        self.assertFalse(
            json_import.endswith('.json.js'),
            f'JSON import should NOT have .js appended, got: {json_import}')

        # SVG should NOT have .js appended
        svg_import = [f for f in source_files if 'logo.svg' in f][0]
        self.assertTrue(
            svg_import.endswith('.svg'),
            f'SVG import should end with .svg, got: {svg_import}')
        self.assertFalse(
            svg_import.endswith('.svg.js'),
            f'SVG import should NOT have .js appended, got: {svg_import}')


if __name__ == '__main__':
    unittest.main()
