"""
测试运行器实现
在指定目录下运行pytest，捕获输出和错误日志，实现错误日志提取和反馈机制
"""
import os
import subprocess
import sys
import json
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List


class TestRunner:
    """
    测试运行器
    在指定目录下运行pytest，捕获输出和错误，解析测试结果
    """
    
    def __init__(self, timeout: int = 120):
        """
        初始化TestRunner
        
        Args:
            timeout: 测试执行的超时时间（秒）
        """
        self.timeout = timeout

    def run_tests(self, tests_dir: Path, work_dir: Optional[Path] = None) -> Dict[str, Any]:
        """
        运行测试目录中的pytest测试
        
        Args:
            tests_dir: 测试文件目录路径
            work_dir: 工作目录路径（代码源文件所在目录，用于添加到Python路径）
            
        Returns:
            包含测试结果的字典
        """
        tests_dir = Path(tests_dir)
        
        if not tests_dir.exists():
            return {
                'success': False,
                'exit_code': -1,
                'stdout': '',
                'stderr': f'Tests directory does not exist: {tests_dir}',
                'parsed_errors': []
            }
        
        # 准备运行pytest的命令
        cmd = [sys.executable, '-m', 'pytest', str(tests_dir), '-v']
        
        # 设置环境，将工作目录添加到Python路径
        env = os.environ.copy()
        if work_dir:
            work_dir = Path(work_dir)
            # 将工作目录添加到PYTHONPATH，以便测试可以导入源代码
            if 'PYTHONPATH' in env:
                env['PYTHONPATH'] = f"{work_dir}:{env['PYTHONPATH']}"
            else:
                env['PYTHONPATH'] = str(work_dir)
        
        try:
            # 运行pytest
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                cwd=work_dir or tests_dir.parent
            )
            
            parsed_errors = self._parse_pytest_output(result.stdout, result.stderr)
            
            return {
                'success': result.returncode == 0,
                'exit_code': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'parsed_errors': parsed_errors
            }
            
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'exit_code': -1,
                'stdout': '',
                'stderr': f'Tests execution timed out after {self.timeout} seconds',
                'parsed_errors': []
            }
        except Exception as e:
            return {
                'success': False,
                'exit_code': -1,
                'stdout': '',
                'stderr': str(e),
                'parsed_errors': []
            }

    def _parse_pytest_output(self, stdout: str, stderr: str) -> List[Dict[str, Any]]:
        """
        解析pytest输出，提取关键错误信息
        
        Args:
            stdout: pytest的标准输出
            stderr: pytest的错误输出
            
        Returns:
            解析后的错误信息列表
        """
        errors = []
        
        # 解析输出以提取错误信息
        output = stdout + stderr
        
        # 查找测试失败的相关信息
        lines = output.split('\n')
        current_error = None
        
        for line in lines:
            # 检查是否是错误行
            if 'FAIL' in line and '::' in line:
                # 这是一个失败的测试
                parts = line.split()
                for part in parts:
                    if '::' in part and 'FAIL' not in part:
                        test_name = part
                        errors.append({
                            'type': 'test_failure',
                            'test_name': test_name,
                            'message': line.strip()
                        })
                        break
            elif 'ERROR' in line and '::' in line:
                # 这是一个错误的测试
                parts = line.split()
                for part in parts:
                    if '::' in part and 'ERROR' not in part:
                        test_name = part
                        errors.append({
                            'type': 'test_error',
                            'test_name': test_name,
                            'message': line.strip()
                        })
                        break
            elif line.strip().startswith('E   '):
                # 这是具体的错误详情
                if errors:
                    errors[-1]['detailed_error'] = line.strip()[4:]  # 移除 'E   ' 前缀
        
        # 尝试解析Python异常
        in_traceback = False
        for i, line in enumerate(lines):
            if 'Traceback' in line and '(most recent call last)' in line:
                in_traceback = True
                continue
            
            if in_traceback:
                if line.strip().startswith('File "'):
                    # 提取异常信息
                    error_info = {
                        'type': 'exception',
                        'traceback': []
                    }
                    
                    # 收集整个traceback
                    j = i
                    while j < len(lines) and not (lines[j].strip() == '' and j > i + 5):
                        if j >= len(lines):
                            break
                        error_info['traceback'].append(lines[j])
                        if j > i and not lines[j].strip().startswith(' ') and not lines[j].strip().startswith('File "'):
                            # 可能是异常类型和消息
                            if ':' in lines[j]:
                                parts = lines[j].split(':', 1)
                                error_info['exception_type'] = parts[0].strip()
                                error_info['exception_message'] = parts[1].strip()
                            break
                        j += 1
                    
                    errors.append(error_info)
                    in_traceback = False
        
        return errors

    def run_tests_with_feedback(self, work_dir: Path, error_log_path: Optional[Path] = None) -> Dict[str, Any]:
        """
        运行测试并生成反馈信息用于修复
        
        Args:
            work_dir: 工作目录，包含src/和tests/子目录
            error_log_path: 用于保存错误日志的路径（可选）
            
        Returns:
            包含测试结果和反馈信息的字典
        """
        work_dir = Path(work_dir)
        tests_dir = work_dir / 'tests'
        src_dir = work_dir / 'src'
        
        # 运行测试
        result = self.run_tests(tests_dir, src_dir)
        
        # 生成反馈信息
        feedback = {
            'test_results': result,
            'should_retry': not result['success'],
            'error_summary': self._generate_error_summary(result['parsed_errors'])
        }
        
        # 如果提供了错误日志路径，保存错误信息
        if error_log_path and result['parsed_errors']:
            with open(error_log_path, 'w', encoding='utf-8') as f:
                json.dump(result['parsed_errors'], f, indent=2, ensure_ascii=False)
        
        return feedback

    def _generate_error_summary(self, parsed_errors: List[Dict[str, Any]]) -> str:
        """
        生成错误摘要，用于指导代码修复
        
        Args:
            parsed_errors: 解析后的错误列表
            
        Returns:
            错误摘要字符串
        """
        if not parsed_errors:
            return "所有测试通过。"
        
        summary = "测试失败摘要：\n"
        for error in parsed_errors:
            if error['type'] == 'test_failure':
                summary += f"- 测试失败: {error['test_name']} - {error['message']}\n"
            elif error['type'] == 'test_error':
                summary += f"- 测试错误: {error['test_name']} - {error['message']}\n"
            elif error['type'] == 'exception':
                summary += f"- 异常: {error.get('exception_type', 'Unknown')} - {error.get('exception_message', 'No message')}\n"
        
        return summary