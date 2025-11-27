"""
Prompt 注入器实现
读取tech_spec.md和tests/目录，构造"元指令"注入到代码生成流程
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional


class PromptInjector:
    """
    Prompt 注入器
    读取tech_spec.md和tests/目录，构造"元指令"，包含遵循spec和通过test的指示
    """
    
    def __init__(self):
        pass

    def inject(self, spec_path: Path, test_dir: Path, base_query: str = "") -> str:
        """
        构造包含技术规范和测试用例的"元指令"
        
        Args:
            spec_path: 技术规范文件路径 (tech_spec.md)
            test_dir: 测试文件目录路径 (tests/)
            base_query: 原始查询或基础提示词
            
        Returns:
            构造的完整prompt，包含"请遵循tech_spec.md并使tests/中的测试通过"的指令
        """
        spec_path = Path(spec_path)
        test_dir = Path(test_dir)
        
        # 读取技术规范内容
        if not spec_path.exists():
            raise FileNotFoundError(f"技术规范文件不存在: {spec_path}")
        
        with open(spec_path, 'r', encoding='utf-8') as f:
            spec_content = f.read()
        
        # 读取测试目录中的测试文件
        test_files_content = []
        if test_dir.exists():
            for test_file in test_dir.glob('*.py'):
                with open(test_file, 'r', encoding='utf-8') as f:
                    test_content = f.read()
                    test_files_content.append(f"文件: {test_file.name}\n{test_content}")
        
        # 构造元指令
        meta_instruction = f"""
你是一个高级软件工程师，需要根据以下技术规范实现功能。

## 原始需求
{base_query}

## 技术规范
{spec_content}

## 测试要求
以下是需要通过的测试用例，你生成的代码必须能够通过这些测试：
"""
        
        if test_files_content:
            for test_content in test_files_content:
                meta_instruction += f"\n{test_content}\n"
        else:
            meta_instruction += "\n当前没有提供具体的测试用例，但请确保代码质量并符合技术规范。\n"
        
        meta_instruction += """
## 实现要求
1. 严格按照技术规范实现功能
2. 确保生成的代码能通过上述测试用例
3. 保持代码结构清晰，遵循最佳实践
4. 如果有依赖库要求，请按规范中指定的版本安装
5. 代码应具有适当的错误处理和边界条件处理
"""
        
        return meta_instruction
    
    def inject_with_error_feedback(self, spec_path: Path, test_dir: Path, 
                                   base_query: str, error_log: str = "") -> str:
        """
        构造包含错误反馈的"元指令"
        
        Args:
            spec_path: 技术规范文件路径
            test_dir: 测试文件目录路径
            base_query: 原始查询或基础提示词
            error_log: 错误日志，用于指导修复
        
        Returns:
            包含错误修复指导的完整prompt
        """
        base_prompt = self.inject(spec_path, test_dir, base_query)
        
        if error_log:
            error_feedback = f"""
## 错误修复指导
上一次生成的代码未能通过测试，以下是错误信息：
{error_log}

请基于错误信息修复代码，特别注意：
1. 检查语法错误
2. 确保逻辑符合技术规范
3. 修复导致测试失败的具体问题
"""
            return base_prompt + error_feedback
        else:
            return base_prompt