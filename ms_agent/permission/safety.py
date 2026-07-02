"""SafetyGuard: inner-layer safety baseline that cannot be bypassed by users.

Checks safety rules, file path validation, and shell command path-level
analysis before any tool call is allowed to execute.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from .config import SafetyConfig
from .matcher import PermissionMatcher
from .path_validator import validate_path
from .shell_validator import PathSafetyConfig, SafetyDecision, ShellPathValidator


class SafetyGuard:
    """Inner-layer safety enforcement — not overridable by user configuration."""

    def __init__(
        self,
        config: SafetyConfig,
        allowed_dirs: Sequence[str],
        read_only_dirs: Sequence[str] = (),
        workspace_root: str | None = None,
    ) -> None:
        self._config = config
        self._matcher = PermissionMatcher()
        self._allowed_dirs = list(allowed_dirs)
        self._read_only_dirs = list(read_only_dirs)
        self._sensitive_paths = list(config.sensitive_paths)
        self._workspace_root = workspace_root

        path_safety_cfg = PathSafetyConfig(
            max_command_chars=config.max_command_chars,
            allowed_directories=tuple(self._allowed_dirs),
            read_only_directories=tuple(self._read_only_dirs),
            workspace_root=workspace_root,
        )
        self._shell_validator = ShellPathValidator(
            allowed_dirs=self._allowed_dirs,
            safety_config=path_safety_cfg,
        )

    def check(self, tool_name: str, tool_args: dict[str, Any]) -> SafetyDecision:
        # 1. Generic safety rules
        for rule in self._config.patterns:
            if self._matcher.match_with_content(rule, tool_name, tool_args):
                return SafetyDecision(action='deny', reason=f'Blocked by safety rule: {rule}')

        # 2. Tool-specific checks
        if tool_name.endswith('---shell_executor'):
            command = tool_args.get('command', '')
            return self._shell_validator.check(command)

        if tool_name.endswith('---write_file') or tool_name.endswith('---edit_file'):
            return self._check_file_path(tool_args.get('path', ''), 'write')

        if tool_name.endswith('---read_file'):
            return self._check_file_path(tool_args.get('path', ''), 'read')

        if tool_name.endswith('---grep') or tool_name.endswith('---glob'):
            return self._check_file_path(tool_args.get('path', '.'), 'read')

        # 3. No rule matched → allow
        return SafetyDecision(action='allow', reason='No safety rule matched')

    def _check_file_path(self, path: str, op_type: Literal['read', 'write']) -> SafetyDecision:
        if not path:
            return SafetyDecision(action='deny', reason='Empty file path')

        # Sensitive path check
        if op_type == 'write':
            expanded = os.path.expanduser(path)
            for sensitive in self._sensitive_paths:
                sensitive_expanded = os.path.expanduser(sensitive)
                if fnmatch.fnmatch(expanded, sensitive_expanded):
                    return SafetyDecision(
                        action='deny',
                        reason=f'Write to sensitive path blocked: {path}',
                    )

        cwd = self._workspace_root or os.getcwd()
        result = validate_path(path, cwd, self._allowed_dirs, op_type, read_only_dirs=self._read_only_dirs)
        if not result.allowed:
            return SafetyDecision(action=result.action, reason=result.reason, category=result.category)

        return SafetyDecision(action='allow', reason='Path validation passed')
