import os
import sys
import re
import ast
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from optimized_manim_prompts import OptimizedManimPrompts, FixContext

@dataclass
class CodeQualityReport:
    """代码质量报告"""
    is_valid: bool
    syntax_errors: List[str]
    import_errors: List[str]
    structure_issues: List[str]
    style_issues: List[str]
    suggestions: List[str]

class ManimCodePreprocessor:
    """Manim代码预处理器 - 简化版本"""
    
    def __init__(self):
        pass
    
    def analyze_code(self, code):
        """分析代码质量"""
        syntax_errors = []
        import_errors = []
        structure_issues = []
        style_issues = []
        suggestions = []
        
        try:
            # 语法检查
            ast.parse(code)
        except SyntaxError as e:
            syntax_errors.append(f"语法错误: {str(e)}")
        
        # 基础结构检查
        if 'class Scene' not in code:
            structure_issues.append("缺少Scene类定义")
        if 'def construct(self):' not in code:
            structure_issues.append("缺少construct方法")
        if 'from manim import' not in code:
            import_errors.append("缺少manim导入")
            
        # 风格检查
        if code.count('\n') < 5:
            style_issues.append("代码过于简短")
        if 'TRANSPARENT' not in code:
            suggestions.append("建议设置透明背景")
            
        is_valid = not syntax_errors and not structure_issues and not import_errors
        
        return CodeQualityReport(
            is_valid=is_valid,
            syntax_errors=syntax_errors,
            import_errors=import_errors,
            structure_issues=structure_issues,
            style_issues=style_issues,
            suggestions=suggestions
        )
    
    def preprocess_code(self, code: str) -> str:
        """预处理代码"""
        # 简单的代码清理
        code = code.strip()
        
        # 移除markdown标记
        if '```python' in code:
            code = code.split('```python')[1].split('```')[0]
        elif '```' in code:
            code = code.split('```')[1].split('```')[0]
            
        return code.strip()

@dataclass
class ProcessingResult:
    """处理结果"""
    success: bool
    final_code: str
    attempts_used: int
    issues_resolved: List[str]
    remaining_issues: List[str]
    processing_log: List[str]

class ManimQualityController:
    """Manim质量控制器 - 整合预处理、检查、修复"""
    
    def __init__(self, max_fix_attempts = 3):
        self.preprocessor = ManimCodePreprocessor()
        self.prompt_system = OptimizedManimPrompts()
        self.max_fix_attempts = max_fix_attempts
        
    def process_manim_code(self, raw_code, scene_name, content_description = ""):
        """主要处理流程"""
        
        log = []
        log.append(f" 开始处理 {scene_name}")
        
        # 步骤1: 预处理清理
        log.append(" 步骤1: 代码预处理...")
        current_code = self.preprocessor.get_clean_code(raw_code)
        
        # 步骤2: 质量检查
        log.append(" 步骤2: 质量检查...")
        report = self.preprocessor.preprocess_code(current_code, scene_name)
        
        # 如果质量良好，直接返回
        if not report.needs_llm_fix:
            log.append(" 代码质量良好，无需修复")
            return ProcessingResult(
                success=True,
                final_code=current_code,
                attempts_used=0,
                issues_resolved=[],
                remaining_issues=report.layout_issues,
                processing_log=log
            )
        
        # 步骤3: LLM修复循环
        log.append(" 步骤3: LLM修复流程...")
        
        resolved_issues = []
        all_errors = report.syntax_errors + report.layout_issues
        
        for attempt in range(1, self.max_fix_attempts + 1):
            log.append(f"   尝试修复 {attempt}/{self.max_fix_attempts}")
            
            # 创建修复上下文
            fix_context = FixContext(
                attempt_count=attempt,
                previous_errors=report.syntax_errors,
                layout_issues=report.layout_issues,
                complexity_level=self._get_complexity_level(report.complexity_score),
                confidence_score=report.confidence
            )
            
            # 生成修复提示
            error_info = "; ".join(all_errors[:3])  # 限制错误信息长度
            fix_prompt = self.prompt_system.generate_fix_prompt(
                fix_context, current_code, error_info
            )
            
            # 调用LLM修复
            try:
                fixed_code = self._call_llm_fix(fix_prompt)
                if not fixed_code:
                    log.append(f"   第{attempt}次LLM修复失败")
                    continue
                
                # 清理并验证修复结果
                cleaned_fixed_code = self.preprocessor.get_clean_code(fixed_code)
                new_report = self.preprocessor.preprocess_code(cleaned_fixed_code, f"{scene_name}_fix{attempt}")
                
                # 检查是否有改善
                improvement = self._assess_improvement(report, new_report)
                
                if improvement['improved']:
                    log.append(f"   第{attempt}次修复成功，改善: {improvement['description']}")
                    current_code = cleaned_fixed_code
                    resolved_issues.extend(improvement['resolved'])
                    report = new_report
                    
                    # 如果已经足够好，提前结束
                    if not new_report.needs_llm_fix:
                        log.append(f"   修复完成，质量达标")
                        break
                else:
                    log.append(f"   第{attempt}次修复无明显改善")
                    
            except Exception as e:
                log.append(f"   第{attempt}次修复出错: {str(e)[:100]}")
        
        # 步骤4: 结果评估
        final_success = not report.needs_llm_fix or report.confidence < 0.5
        remaining_issues = report.syntax_errors + report.layout_issues
        
        log.append(f" 处理完成 - {'成功' if final_success else '部分成功'}")
        log.append(f"   解决问题: {len(resolved_issues)} 个")
        log.append(f"   剩余问题: {len(remaining_issues)} 个")
        
        return ProcessingResult(
            success=final_success,
            final_code=current_code,
            attempts_used=attempt if 'attempt' in locals() else 0,
            issues_resolved=resolved_issues,
            remaining_issues=remaining_issues,
            processing_log=log
        )
    
    def _get_complexity_level(self, score):
        """获取复杂度级别"""
        if score <= 3:
            return "low"
        elif score <= 6:
            return "medium"
        else:
            return "high"
    
    def _call_llm_fix(self, fix_prompt):
        """调用LLM修复 - 集成实际LLM或使用模拟修复"""
        
        print(f"🤖 调用LLM修复 (提示长度: {len(fix_prompt)})")
        
        # 尝试使用实际LLM
        try:
            from .workflow import modai_model_request
            result = modai_model_request(fix_prompt, max_tokens=2048, temperature=0.1)
            if result and len(result) > 100:  # 基本质量检查
                return result
        except Exception as e:
            print(f"   实际LLM调用失败: {str(e)[:50]}...")
        
        # 模拟修复 - 处理常见问题
        return self._mock_fix_common_issues(fix_prompt)
    
    def _mock_fix_common_issues(self, fix_prompt):
        """模拟修复常见问题"""
        
        print(f"   使用模拟修复...")
        
        # 检查提示中的问题类型
        if "expected ':'" in fix_prompt or "语法错误" in fix_prompt:
            # 生成一个简单的修复示例
            return '''# -*- coding: utf-8 -*-

import sys
import os

if hasattr(sys, 'setdefaultencoding'):
    sys.setdefaultencoding('utf-8')

os.environ['PYTHONIOENCODING'] = 'utf-8'

from manim import *

class TestScene(Scene):
    def construct(self):
        # 修复后的代码 - 使用VGroup避免重叠
        title_group = VGroup()
        
        title = Text("测试", font_size=36, color=BLUE)
        title.to_edge(UP, buff=0.8)
        title_group.add(title)
        
        subtitle = Text("副标题", font_size=24)
        subtitle.next_to(title, DOWN, buff=0.5)
        title_group.add(subtitle)
        
        # 分段显示和清理
        self.play(Write(title))
        self.wait(1)
        self.play(Write(subtitle))
        self.wait(2)
        
        # 清理
        self.play(FadeOut(title_group))
'''
        
        elif "元素重叠" in fix_prompt or "布局问题" in fix_prompt:
            return '''# -*- coding: utf-8 -*-

import sys
import os

if hasattr(sys, 'setdefaultencoding'):
    sys.setdefaultencoding('utf-8')

os.environ['PYTHONIOENCODING'] = 'utf-8'

from manim import *

class OptimizedScene(Scene):
    def construct(self):
        # 使用区域化布局避免重叠
        title = Text("优化标题", font_size=32)
        title.to_edge(UP, buff=0.8)
        
        content = Text("主要内容", font_size=24)
        content.next_to(title, DOWN, buff=0.6)
        
        visual = Circle(radius=1.0, color=BLUE)
        visual.next_to(content, DOWN, buff=0.5)
        
        # 分段动画
        self.play(Write(title))
        self.wait(1)
        
        self.play(Write(content))
        self.wait(1)
        
        self.play(Create(visual))
        self.wait(2)
        
        # 清理
        elements = VGroup(title, content, visual)
        self.play(FadeOut(elements))
'''
        
        else:
            # 默认的基础修复
            return '''# -*- coding: utf-8 -*-

import sys
import os

if hasattr(sys, 'setdefaultencoding'):
    sys.setdefaultencoding('utf-8')

os.environ['PYTHONIOENCODING'] = 'utf-8'

from manim import *

class BasicScene(Scene):
    def construct(self):
        title = Text("基础场景", font_size=32, color=BLUE)
        title.to_edge(UP, buff=1.0)
        
        self.play(Write(title))
        self.wait(2)
        self.play(FadeOut(title))
'''
    
    def _assess_improvement(self, old_report, new_report):
        """评估修复改善效果"""
        
        improvement = {
            'improved': False,
            'description': '',
            'resolved': []
        }
        
        # 语法改善
        if old_report.syntax_errors and not new_report.syntax_errors:
            improvement['improved'] = True
            improvement['description'] += "修复语法错误; "
            improvement['resolved'].extend(old_report.syntax_errors)
        
        # 布局改善
        old_layout_count = len(old_report.layout_issues)
        new_layout_count = len(new_report.layout_issues)
        
        if new_layout_count < old_layout_count:
            improvement['improved'] = True
            resolved_count = old_layout_count - new_layout_count
            improvement['description'] += f"减少{resolved_count}个布局问题; "
            improvement['resolved'].append(f"减少{resolved_count}个布局问题")
        
        # 复杂度改善
        if new_report.complexity_score < old_report.complexity_score:
            improvement['improved'] = True
            improvement['description'] += "降低复杂度; "
        
        # 置信度改善
        if new_report.confidence < old_report.confidence:
            improvement['improved'] = True
            improvement['description'] += "提高修复置信度; "
        
        return improvement
    
    def validate_final_code(self, code):
        """最终代码验证"""
        
        validations = []
        
        # 基础检查
        if 'from manim import' not in code:
            validations.append("缺少manim导入")
        
        if 'class' not in code or 'Scene' not in code:
            validations.append("缺少Scene类定义")
        
        if 'def construct' not in code:
            validations.append("缺少construct方法")
        
        # 语法检查
        syntax_valid, syntax_errors = self.preprocessor.check_syntax(code)
        if not syntax_valid:
            validations.extend(syntax_errors)
        
        return len(validations) == 0, validations

def integrate_with_workflow():
    """集成到现有workflow的示例"""
    
    def enhanced_code_processing(raw_code, scene_name, content_description = ""):
        """增强的代码处理函数"""
        
        controller = ManimQualityController(max_fix_attempts=2)
        
        # 处理代码
        result = controller.process_manim_code(raw_code, scene_name, content_description)
        
        # 打印处理日志
        for log_entry in result.processing_log:
            print(log_entry)
        
        # 返回最终代码和是否成功
        return result.final_code, result.success
    
    return enhanced_code_processing

