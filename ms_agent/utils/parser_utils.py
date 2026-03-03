import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import json


@dataclass
class ImportInfo:
    """Detailed information about an import statement"""
    # Source file path (resolved path)
    source_file: str
    # Original import statement
    raw_statement: str
    # What's being imported (e.g., ['User', 'UserRole'] or ['*'] or ['default'])
    imported_items: List[str] = field(default_factory=list)
    # Import type: 'named', 'default', 'namespace', 'side-effect'
    import_type: str = 'named'
    # Alias if any (e.g., 'import * as utils' -> 'utils')
    alias: Optional[str] = None
    # Whether this is a type-only import (TypeScript)
    is_type_only: bool = False

    def __repr__(self):
        items_str = ', '.join(
            self.imported_items) if self.imported_items else 'all'
        alias_str = f' as {self.alias}' if self.alias else ''
        return f"ImportInfo(file='{self.source_file}', items=[{items_str}]{alias_str})"


class BaseImportParser(ABC):
    """Base class for language-specific import parsers"""

    def __init__(self, output_dir: str, current_file: str, current_dir: str):
        self.output_dir = output_dir
        self.current_file = current_file
        self.current_dir = current_dir

    @abstractmethod
    def get_file_extensions(self) -> List[str]:
        """Return list of file extensions this parser handles"""
        pass

    @abstractmethod
    def parse(self, code_content: str) -> List[ImportInfo]:
        """Parse imports from code content"""
        pass

    def _resolve_path(self, module_path: str) -> Optional[str]:
        """Resolve module path to file path (to be overridden by subclasses)"""
        return None


class PythonImportParser(BaseImportParser):
    """Parser for Python import statements"""

    def get_file_extensions(self) -> List[str]:
        return ['py']

    def parse(self, code_content: str) -> List[ImportInfo]:
        imports = []

        # Pattern 1: from ... import ...
        from_pattern = r'^\s*from\s+([\w.]+)\s+import\s+(?:\(([^)]+)\)|([^\n]+))'
        for match in re.finditer(from_pattern, code_content,
                                 re.MULTILINE | re.DOTALL):
            info = self._extract_from_import(match, code_content)
            if info:
                imports.append(info)

        # Pattern 2: import ...
        import_pattern = r'^\s*import\s+([\w.,\s]+)'
        for match in re.finditer(import_pattern, code_content, re.MULTILINE):
            infos = self._extract_simple_import(match)
            imports.extend(infos)

        return imports

    def _extract_from_import(self, match,
                             code_content) -> Optional[ImportInfo]:
        """Extract 'from ... import ...' statement"""
        module_path = match.group(1)
        # Group 2 is parenthesized multi-line imports, group 3 is single-line imports
        imports_str = (match.group(2) or match.group(3)).strip()

        # Remove inline comments
        lines = imports_str.split('\n')
        cleaned_items = []
        for line in lines:
            if '#' in line:
                line = line[:line.index('#')]
            cleaned_items.append(line.strip())
        imports_str = ','.join(cleaned_items)

        # Parse imported items
        imported_items = []
        for item in imports_str.split(','):
            item = item.strip()
            if not item:
                continue
            if ' as ' in item:
                imported_items.append(item.split(' as ')[0].strip())
            elif item != '*':
                imported_items.append(item)
            elif item == '*':
                imported_items = ['*']
                break

        # Resolve file path
        file_path = self._resolve_python_path(module_path)
        # If file not found, use module_path as source_file (could be stdlib or external package)
        if not file_path:
            file_path = module_path

        return ImportInfo(
            source_file=file_path,
            raw_statement=match.group(0),
            imported_items=imported_items,
            import_type='namespace' if '*' in imported_items else 'named')

    def _extract_simple_import(self, match) -> List[ImportInfo]:
        """Extract 'import ...' statement"""
        imports_str = match.group(1)
        results = []

        for module in imports_str.split(','):
            module = module.strip()
            if not module:
                continue

            alias = None
            if ' as ' in module:
                module, alias = module.split(' as ')
                module = module.strip()
                alias = alias.strip()

            file_path = self._resolve_python_path(module)
            # If not found, use module name (could be stdlib)
            if not file_path:
                file_path = module

            results.append(
                ImportInfo(
                    source_file=file_path,
                    raw_statement=f'import {module}',
                    imported_items=[module.split('.')[-1]],
                    import_type='default',
                    alias=alias))

        return results

    def _resolve_python_path(self, module_path: str) -> Optional[str]:
        """Resolve Python module to file path

        For relative imports (starting with .), resolves them relative to current_dir.
        For absolute imports, tries to resolve from output_dir.

        Returns path relative to output_dir with file extension.
        """

        # Helper function to safely convert to relative path
        def safe_relpath(path):
            """Convert path to relative from output_dir, handling mixed abs/rel paths.

            IMPORTANT: In Python imports, paths should always be absolute (from current_dir).
            Always convert output_dir to absolute to avoid relpath bugs.
            Use realpath to resolve symlinks (e.g., /var vs /private/var on macOS).
            """
            # Use realpath to resolve symlinks and get canonical paths
            abs_output_dir = os.path.realpath(os.path.abspath(self.output_dir))

            # Path should be absolute (constructed from absolute current_dir)
            # If somehow it's relative, make it absolute from output_dir
            if os.path.isabs(path):
                abs_path = os.path.realpath(path)
            else:
                # This shouldn't happen in Python imports, but handle it anyway
                abs_path = os.path.realpath(os.path.join(abs_output_dir, path))

            return os.path.relpath(abs_path, abs_output_dir)

        # Handle relative imports (., .., ...)
        if module_path.startswith('.'):
            # Count leading dots
            dots = 0
            for char in module_path:
                if char == '.':
                    dots += 1
                else:
                    break

            # Get the module part after dots
            module_part = module_path[dots:]

            # Calculate the target directory
            # . means current directory, .. means parent, etc.
            target_dir = self.current_dir
            for _ in range(dots - 1):  # -1 because . means current dir
                target_dir = os.path.dirname(target_dir)

            # If there's a module part, append it
            if module_part:
                module_file_path = module_part.replace('.', os.sep)
                target_dir = os.path.join(target_dir, module_file_path)

            # Try as package
            package_init = os.path.normpath(
                os.path.join(target_dir, '__init__.py'))
            if os.path.exists(package_init):
                return safe_relpath(package_init)

            # Try as module
            module_file = os.path.normpath(target_dir + '.py')
            if os.path.exists(module_file):
                return safe_relpath(module_file)

            # File doesn't exist - return constructed path
            # Convert relative import notation to file path
            # e.g., "..config" -> "../config.py" or "../config/__init__.py"
            relative_path = safe_relpath(target_dir)
            # Try to guess if it's a package or module (assume module if uncertain)
            return relative_path + '.py'

        # Handle absolute imports
        module_file_path = module_path.replace('.', os.sep)

        # Try as package (relative to current file)
        package_init = os.path.normpath(
            os.path.join(self.current_dir, module_file_path, '__init__.py'))
        if os.path.exists(package_init):
            return safe_relpath(package_init)

        # Try as module (relative to current file)
        module_file = os.path.normpath(
            os.path.join(self.current_dir, module_file_path + '.py'))
        if os.path.exists(module_file):
            return safe_relpath(module_file)

        # Try from output_dir (absolute import)
        if self.output_dir:
            package_init_abs = os.path.normpath(
                os.path.join(self.output_dir, module_file_path, '__init__.py'))
            if os.path.exists(package_init_abs):
                return os.path.join(module_file_path, '__init__.py')

            module_file_abs = os.path.normpath(
                os.path.join(self.output_dir, module_file_path + '.py'))
            if os.path.exists(module_file_abs):
                return module_file_path + '.py'

        return None


class JavaScriptImportParser(BaseImportParser):
    """Parser for JavaScript/TypeScript import statements"""

    def __init__(self, output_dir: str, current_file: str, current_dir: str):
        super().__init__(output_dir, current_file, current_dir)
        self.path_aliases = self._load_path_aliases()

    def get_file_extensions(self) -> List[str]:
        return ['js', 'ts', 'jsx', 'tsx', 'mjs', 'cjs']

    def parse(self, code_content: str) -> List[ImportInfo]:
        imports = []

        # Pattern 1: Mixed import - import Default, { Named } from 'path'
        # Must come BEFORE Pattern 2 and 3 to avoid partial matches
        mixed_pattern = r"^\s*import\s+(type\s+)?(\w+)\s*,\s*\{([^}]+)\}\s*from\s+['\"]([^'\"]+)['\"]"
        for match in re.finditer(mixed_pattern, code_content,
                                 re.MULTILINE | re.DOTALL):
            infos = self._extract_mixed_import(match)
            if infos:
                imports.extend(infos)

        # Pattern 2: Named import - import { A, B } from 'path' (supports multiline)
        named_pattern = r"^\s*import\s+(type\s+)?\{([^}]+)\}\s*from\s+['\"]([^'\"]+)['\"]"
        for match in re.finditer(named_pattern, code_content,
                                 re.MULTILINE | re.DOTALL):
            info = self._extract_named_import(match)
            if info:
                imports.append(info)

        # Pattern 3: Default import - import React from 'path'
        default_pattern = r"^\s*import\s+(type\s+)?(\w+)\s+from\s+['\"]([^'\"]+)['\"]"
        for match in re.finditer(default_pattern, code_content, re.MULTILINE):
            info = self._extract_default_import(match)
            if info:
                imports.append(info)

        # Pattern 4: Namespace import - import * as name from 'path'
        namespace_pattern = r"^\s*import\s+(type\s+)?\*\s+as\s+(\w+)\s+from\s+['\"]([^'\"]+)['\"]"
        for match in re.finditer(namespace_pattern, code_content,
                                 re.MULTILINE):
            info = self._extract_namespace_import(match)
            if info:
                imports.append(info)

        # Pattern 5: Side-effect import - import 'path'
        side_effect_pattern = r"^\s*import\s+['\"]([^'\"]+)['\"]"
        for match in re.finditer(side_effect_pattern, code_content,
                                 re.MULTILINE):
            info = self._extract_side_effect_import(match)
            if info:
                imports.append(info)

        # Pattern 6: Named re-export - export { A, B } from 'path' (supports multiline)
        export_named_pattern = r"^\s*export\s+(type\s+)?\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]"
        for match in re.finditer(export_named_pattern, code_content,
                                 re.MULTILINE | re.DOTALL):
            info = self._extract_export_named(match)
            if info:
                imports.append(info)

        # Pattern 7: Wildcard re-export - export * from 'path'
        export_wildcard_pattern = r"^\s*export\s+(type\s+)?\*\s+from\s+['\"]([^'\"]+)['\"]"
        for match in re.finditer(export_wildcard_pattern, code_content,
                                 re.MULTILINE):
            info = self._extract_export_wildcard(match)
            if info:
                imports.append(info)

        # Pattern 8: Named wildcard re-export - export * as name from 'path'
        export_named_wildcard_pattern = r"^\s*export\s+(type\s+)?\*\s+as\s+(\w+)\s+from\s+['\"]([^'\"]+)['\"]"
        for match in re.finditer(export_named_wildcard_pattern, code_content,
                                 re.MULTILINE):
            info = self._extract_export_named_wildcard(match)
            if info:
                imports.append(info)

        return imports

    def _extract_mixed_import(self, match) -> List[ImportInfo]:
        """Extract: import Default, { Named1, Named2 } from 'path'

        Returns a list of 2 ImportInfo objects:
        1. Default import
        2. Named imports
        """
        is_type = bool(match.group(1))
        default_name = match.group(2)
        named_items_str = match.group(3).strip()
        import_path = match.group(4)

        # Parse named items and remove inline 'type' keyword
        named_items = []
        for item in named_items_str.split(','):
            item = item.strip()
            if not item:
                continue
            # Remove inline 'type' keyword: "type User" -> "User"
            if item.startswith('type '):
                item = item[5:].strip()
            # Extract name before 'as' if aliased
            item = item.split(' as ')[0].strip()
            named_items.append(item)

        resolved_path = self._resolve_js_path(import_path)
        # If not resolved, use import_path as-is (external package)
        if not resolved_path:
            resolved_path = import_path

        results = []

        # Create default import info
        results.append(
            ImportInfo(
                source_file=resolved_path,
                raw_statement=match.group(0),
                imported_items=[default_name],
                import_type='default',
                is_type_only=is_type))

        # Create named import info
        results.append(
            ImportInfo(
                source_file=resolved_path,
                raw_statement=match.group(0),
                imported_items=named_items,
                import_type='named',
                is_type_only=is_type))

        return results

    def _extract_named_import(self, match) -> Optional[ImportInfo]:
        """Extract: import { A, B } from 'path'"""
        is_type = bool(match.group(1))
        items_str = match.group(2).strip()
        import_path = match.group(3)

        # Parse items and remove inline 'type' keyword (TS 4.5+ syntax)
        items = []
        for item in items_str.split(','):
            item = item.strip()
            if not item:
                continue
            # Remove inline 'type' keyword: "type User" -> "User"
            if item.startswith('type '):
                item = item[5:].strip()  # Remove 'type '
            # Extract name before 'as' if aliased
            item = item.split(' as ')[0].strip()
            items.append(item)

        resolved_path = self._resolve_js_path(import_path)
        # If not resolved, use import_path as-is (external package)
        if not resolved_path:
            resolved_path = import_path

        return ImportInfo(
            source_file=resolved_path,
            raw_statement=match.group(0),
            imported_items=items,
            import_type='named',
            is_type_only=is_type)

    def _extract_default_import(self, match) -> Optional[ImportInfo]:
        """Extract: import React from 'path'"""
        is_type = bool(match.group(1))
        name = match.group(2)
        import_path = match.group(3)

        resolved_path = self._resolve_js_path(import_path)
        # If not resolved, use import_path as-is (external package)
        if not resolved_path:
            resolved_path = import_path

        return ImportInfo(
            source_file=resolved_path,
            raw_statement=match.group(0),
            imported_items=[name],
            import_type='default',
            is_type_only=is_type)

    def _extract_namespace_import(self, match) -> Optional[ImportInfo]:
        """Extract: import * as name from 'path'"""
        is_type = bool(match.group(1))
        name = match.group(2)
        import_path = match.group(3)

        resolved_path = self._resolve_js_path(import_path)
        # If not resolved, use import_path as-is (external package)
        if not resolved_path:
            resolved_path = import_path

        return ImportInfo(
            source_file=resolved_path,
            raw_statement=match.group(0),
            imported_items=['*'],
            import_type='namespace',
            alias=name,
            is_type_only=is_type)

    def _extract_side_effect_import(self, match) -> Optional[ImportInfo]:
        """Extract: import 'path'"""
        import_path = match.group(1)
        resolved_path = self._resolve_js_path(import_path)
        # If not resolved, use import_path as-is (external package)
        if not resolved_path:
            resolved_path = import_path

        return ImportInfo(
            source_file=resolved_path,
            raw_statement=match.group(0),
            imported_items=[],
            import_type='side-effect')

    def _extract_export_named(self, match) -> Optional[ImportInfo]:
        """Extract: export { A, B } from 'path'"""
        is_type = bool(match.group(1))
        items_str = match.group(2).strip()
        import_path = match.group(3)

        # Parse items and remove inline 'type' keyword (TS 4.5+ syntax)
        items = []
        for item in items_str.split(','):
            item = item.strip()
            if not item:
                continue
            # Remove inline 'type' keyword: "type User" -> "User"
            if item.startswith('type '):
                item = item[5:].strip()  # Remove 'type '
            # Extract name before 'as' if aliased
            item = item.split(' as ')[0].strip()
            items.append(item)

        resolved_path = self._resolve_js_path(import_path)
        # If not resolved, use import_path as-is (external package)
        if not resolved_path:
            resolved_path = import_path

        return ImportInfo(
            source_file=resolved_path,
            raw_statement=match.group(0),
            imported_items=items,
            import_type='named',
            is_type_only=is_type)

    def _extract_export_wildcard(self, match) -> Optional[ImportInfo]:
        """Extract: export * from 'path'"""
        is_type = bool(match.group(1))
        import_path = match.group(2)

        resolved_path = self._resolve_js_path(import_path)
        # If not resolved, use import_path as-is (external package)
        if not resolved_path:
            resolved_path = import_path

        return ImportInfo(
            source_file=resolved_path,
            raw_statement=match.group(0),
            imported_items=['*'],
            import_type='namespace',
            is_type_only=is_type)

    def _extract_export_named_wildcard(self, match) -> Optional[ImportInfo]:
        """Extract: export * as name from 'path'"""
        is_type = bool(match.group(1))
        name = match.group(2)
        import_path = match.group(3)

        resolved_path = self._resolve_js_path(import_path)
        # If not resolved, use import_path as-is (external package)
        if not resolved_path:
            resolved_path = import_path

        return ImportInfo(
            source_file=resolved_path,
            raw_statement=match.group(0),
            imported_items=['*'],
            import_type='namespace',
            alias=name,
            is_type_only=is_type)

    def _resolve_js_path(self, import_path: str) -> Optional[str]:
        """Resolve JavaScript/TypeScript import path to file

        Returns path relative to output_dir with file extension.
        Returns None for external packages.
        """
        # Check if it's an external package (doesn't start with . or /)
        is_external = not import_path.startswith(
            '.') and not import_path.startswith('/')

        # External packages return None early
        if is_external:
            # Check if it might be a path alias
            alias_resolved = self._resolve_alias_path(import_path)
            if not alias_resolved:
                # Not an alias, it's an external package
                return None
            resolved = alias_resolved
        elif import_path.startswith('/'):
            resolved = import_path.lstrip('/')
        else:
            # Handle relative paths - resolve relative to current_file's directory
            resolved = os.path.join(self.current_dir, import_path)
            resolved = os.path.normpath(resolved)

        # Helper function to convert to relative path from output_dir
        def to_relative(path):
            """Convert path to relative from output_dir.

            IMPORTANT: path must be absolute or will be treated as relative to cwd!
            Always convert to absolute before calling relpath.
            """
            # Convert both to absolute paths first
            abs_output_dir = os.path.abspath(self.output_dir)

            # If path is already absolute, use it directly
            if os.path.isabs(path):
                abs_path = path
            else:
                # Path is relative - must be relative to output_dir
                abs_path = os.path.abspath(os.path.join(self.output_dir, path))

            # Now both are absolute, safe to use relpath
            return os.path.relpath(abs_path, abs_output_dir)

        # Convert resolved path to absolute for existence checks
        # resolved is relative to output_dir, so we need to join them
        if os.path.isabs(resolved):
            abs_resolved = resolved
        elif os.path.isabs(self.output_dir):
            abs_resolved = os.path.join(self.output_dir, resolved)
        else:
            # Both are relative, make absolute from current working directory
            abs_resolved = os.path.abspath(
                os.path.join(self.output_dir, resolved))

        # Try as directory with index file first
        if os.path.isdir(abs_resolved):
            for index_file in [
                    'index.ts', 'index.tsx', 'index.js', 'index.jsx'
            ]:
                index_path = os.path.join(abs_resolved, index_file)
                if os.path.exists(index_path):
                    # Return relative path with index file
                    return to_relative(os.path.join(resolved, index_file))
            # Directory exists but no index file - return directory itself
            return to_relative(resolved)

        # Try different extensions
        extensions = [
            '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.json', '.css',
            '.scss', '.sass', '.less', '.module.css', '.module.scss'
        ]

        for ext in extensions:
            path_with_ext = abs_resolved + ext
            if os.path.exists(path_with_ext):
                return to_relative(resolved + ext)

        # File doesn't exist - add default extension based on current file type
        if not os.path.exists(abs_resolved):
            # Check if path already has an extension (e.g., .css, .json)
            if '.' in os.path.basename(resolved):
                # Already has extension, return as-is
                return to_relative(resolved)

            # No extension, infer from current_file
            if self.current_file:
                current_ext = os.path.splitext(self.current_file)[1]
                if current_ext in ['.ts', '.tsx']:
                    return to_relative(resolved + '.tsx')
                elif current_ext in ['.js', '.jsx', '.mjs']:
                    return to_relative(resolved + '.js')
            # Default to .js
            return to_relative(resolved + '.js')

        # Path exists as-is
        if os.path.exists(abs_resolved):
            return to_relative(resolved)

        # File doesn't exist, but has extension
        if '.' in os.path.basename(resolved):
            return to_relative(resolved)

        # Last resort: add default extension
        default_ext = '.js'
        if self.current_file:
            current_ext = os.path.splitext(self.current_file)[1]
            if current_ext in ['.ts', '.tsx']:
                default_ext = '.tsx'
        return to_relative(resolved + default_ext)

    def _load_path_aliases(self) -> Dict[str, str]:
        """Load path aliases from tsconfig.json and vite.config"""
        aliases = {}
        excluded_dirs = {
            'node_modules', 'dist', 'build', '.git', '__pycache__'
        }

        # Search for config files
        for root, dirs, files in os.walk(self.output_dir):
            dirs[:] = [d for d in dirs if d not in excluded_dirs]

            # tsconfig.json
            if 'tsconfig.json' in files:
                self._parse_tsconfig_aliases(
                    os.path.join(root, 'tsconfig.json'), root, aliases)

            # vite.config.*
            for config_file in [
                    'vite.config.js', 'vite.config.ts', 'vite.config.mjs'
            ]:
                if config_file in files:
                    self._parse_vite_config_aliases(
                        os.path.join(root, config_file), root, aliases)

        # Default aliases
        if not aliases:
            for root, dirs, files in os.walk(self.output_dir):
                dirs[:] = [d for d in dirs if d not in excluded_dirs]
                if 'src' in dirs:
                    aliases['@'] = os.path.join(root, 'src')
                    aliases['~'] = root
                    break

        return aliases

    def _parse_tsconfig_aliases(self, tsconfig_path: str, base_dir: str,
                                aliases: Dict[str, str]):
        """Parse tsconfig.json and extract path aliases"""
        try:
            with open(tsconfig_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Remove comments
                content = re.sub(
                    r'//.*?\n|/\*.*?\*/', '', content, flags=re.DOTALL)
                tsconfig = json.loads(content)

                if 'compilerOptions' in tsconfig and 'paths' in tsconfig[
                        'compilerOptions']:
                    base_url = tsconfig['compilerOptions'].get('baseUrl', '.')
                    for alias, paths in tsconfig['compilerOptions'][
                            'paths'].items():
                        clean_alias = alias.rstrip('/*')
                        if paths and len(paths) > 0:
                            target = paths[0].rstrip('/*')
                            resolved_target = os.path.normpath(
                                os.path.join(base_dir, base_url, target))
                            if clean_alias not in aliases:
                                aliases[clean_alias] = resolved_target
        except (json.JSONDecodeError, IOError, KeyError):
            pass

    def _parse_vite_config_aliases(self, config_path: str, base_dir: str,
                                   aliases: Dict[str, str]):
        """Parse vite.config and extract path aliases"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                alias_pattern = (
                    r"['\"]([^'\"]+)['\"]\s*:\s*(?:path\.resolve\([^,]+,\s*['\"]"
                    r"([^'\"]+)['\"]\)|['\"]([^'\"]+)['\"])")
                for match in re.finditer(alias_pattern, content):
                    alias_key = match.group(1)
                    target = match.group(2) or match.group(3)
                    if target:
                        target = target.lstrip('/')
                        resolved_target = os.path.join(base_dir, target)
                        if alias_key not in aliases:
                            aliases[alias_key] = resolved_target
        except IOError:
            pass

    def _resolve_alias_path(self, import_path: str) -> Optional[str]:
        """Resolve path alias to actual path"""
        for alias, target in self.path_aliases.items():
            if import_path == alias:
                return target
            elif import_path.startswith(alias + '/'):
                remainder = import_path[len(alias) + 1:]
                return os.path.join(target, remainder)
        return None


class JavaImportParser(BaseImportParser):
    """Parser for Java import statements"""

    def get_file_extensions(self) -> List[str]:
        return ['java']

    def parse(self, code_content: str) -> List[ImportInfo]:
        imports = []

        # Pattern: import [static] package.Class[.*]; or import [static] package.*;
        import_pattern = r'^\s*import\s+(static\s+)?((?:[\w]+\.)*[\w*]+);?'
        for match in re.finditer(import_pattern, code_content, re.MULTILINE):
            info = self._extract_java_import(match)
            if info:
                imports.append(info)

        return imports

    def _extract_java_import(self, match) -> Optional[ImportInfo]:
        """Extract Java import statement"""
        import_path = match.group(2)

        # Resolve to file path
        file_path = self._resolve_java_path(import_path)
        # If not resolved, use import_path as-is (stdlib or external package)
        if not file_path:
            file_path = import_path

        # Determine import type
        if import_path.endswith('.*'):
            import_type = 'namespace'
            items = ['*']
        else:
            import_type = 'named'
            items = [import_path.split('.')[-1]]

        return ImportInfo(
            source_file=file_path,
            raw_statement=match.group(0),
            imported_items=items,
            import_type=import_type)

    def _resolve_java_path(self, import_path: str) -> Optional[str]:
        """Resolve Java import to file path"""
        # Remove .* if present
        if import_path.endswith('.*'):
            import_path = import_path[:-2]

        # Convert package.Class to path/Class.java
        file_path = import_path.replace('.', os.sep) + '.java'
        full_path = os.path.join(self.output_dir, file_path)

        if os.path.exists(full_path):
            return file_path

        return None


class ImportParserFactory:
    """Factory to get appropriate parser for file type"""

    @staticmethod
    def get_parser(file_ext: str, output_dir: str, current_file: str,
                   current_dir: str) -> Optional[BaseImportParser]:
        """Get parser instance for given file extension"""
        parsers = [
            PythonImportParser,
            JavaScriptImportParser,
            JavaImportParser,
        ]

        for parser_class in parsers:
            parser = parser_class(output_dir, current_file, current_dir)
            if file_ext in parser.get_file_extensions():
                return parser

        return None


def parse_imports(current_file: str, code_content: str,
                  output_dir: str) -> List[ImportInfo]:
    """
    Parse imports from code content (main entry point for backward compatibility)

    IMPORTANT: This function filters out external packages and only returns project files.
    External packages (like 'react', 'os', 'typing', 'java.util.List') are NOT included.

    Args:
        current_file: Path to the file being parsed
        code_content: Content of the file
        output_dir: Root directory of the project

    Returns:
        List of ImportInfo objects for project files only (external packages are excluded)
    """
    # Detect file extension
    file_ext = os.path.splitext(current_file)[1].lstrip(
        '.').lower() if current_file else ''
    current_dir = os.path.dirname(current_file) if current_file else '.'

    # Get appropriate parser
    parser = ImportParserFactory.get_parser(file_ext, output_dir, current_file,
                                            current_dir)
    if not parser:
        return []

    # Parse all imports
    all_imports = parser.parse(code_content)

    # Filter out external packages - only keep project files
    project_imports = []
    for imp in all_imports:
        source = imp.source_file
        if not source:
            continue

        # For Python files:
        # - If source is resolved to a file path (contains / or \), it's a project file
        # - If source is still a relative import notation (starts with .), check if it was resolved
        # - Otherwise it's an external package
        if file_ext in ('py', 'pyw'):
            # If it contains path separators or file extension, it's been resolved to a file
            if '/' in source or os.sep in source or source.endswith('.py'):
                project_imports.append(imp)
            # If it starts with . but wasn't resolved (no path sep), it's still relative notation
            elif source.startswith('.'):
                project_imports.append(imp)
            # Otherwise it's an external package (os, sys, typing, numpy, etc.)
            continue

        # For JavaScript/TypeScript/Java: filter external packages
        # External packages: 'react', 'lodash', '@types/react', '@vue/cli', 'java.util.List'
        # They don't start with '.', '/', or contain path separators (except scoped packages)

        # Check if it's a scoped package (starts with @ but file doesn't exist)
        is_scoped_package = source.startswith('@') and not os.path.exists(
            os.path.join(output_dir, source))

        # Check if it's a project file (exists in output_dir)
        full_path = os.path.join(
            output_dir, source) if not os.path.isabs(source) else source
        is_project_file = os.path.exists(full_path)

        # Check if source has common code file extension
        # This helps identify resolved file paths vs package names
        common_extensions = ('.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs',
                             '.java', '.py', '.pyw', '.css', '.scss', '.json')
        has_code_extension = source.endswith(common_extensions)

        # Check if it's an external package (package name without path separators)
        # For Java: java.util.List has dots but no file extension, so it's external
        # For JS: utils.js has extension, so it's a file
        is_external = (
            is_scoped_package
            or (not is_project_file and not has_code_extension
                and not source.startswith('.') and not source.startswith('/')
                and '/' not in source and os.sep not in source))

        if not is_external:
            project_imports.append(imp)

    return project_imports
