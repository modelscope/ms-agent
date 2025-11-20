import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

import json
from ms_agent.utils.logger import get_logger
from ms_agent.utils.utils import extract_by_tag

logger = get_logger()

SUPPORTED_SCRIPT_EXT = ('.py', '.sh', '.js')
SUPPORTED_READ_EXT = ('.md', '.txt', '.py', '.json', '.yaml', '.yml', '.sh',
                      '.js', '.html', '.xml')


def find_skill_dir(root: Union[str, List[str]]) -> List[str]:
    """
    Find all skill directories containing SKILL.md

    Args:
        root: Root directory to search

    Returns:
        list: List of skill directory paths
    """
    if isinstance(root, str):
        root_paths = [Path(root).resolve()]
    else:
        root_paths = [Path(p).resolve() for p in root]

    folders = []

    for root_path in root_paths:
        if not root_path.exists():
            continue
        for item in root_path.rglob('SKILL.md'):
            if item.is_file():
                folders.append(str(item.parent))

    return list(dict.fromkeys(folders))


def extract_implementation(content: str) -> Tuple[str, List[Any]]:
    """
    Extract IMPLEMENTATION content and determine execution scenario.
        e.g. <IMPLEMENTATION> ... </IMPLEMENTATION>

    Args:
        content: Full text containing IMPLEMENTATION tag

    Returns:
        Tuple of (scenario_type, results)
            scenario_type: 'script_execution', 'code_generation', or 'unable_to_execute'
            results: List of parsed results based on scenario
    """
    impl_content: str = extract_by_tag(text=content, tag='IMPLEMENTATION')
    results: List[Any] = []
    # Scenario 1: Script Execution
    try:
        results: List[Dict[str, Any]] = json.loads(impl_content)
    except Exception as e:
        logger.debug(f'Failed to parse IMPLEMENTATION as JSON: {str(e)}')

    if len(results) > 0:
        return 'script_execution', results

    # Scenario 2: No Script Execution, output JavaScript or HTML code blocks
    results: List[str] = re.findall(r'```(html|javascript)\s*\n(.*?)\n```',
                                    impl_content, re.DOTALL)
    if len(results) > 0:
        return 'code_generation', results

    # Scenario 3: Unable to Execute Any Script, provide reason (string)
    return 'unable_to_execute', [impl_content]


def extract_packages_from_code_blocks(text) -> List[str]:
    """
    Extract ```packages ... ``` content from input text.

    Args:
        text (str): Text containing packages code blocks

    Returns:
        list: List of packages, e.g. ['numpy', 'torch', ...]
    """
    pattern = r'```packages\s*\n(.*?)\n```'
    matches = re.findall(pattern, text, re.DOTALL)

    results = []
    for packages_str in matches:
        try:
            cleaned_packages_str = packages_str.strip()
            results.append(cleaned_packages_str)
        except Exception as e:
            raise RuntimeError(
                f'Failed to decode shell command: {e}\nProblematic shell string: {packages_str}'
            )

    results = '\n'.join(results).splitlines()
    return results


def extract_cmd_from_code_blocks(text) -> List[str]:
    """
    Extract ```shell ... ``` code block from text.

    Args:
        text (str): Text containing shell code blocks

    Returns:
        list: List of parsed str
    """
    pattern = r'```shell\s*\n(.*?)\n```'
    matches = re.findall(pattern, text, re.DOTALL)

    results = []
    for shell_str in matches:
        try:
            cleaned_shell_str = shell_str.strip()
            results.append(cleaned_shell_str)
        except Exception as e:
            raise RuntimeError(
                f'Failed to decode shell command: {e}\nProblematic shell string: {shell_str}'
            )

    return results


def copy_with_exec_if_script(src: str, dst: str):
    """
    Copy file from src to dst. If it's a script file, add execute permission.

    Args:
        src (str): Source file path
        dst (str): Destination file path
    """
    shutil.copy2(src, dst)
    # Add execute permission if it's a script file
    if Path(src).suffix in SUPPORTED_SCRIPT_EXT:
        st = os.stat(src)
        os.chmod(dst, st.st_mode | 0o111)
