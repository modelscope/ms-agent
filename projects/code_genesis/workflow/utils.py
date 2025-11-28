"""Multi-language Import Parser

This module provides utilities to parse import/include statements from various
programming languages and extract detailed information about dependencies.

Supported Languages:
- JavaScript/TypeScript (.js, .ts, .jsx, .tsx, .mjs, .cjs)
- Vue (.vue)
- Python (.py)
- C/C++ (.c, .cpp, .cc, .cxx, .h, .hpp)
- Rust (.rs)
- Java/Kotlin (.java, .kt, .kts)
- Go (.go)

Main Functions:

1. parse_imports_detailed(file_path, code_content) -> List[ImportInfo]
   Returns detailed information including:
   - source_file: Resolved file path
   - imported_items: List of imported symbols/classes/functions
   - import_type: 'named', 'default', 'namespace', or 'side-effect'
   - alias: Import alias if any
   - is_type_only: Whether it's a type-only import (TypeScript)
   - raw_statement: Original import statement

2. parse_imports(file_path, code_content) -> List[str]
   Backward compatible function that returns only file paths

Example Usage:

    from utils import parse_imports_detailed

    code = '''
    import { User, UserRole } from '../models/User';
    import * as utils from './utils';
    import type { Config } from './config';
    '''

    imports = parse_imports_detailed('src/index.ts', code)

    for imp in imports:
        print(f"File: {imp.source_file}")
        print(f"Items: {imp.imported_items}")
        print(f"Type: {imp.import_type}")
        if imp.is_type_only:
            print("  (Type-only import)")

Key Features:
- Handles multi-line import statements
- Extracts specific imported items (classes, functions, variables)
- Resolves relative file paths
- Distinguishes between different import types
- Filters out external packages (npm, pip, etc.)
"""

import json
import os
import re
from dataclasses import dataclass, field
from functools import partial
from typing import Dict, List, Optional, Set


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


stop_words = [
    '\nclass ',
    '\ndef ',
    '\nfunc ',
    '\nfunction ',
    '\npub fn ',
    '\nfn ',
    '\nstruct ',
    '\nenum ',
    '\nexport ',
    '\ninterface ',
    '\ntrait ',
    '\nimpl ',
    '\nmodule ',
    '\ntype ',
    '\npublic class ',
    '\nprivate class ',
    '\nprotected class ',
    '\npublic interface ',
    '\npublic enum ',
    '\npublic struct ',
    '\nabstract class ',
    '\nconst ',
    '\nlet ',
    '\nvar ',
    '\nasync def ',
    '\n@',
]


def parse_imports_detailed(current_file: str, code_content: str,
                           output_dir: str) -> List[ImportInfo]:
    """Parse imports and return detailed information about what's imported from each file"""
    imports = []
    current_dir = os.path.dirname(current_file) if current_file else '.'

    # Detect file extension
    file_ext = os.path.splitext(current_file)[1].lstrip(
        '.').lower() if current_file else ''

    # Load path aliases from config files
    path_aliases = _load_path_aliases(output_dir)

    # Import patterns for different languages with detailed extraction
    # Pattern structure: (regex_pattern, file_extensions, resolver_function, regex_flags)
    patterns = [
        # Python: from ... import ...
        (r'^\s*from\s+([\w.]+)\s+import\s+([^\n]+)', ['py'],
         _extract_python_import, re.MULTILINE),
        # Python: import ...
        (r'^\s*import\s+([\w.,\s]+)', ['py'], _extract_python_import_simple,
         re.MULTILINE),

        # JavaScript/TypeScript/Vue: import ... from '...'
        # Match: import { A, B } from 'path' or import A from 'path' or import * as A from 'path'
        (r"import\s+(type\s+)?(?:(\{[^}]*\}|\*\s+as\s+\w+|\w+)\s*,?\s*)*from\s+['\"]([^'\"]+)['\"]",
         ['js', 'ts', 'jsx', 'tsx', 'mjs', 'cjs', 'vue'],
         partial(_extract_js_import,
                 output_dir=output_dir,
                 path_aliases=path_aliases), re.MULTILINE | re.DOTALL),
        # Match: import 'path' (side-effect)
        (r"^\s*import\s+['\"]([^'\"]+)['\"]",
         ['js', 'ts', 'jsx', 'tsx', 'mjs', 'cjs', 'vue'],
         partial(_extract_js_side_effect,
                 output_dir=output_dir,
                 path_aliases=path_aliases), re.MULTILINE),
        # Match: export ... from 'path'
        (r"export\s+(type\s+)?(?:(\{[^}]*\}|\*(?:\s+as\s+\w+)?)\s+)?from\s+['\"]([^'\"]+)['\"]",
         ['js', 'ts', 'jsx', 'tsx', 'mjs', 'cjs', 'vue'],
         partial(_extract_js_export,
                 output_dir=output_dir,
                 path_aliases=path_aliases), re.MULTILINE | re.DOTALL),

        # C/C++: #include
        (r'^\s*#include\s+"([^"]+)"', ['c', 'cpp', 'cc', 'cxx', 'h', 'hpp'],
         _extract_c_include, re.MULTILINE),

        # Rust: use
        (r'^\s*use\s+(?:crate::)?([\w:]+)(?:::\{([^}]+)\})?', ['rs'],
         _extract_rust_use, re.MULTILINE),

        # Java/Kotlin: import
        (r'^\s*import\s+(static\s+)?([\w.]+(?:\.\*)?)', ['java', 'kt', 'kts'],
         _extract_java_import, re.MULTILINE),

        # Go: import
        (r'^\s*import\s+(?:(\w+)\s+)?"([^"]+)"', ['go'], _extract_go_import,
         re.MULTILINE),
    ]

    # Process each pattern on the entire content
    for pattern, extensions, extractor, flags in patterns:
        # Skip if file extension doesn't match
        if file_ext and file_ext not in extensions:
            continue

        # Find all matches in the entire content
        for match in re.finditer(pattern, code_content, flags):
            import_info = extractor(match, current_dir, current_file,
                                    code_content)
            if import_info:
                if isinstance(import_info, list):
                    imports.extend(import_info)
                else:
                    imports.append(import_info)

    return imports


def parse_imports(current_file: str, code_content: str,
                  output_dir: str) -> List[ImportInfo]:
    """Parse imports and return list of file paths (for backward compatibility)"""
    return parse_imports_detailed(current_file, code_content, output_dir)


# ============================================================================
# Path Alias Resolution
# ============================================================================


def _load_path_aliases(output_dir: str) -> Dict[str, str]:
    """Load path aliases from config files (tsconfig.json, vite.config.js, etc.)
    
    Uses os.walk to search in output_dir and subdirectories.
    """
    aliases = {}
    config_files_found = []
    
    # Excluded directories
    excluded_dirs = {'node_modules', 'dist', 'build', '.git', '.next', 'out', '__pycache__'}
    
    # Walk through directory tree to find config files
    for root, dirs, files in os.walk(output_dir):
        # Filter out excluded directories
        dirs[:] = [d for d in dirs if d not in excluded_dirs]
        
        # Look for tsconfig.json
        if 'tsconfig.json' in files:
            tsconfig_path = os.path.join(root, 'tsconfig.json')
            _parse_tsconfig_aliases(tsconfig_path, root, aliases)
            config_files_found.append(tsconfig_path)
        
        # Look for vite config files
        for config_file in ['vite.config.js', 'vite.config.ts', 'vite.config.mjs']:
            if config_file in files:
                config_path = os.path.join(root, config_file)
                _parse_vite_config_aliases(config_path, root, aliases)
                config_files_found.append(config_path)
    
    # Common default aliases if not found in config
    if not aliases:
        # Try common conventions
        for root, dirs, files in os.walk(output_dir):
            dirs[:] = [d for d in dirs if d not in excluded_dirs]
            if 'src' in dirs:
                src_dir = os.path.join(root, 'src')
                aliases['@'] = src_dir
                aliases['~'] = root
                break
    
    return aliases


def _parse_tsconfig_aliases(tsconfig_path: str, base_dir: str, aliases: Dict[str, str]):
    """Parse tsconfig.json and extract path aliases"""
    try:
        with open(tsconfig_path, 'r', encoding='utf-8') as f:
            # Remove comments from JSON (simple approach)
            content = f.read()
            content = re.sub(r'//.*?\n|/\*.*?\*/', '', content, flags=re.DOTALL)
            tsconfig = json.loads(content)
            
            if 'compilerOptions' in tsconfig and 'paths' in tsconfig['compilerOptions']:
                base_url = tsconfig['compilerOptions'].get('baseUrl', '.')
                for alias, paths in tsconfig['compilerOptions']['paths'].items():
                    # Remove /* suffix if present
                    clean_alias = alias.rstrip('/*')
                    if paths and len(paths) > 0:
                        # Take first path and remove /* suffix
                        target = paths[0].rstrip('/*')
                        # Resolve relative to baseUrl and base_dir
                        resolved_target = os.path.normpath(
                            os.path.join(base_dir, base_url, target)
                        )
                        # Only add if not already defined (first found wins)
                        if clean_alias not in aliases:
                            aliases[clean_alias] = resolved_target
    except (json.JSONDecodeError, IOError, KeyError):
        pass


def _parse_vite_config_aliases(config_path: str, base_dir: str, aliases: Dict[str, str]):
    """Parse vite.config.js/ts and extract path aliases"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # Simple regex to extract alias definitions
            # Matches: '@': '/src' or '@': path.resolve(__dirname, 'src')
            alias_pattern = r"['\"]([^'\"]+)['\"]\s*:\s*(?:path\.resolve\([^,]+,\s*['\"]([^'\"]+)['\"]\)|['\"]([^'\"]+)['\"])"
            for match in re.finditer(alias_pattern, content):
                alias_key = match.group(1)
                target = match.group(2) or match.group(3)
                if target:
                    # Remove leading slash if present
                    target = target.lstrip('/')
                    resolved_target = os.path.join(base_dir, target)
                    # Only add if not already defined (first found wins)
                    if alias_key not in aliases:
                        aliases[alias_key] = resolved_target
    except IOError:
        pass


def _resolve_alias_path(import_path: str, path_aliases: Dict[str, str]) -> Optional[str]:
    """Resolve path alias to actual path"""
    for alias, target in path_aliases.items():
        # Check if import starts with alias
        if import_path == alias:
            return target
        elif import_path.startswith(alias + '/'):
            # Replace alias with target path
            remainder = import_path[len(alias) + 1:]
            return os.path.join(target, remainder)
    return None


# ============================================================================
# Detailed Import Extractors (return ImportInfo objects)
# ============================================================================


def _extract_js_import(match, current_dir, current_file, code_content,
                       output_dir, path_aliases):
    """Extract JavaScript/TypeScript import details"""
    full_match = match.group(0)
    is_type_only = match.group(1) is not None  # 'type' keyword
    import_path = match.group(3)

    # Try to resolve path alias first
    resolved_alias = _resolve_alias_path(import_path, path_aliases)
    if resolved_alias:
        source_file = _resolve_js_path_from_absolute(resolved_alias, output_dir)
    elif import_path.startswith('.') or import_path.startswith('/'):
        # Relative or absolute path
        source_file = _resolve_js_path(import_path, current_dir, output_dir)
    else:
        # External package, skip
        return None

    # Extract imported items
    imported_items = []
    import_type = 'named'
    alias = None

    # Parse the import clause (everything before 'from')
    import_clause = full_match.split('from')[0].replace('import', '').strip()
    if is_type_only:
        import_clause = import_clause.replace('type', '').strip()

    if import_clause.startswith('{') and import_clause.endswith('}'):
        # Named imports: import { A, B as C } from '...'
        import_type = 'named'
        items_str = import_clause[1:-1]  # Remove { }
        for item in items_str.split(','):
            item = item.strip()
            if ' as ' in item:
                original, alias_name = item.split(' as ')
                imported_items.append(original.strip())
            elif item:
                imported_items.append(item)
    elif import_clause.startswith('*'):
        # Namespace import: import * as name from '...'
        import_type = 'namespace'
        imported_items = ['*']
        if ' as ' in import_clause:
            alias = import_clause.split(' as ')[1].strip()
    elif import_clause:
        # Default import: import Name from '...'
        import_type = 'default'
        imported_items = [import_clause.split(',')[0].strip()]

    return ImportInfo(
        source_file=source_file,
        raw_statement=full_match,
        imported_items=imported_items,
        import_type=import_type,
        alias=alias,
        is_type_only=is_type_only)


def _extract_js_side_effect(match, current_dir, current_file, code_content,
                            output_dir, path_aliases):
    """Extract side-effect import: import './file'"""
    import_path = match.group(1)

    # Try to resolve path alias first
    resolved_alias = _resolve_alias_path(import_path, path_aliases)
    if resolved_alias:
        source_file = _resolve_js_path_from_absolute(resolved_alias, output_dir)
    elif import_path.startswith('.') or import_path.startswith('/'):
        source_file = _resolve_js_path(import_path, current_dir, output_dir)
    else:
        return None

    return ImportInfo(
        source_file=source_file,
        raw_statement=match.group(0),
        imported_items=[],
        import_type='side-effect')


def _extract_js_export(match, current_dir, current_file, code_content,
                       output_dir, path_aliases):
    """Extract re-export: export { A } from './file'"""
    is_type_only = match.group(1) is not None
    export_clause = match.group(2)
    import_path = match.group(3)

    # Try to resolve path alias first
    resolved_alias = _resolve_alias_path(import_path, path_aliases)
    if resolved_alias:
        source_file = _resolve_js_path_from_absolute(resolved_alias, output_dir)
    elif import_path.startswith('.') or import_path.startswith('/'):
        source_file = _resolve_js_path(import_path, current_dir, output_dir)
    else:
        return None

    imported_items = []
    import_type = 'named'
    alias = None

    if export_clause:
        if export_clause.startswith('{'):
            items_str = export_clause[1:-1] if export_clause.endswith(
                '}') else export_clause[1:]
            for item in items_str.split(','):
                item = item.strip()
                if ' as ' in item:
                    imported_items.append(item.split(' as ')[0].strip())
                elif item:
                    imported_items.append(item)
        elif '*' in export_clause:
            import_type = 'namespace'
            imported_items = ['*']
            if ' as ' in export_clause:
                alias = export_clause.split(' as ')[1].strip()

    return ImportInfo(
        source_file=source_file,
        raw_statement=match.group(0),
        imported_items=imported_items,
        import_type=import_type,
        alias=alias,
        is_type_only=is_type_only)


def _resolve_js_path(import_path, current_dir, output_dir):
    """Resolve JavaScript/TypeScript import path to file"""
    if import_path.startswith('/'):
        resolved = import_path.lstrip('/')
    else:
        resolved = os.path.join(current_dir, import_path)
        resolved = os.path.normpath(resolved)

    # Try different extensions
    extensions = ['.ts', '.tsx', '.js', '.jsx', '.vue', '.mjs', '.cjs', '.json', '']
    for ext in extensions:
        path_with_ext = resolved + ext
        if os.path.exists(path_with_ext):
            return path_with_ext

    # Try as directory with index file
    for index_file in ['index.ts', 'index.tsx', 'index.js', 'index.jsx', 'index.vue']:
        index_path = os.path.join(resolved, index_file)
        if os.path.exists(index_path):
            return index_path

    if '.' not in resolved[1:]:
        exts = ['.ts', '.tsx', '.js', '.jsx']
        for ext in exts:
            file = os.path.join(output_dir, resolved + ext)
            if os.path.exists(file):
                return resolved + ext
        return resolved
    else:
        return resolved


def _resolve_js_path_from_absolute(resolved_path, output_dir):
    """Resolve JavaScript/TypeScript path from already-resolved absolute path"""
    # Try different extensions
    extensions = ['.ts', '.tsx', '.js', '.jsx', '.vue', '.mjs', '.cjs', '.json', '']
    for ext in extensions:
        path_with_ext = resolved_path + ext
        if os.path.exists(path_with_ext):
            return path_with_ext

    # Try as directory with index file
    for index_file in ['index.ts', 'index.tsx', 'index.js', 'index.jsx', 'index.vue']:
        index_path = os.path.join(resolved_path, index_file)
        if os.path.exists(index_path):
            return index_path

    return resolved_path


def _extract_python_import(match, current_dir, current_file, code_content):
    """Extract Python 'from ... import ...' statement"""
    module_path = match.group(1)
    imports_str = match.group(2).strip()

    # Parse imported items
    imported_items = []
    for item in imports_str.split(','):
        item = item.strip()
        if ' as ' in item:
            imported_items.append(item.split(' as ')[0].strip())
        elif item and item != '*':
            imported_items.append(item)
        elif item == '*':
            imported_items = ['*']
            break

    # Resolve file path
    file_path = _resolve_python_path(module_path, current_dir)
    if not file_path:
        return None

    return ImportInfo(
        source_file=file_path,
        raw_statement=match.group(0),
        imported_items=imported_items,
        import_type='namespace' if '*' in imported_items else 'named')


def _extract_python_import_simple(match, current_dir, current_file,
                                  code_content):
    """Extract Python 'import ...' statement"""
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

        file_path = _resolve_python_path(module, current_dir)
        if file_path:
            results.append(
                ImportInfo(
                    source_file=file_path,
                    raw_statement=f'import {module}',
                    imported_items=[module.split('.')[-1]],
                    import_type='default',
                    alias=alias))

    return results if results else None


def _resolve_python_path(module_path, current_dir):
    """Resolve Python module to file path"""
    module_file_path = module_path.replace('.', os.sep)

    # Try as package
    package_init = os.path.normpath(
        os.path.join(current_dir, module_file_path, '__init__.py'))
    if os.path.exists(package_init):
        return package_init

    # Try as module
    module_file = os.path.normpath(
        os.path.join(current_dir, module_file_path + '.py'))
    if os.path.exists(module_file):
        return module_file

    return None


def _extract_c_include(match, current_dir, current_file, code_content):
    """Extract C/C++ #include statement"""
    include_path = match.group(1)
    resolved = os.path.normpath(os.path.join(current_dir, include_path))

    if not os.path.exists(resolved):
        return None

    return ImportInfo(
        source_file=resolved,
        raw_statement=match.group(0),
        imported_items=['*'],
        import_type='namespace')


def _extract_rust_use(match, current_dir, current_file, code_content):
    """Extract Rust 'use' statement"""
    use_path = match.group(1)
    items_group = match.group(2)

    # Resolve file path
    module_path = use_path.replace('::', os.sep)
    resolved = os.path.normpath(os.path.join(current_dir, module_path + '.rs'))

    if not os.path.exists(resolved):
        return None

    # Parse imported items
    imported_items = []
    if items_group:
        # use module::{A, B, C}
        for item in items_group.split(','):
            imported_items.append(item.strip())
    else:
        # use module or use module::item
        imported_items = [use_path.split('::')[-1]]

    return ImportInfo(
        source_file=resolved,
        raw_statement=match.group(0),
        imported_items=imported_items,
        import_type='named')


def _extract_java_import(match, current_dir, current_file, code_content):
    """Extract Java/Kotlin import statement"""
    import_path = match.group(2)

    # Check if it's a wildcard import
    is_wildcard = import_path.endswith('.*')
    if is_wildcard:
        import_path = import_path[:-2]

    # Convert to file path
    parts = import_path.split('.')
    class_name = parts[-1]
    package_path = os.sep.join(parts[:-1]) if len(parts) > 1 else ''

    # Try .java and .kt
    for ext in ['.java', '.kt', '.kts']:
        if package_path:
            resolved = os.path.normpath(
                os.path.join(current_dir, package_path, class_name + ext))
        else:
            resolved = os.path.normpath(
                os.path.join(current_dir, class_name + ext))

        if os.path.exists(resolved):
            return ImportInfo(
                source_file=resolved,
                raw_statement=match.group(0),
                imported_items=['*'] if is_wildcard else [class_name],
                import_type='namespace' if is_wildcard else 'named')

    return None


def _extract_go_import(match, current_dir, current_file, code_content):
    """Extract Go import statement"""
    alias = match.group(1)  # May be None
    import_path = match.group(2)

    # Skip external packages
    if '.' in import_path.split('/')[0]:
        return None

    package_name = import_path.split('/')[-1]

    return ImportInfo(
        source_file=import_path,
        raw_statement=match.group(0),
        imported_items=[package_name],
        import_type='default',
        alias=alias)


# ============================================================================
# Legacy Path Resolvers (for backward compatibility)
# ============================================================================


def main():
    """Test cases for parse_imports_detailed function"""
    print('=' * 80)
    print('Testing parse_imports_detailed function')
    print('=' * 80)

    # Test Vue file imports with detailed information
    print('\n[Test 1] Vue File Imports')
    vue_code = '''<template>
  <div class=\"document-content\">
    <!-- 文档头部 -->
    <div class=\"document-content__header\">
      <!-- 面包屑导航 -->
      <el-breadcrumb separator=\"/\">
        <el-breadcrumb-item :to=\"{ path: '/documents' }\">
          文档库
        </el-breadcrumb-item>
        <el-breadcrumb-item v-if=\"document?.category\">
          {{ getCategoryName(document.category) }}
        </el-breadcrumb-item>
        <el-breadcrumb-item>
          {{ document?.title || '加载中...' }}
        </el-breadcrumb-item>
      </el-breadcrumb>

      <!-- 文档标题 -->
      <h1 class=\"document-content__title\">
        {{ document?.title }}
      </h1>

      <!-- 文档元信息 -->
      <div class=\"document-content__meta\">
        <div class=\"document-content__meta-left\">
          <span class=\"document-content__meta-item\">
            <el-icon><User /></el-icon>
            {{ document?.authorName }}
          </span>
          <span class=\"document-content__meta-item\">
            <el-icon><Calendar /></el-icon>
            {{ formatDate(document?.updatedAt) }}
          </span>
          <span class=\"document-content__meta-item\">
            <el-icon><View /></el-icon>
            {{ document?.views || 0 }} 次浏览
          </span>
          <span class=\"document-content__meta-item\">
            <el-icon><Star /></el-icon>
            {{ document?.likes || 0 }} 点赞
          </span>
        </div>

        <div class=\"document-content__meta-right\">
          <!-- 点赞按钮 -->
          <el-button
            :type=\"isLiked ? 'primary' : 'default'\"
            :icon=\"isLiked ? StarFilled : Star\"
            size=\"small\"
            @click=\"handleLike\"
          >
            {{ isLiked ? '已点赞' : '点赞' }}
          </el-button>

          <!-- 收藏按钮 -->
          <el-button
            :type=\"isCollected ? 'warning' : 'default'\"
            :icon=\"isCollected ? CollectionFilled : Collection\"
            size=\"small\"
            @click=\"handleCollect\"
          >
            {{ isCollected ? '已收藏' : '收藏' }}
          </el-button>

          <!-- 分享按钮 -->
          <el-dropdown trigger=\"click\" @command=\"handleShare\">
            <el-button :icon=\"Share\" size=\"small\">
              分享
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command=\"copy\">
                  <el-icon><Link /></el-icon>
                  复制链接
                </el-dropdown-item>
                <el-dropdown-item command=\"twitter\">
                  <el-icon><Share /></el-icon>
                  分享到 Twitter
                </el-dropdown-item>
                <el-dropdown-item command=\"facebook\">
                  <el-icon><Share /></el-icon>
                  分享到 Facebook
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <!-- 编辑按钮（仅作者可见） -->
          <el-button
            v-if=\"canEdit\"
            :icon=\"Edit\"
            size=\"small\"
            type=\"primary\"
            @click=\"handleEdit\"
          >
            编辑
          </el-button>
        </div>
      </div>

      <!-- 文档标签 -->
      <div v-if=\"document?.tags && document.tags.length > 0\" class=\"document-content__tags\">
        <Tag
          v-for=\"tag in document.tags\"
          :key=\"tag\"
          :label=\"tag\"
          type=\"primary\"
          size=\"small\"
          plain
          clickable
          @click=\"handleTagClick(tag)\"
        />
      </div>

      <!-- 文档描述 -->
      <div v-if=\"document?.description\" class=\"document-content__description\">
        {{ document.description }}
      </div>
    </div>

    <!-- 文档内容 -->
    <div class=\"document-content__body\">
      <MarkdownPreview
        :content=\"document?.content || ''\"
        :loading=\"loading\"
        :show-toolbar=\"true\"
        :show-copy-button=\"true\"
        :show-export-button=\"true\"
        :show-fullscreen-button=\"true\"
        :show-word-count=\"true\"
        :enable-code-highlight=\"true\"
        :enable-table=\"true\"
        :enable-task-list=\"true\"
        :enable-emoji=\"true\"
        :auto-link=\"true\"
        :scrollable=\"true\"
        :bordered=\"false\"
        empty-text=\"暂无内容\"
        @copy=\"handleCopy\"
        @export=\"handleExport\"
        @link-click=\"handleLinkClick\"
      />
    </div>

    <!-- 文档底部 -->
    <div class=\"document-content__footer\">
      <!-- 改进建议 -->
      <div class=\"document-content__suggestion\">
        <el-alert
          type=\"info\"
          :closable=\"false\"
          show-icon
        >
          <template #title>
            <span>发现文档问题？</span>
            <el-button
              type=\"primary\"
              text
              size=\"small\"
              @click=\"showSuggestionDialog = true\"
            >
              提交改进建议
            </el-button>
          </template>
        </el-alert>
      </div>

      <!-- 相关文档 -->
      <div v-if=\"relatedDocuments.length > 0\" class=\"document-content__related\">
        <h3 class=\"document-content__related-title\">
          <el-icon><Document /></el-icon>
          相关文档
        </h3>
        <div class=\"document-content__related-list\">
          <DocumentCard
            v-for=\"doc in relatedDocuments\"
            :key=\"doc.id\"
            :document=\"doc\"
            @click=\"handleRelatedDocClick(doc)\"
          />
        </div>
      </div>

      <!-- 上一篇/下一篇 -->
      <div class=\"document-content__navigation\">
        <el-button
          v-if=\"prevDocument\"
          :icon=\"ArrowLeft\"
          @click=\"handleNavigation(prevDocument.id)\"
        >
          上一篇: {{ prevDocument.title }}
        </el-button>
        <div class=\"document-content__navigation-spacer\"></div>
        <el-button
          v-if=\"nextDocument\"
          @click=\"handleNavigation(nextDocument.id)\"
        >
          下一篇: {{ nextDocument.title }}
          <el-icon class=\"el-icon--right\"><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- 改进建议对话框 -->
    <el-dialog
      v-model=\"showSuggestionDialog\"
      title=\"提交改进建议\"
      width=\"600px\"
      :close-on-click-modal=\"false\"
    >
      <el-form
        ref=\"suggestionFormRef\"
        :model=\"suggestionForm\"
        :rules=\"suggestionRules\"
        label-width=\"100px\"
      >
        <el-form-item label=\"建议类型\" prop=\"type\">
          <el-select
            v-model=\"suggestionForm.type\"
            placeholder=\"请选择建议类型\"
            style=\"width: 100%\"
          >
            <el-option label=\"内容错误\" value=\"error\" />
            <el-option label=\"内容补充\" value=\"addition\" />
            <el-option label=\"格式优化\" value=\"format\" />
            <el-option label=\"其他建议\" value=\"other\" />
          </el-select>
        </el-form-item>

        <el-form-item label=\"建议内容\" prop=\"content\">
          <el-input
            v-model=\"suggestionForm.content\"
            type=\"textarea\"
            :rows=\"6\"
            placeholder=\"请详细描述您的建议...\"
            maxlength=\"500\"
            show-word-limit
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click=\"showSuggestionDialog = false\">
          取消
        </el-button>
        <el-button
          type=\"primary\"
          :loading=\"submittingSuggestion\"
          @click=\"handleSubmitSuggestion\"
        >
          提交
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang=\"ts\">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import {
  User,
  Calendar,
  View,
  Star,
  StarFilled,
  Collection,
  CollectionFilled,
  Share,
  Link,
  Edit,
  Document,
  ArrowLeft,
  ArrowRight,
} from '@element-plus/icons-vue';
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus';
import { useAuthStore } from '../../stores/auth.ts';
import { useCollectionStore } from '../../stores/collection.ts';
import MarkdownPreview from '../../components/editor/MarkdownPreview.vue';
import Tag from '../../components/common/Tag.vue';
import DocumentCard from './DocumentCard.vue';
import {
  getDocument,
  likeDocument,
  unlikeDocument,
  getRelatedDocuments,
  submitDocumentSuggestion,
  checkDocumentPermission,
  getDocumentCategories,
} from '../../api/document.ts';
import type { Document as DocumentType, DocumentCategory } from '../../api/document.ts';
import { addCollection, removeCollection, checkCollection } from '../../api/collection.ts';

/**
 * 文档内容组件属性
 */
'''
    result = parse_imports_detailed('frontend/src/views/documents/DocumentContent.vue', vue_code,
                                    'output')
    print('Current file: frontend/src/views/documents/DocumentContent.vue')
    print(f'\nDetected {len(result)} imports:')
    for imp in result:
        print(f'\n  File: {imp.source_file}')
        print(f'    Type: {imp.import_type}')
        print(f'    Items: {imp.imported_items}')
        print(f'    Alias: {imp.alias}')
        print(f'    Type-only: {imp.is_type_only}')
        print(f'    Statement: {imp.raw_statement[:60]}...')

    # Test backward compatibility
    print('\n' + '=' * 80)
    print('[Test 2] TypeScript File Imports')
    ts_code = '''
import { User, Profile } from '../models/User';
import type { Config } from './config';
import * as utils from '@/utils/helper';
import './styles.css';
export { Button } from '../components/Button';
'''
    simple_result = parse_imports('src/index.ts', ts_code, 'output')
    print('parse_imports() returns list of ImportInfo objects:')
    for info in simple_result:
        print(f'  - {info}')

    print('\n' + '=' * 80)
    print('All tests completed!')
    print('=' * 80)


if __name__ == '__main__':
    main()
