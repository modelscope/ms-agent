from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class FixContext:
    """修复上下文"""
    attempt_count: int
    previous_errors: List[str]
    layout_issues: List[str]
    complexity_level: str
    confidence_score: float


class OptimizedManimPrompts:
    """优化的Manim提示词系统"""

    def __init__(self):
        self.generation_templates = self._load_generation_templates()
        self.fix_templates = self._load_fix_templates()
        self.constraint_rules = self._load_constraint_rules()

    def _load_generation_templates(self):
        """生成模板 - 前置约束，避免问题发生"""
        return {
            'base_generation':
            """
你是专业的Manim动画代码生成专家。请生成符合以下严格规范的代码：

## 布局规范（必须遵循）

### 空间管理
- 使用相对布局：next_to(), to_edge(), align_to()
- 禁止硬编码坐标：避免move_to(np.array([x,y,z]))
- VGroup容器：相关元素必须用VGroup组织
- 最小间距：buff≥0.4 (垂直)，buff≥0.5 (水平)

### 边界约束
- 安全区域：left≥-5.5, right≤5.5, top≤3.0, bottom≥-3.0
- 文字大小：title(32-36), subtitle(24-28), body(20-24)
- 图形大小：radius≤2.0, width≤8.0, height≤5.0

### VGroup使用规范
```python
# 正确方式：分组管理
title_group = VGroup(title, subtitle)
title_group.arrange(DOWN, buff=0.5)
title_group.to_edge(UP, buff=0.8)

content_group = VGroup(text1, text2, visual)
content_group.arrange(DOWN, buff=0.4)
content_group.next_to(title_group, DOWN, buff=0.6)
```

### 分段清理机制
```python
# 每个概念段落后必须清理
def show_concept_1(self):
    elements = VGroup(title, content, visual)
    self.play(FadeIn(elements))
    self.wait(2)
    self.play(FadeOut(elements))  # 必须清理

def show_concept_2(self):
    # 下一个概念...
```

## 动画丰富性要求

### 多样化动画
- 文字：Write(), DrawBorderThenFill(), FadeIn()
- 图形：Create(), GrowFromCenter(), DrawBorderThenFill()
- 转换：Transform(), ReplacementTransform(), MorphShape()
- 组合：LaggedStart(), AnimationGroup(), Succession()

### 视觉层次
- 标题醒目：大字体+明亮颜色
- 重点突出：颜色对比+动画强调
- 节奏控制：适当的wait()间隔

## 内容要求
主题：{content}
类型：{content_type}
目标：生成专业、无重叠、视觉丰富的动画

请生成完整的Scene类代码，确保：
· 零重叠零越界
· 丰富的动画效果
· 清晰的视觉层次
· 完整的分段清理
""",
            'fix_generation':
            """
你是Manim代码修复专家。基于以下错误信息和约束，修复代码：

## 修复目标
原始错误：{error_info}
布局问题：{layout_issues}
尝试次数：{attempt_count}

## 修复策略

### 语法错误修复
1. 检查缩进和语法
2. 确保import正确
3. 修复变量名错误
4. 处理编码问题

### 布局问题修复
1. 重新设计元素布局
2. 使用VGroup避免重叠
3. 调整相对位置关系
4. 确保边界安全

### 渐进修复原则
- 第1次：修复语法+明显布局问题
- 第2次：优化空间使用+动画流畅性
- 第3次：精细调整+视觉优化

## 避免过度修复
- 不要完全重写功能
- 保持原有动画思路
- 只修复确定的问题
- 避免引入新的复杂性

## 修复重点
{specific_fixes}

请提供修复后的完整代码：
"""
        }

    def _load_fix_templates(self) -> Dict[str, str]:
        """修复模板 - 循序渐进"""
        return {
            'syntax_fix':
            """
专注语法修复：
1. 修复Python语法错误
2. 确保正确的缩进
3. 修正import语句
4. 处理编码问题
保持原有功能不变。
""",
            'layout_fix':
            """
专注布局修复：
1. 重新组织元素布局
2. 使用VGroup避免重叠
3. 调整相对位置关系
4. 确保在安全边界内
保持原有动画效果。
""",
            'visual_fix':
            """
专注视觉优化：
1. 优化动画流畅性
2. 改善视觉层次
3. 增强色彩搭配
4. 完善过渡效果
保持布局稳定。
"""
        }

    def _load_constraint_rules(self) -> Dict[str, List[str]]:
        """约束规则库"""
        return {
            'positioning': [
                '使用to_edge()确保边界安全', '用next_to()建立相对关系', 'VGroup统一管理相关元素',
                'buff参数保证最小间距'
            ],
            'sizing': [
                'title字体32-36，subtitle字体24-28', '圆形radius≤2.0，矩形width≤8.0',
                '文本行数限制在3行以内', '复杂图形分解为简单元素'
            ],
            'animation': [
                'Write()用于文字显示', 'Create()用于图形绘制', 'Transform()用于元素变换',
                'LaggedStart()用于序列动画'
            ],
            'cleanup':
            ['每个概念段落后FadeOut清理', '使用VGroup统一管理和清理', '避免元素在场景中累积', '保持画面清洁简约']
        }

    def generate_creation_prompt(self, content, content_type='educational'):
        """生成创建提示词"""

        return self.generation_templates['base_generation'].format(
            content=content, content_type=content_type)

    def generate_fix_prompt(self, fix_context, original_code, error_info):
        """生成修复提示词"""

        # 根据尝试次数选择修复策略
        if fix_context.attempt_count == 1:
            specific_fixes = self.fix_templates['syntax_fix']
        elif fix_context.attempt_count == 2:
            specific_fixes = self.fix_templates['layout_fix']
        else:
            specific_fixes = self.fix_templates['visual_fix']

        # 构建布局问题描述
        layout_desc = '\n'.join(f'- {issue}'
                                for issue in fix_context.layout_issues
                                ) if fix_context.layout_issues else '无明显布局问题'

        return self.generation_templates['fix_generation'].format(
            error_info=error_info,
            layout_issues=layout_desc,
            attempt_count=fix_context.attempt_count,
            specific_fixes=specific_fixes)

    def get_feedback_prompt(self, code, issues):
        """生成反馈提示词"""

        if not issues:
            return '代码质量良好，无需修复。'

        feedback = f"""
## 代码审查反馈

发现问题：{len(issues)} 个

"""
        for i, issue in enumerate(issues, 1):
            feedback += f'{i}. {issue}\n'

        feedback += """
## 修复建议

请重点关注：
1. 使用VGroup组织相关元素
2. 确保相对布局和适当间距
3. 避免硬编码坐标
4. 保持视觉层次清晰

请基于以上反馈优化代码。
"""

        return feedback

    def get_constraint_checklist(self, check_type='all'):
        """获取约束检查清单"""

        if check_type == 'all':
            checklist = []
            for category, rules in self.constraint_rules.items():
                checklist.extend(rules)
            return checklist

        return self.constraint_rules.get(check_type, [])
