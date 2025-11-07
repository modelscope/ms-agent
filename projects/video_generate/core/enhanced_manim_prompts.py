import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import json


@dataclass
class ManimPromptTemplate:
    """Manim代码生成的提示词模板"""
    system_prompt: str
    user_prompt_template: str
    few_shot_examples: List[Dict[str, str]]
    validation_rules: List[str]


class EnhancedManimPromptSystem:
    """
    Manim提示词生成器
    """

    def __init__(self):
        self.templates = self._load_prompt_templates()
        self.few_shot_examples = self._load_few_shot_examples()
        self.validation_rules = self._load_validation_rules()

    def _load_prompt_templates(self):
        """加载各种类型的提示词模板"""
        # 基础系统提示词
        base_system_prompt = """
You are an expert Manim Community code generator with strict spatial quality control. You ONLY respond with valid Manim code, nothing else.

# CRITICAL SPATIAL CONSTRAINTS (STRICTLY ENFORCED):
1. **Safe Area Margins**: 0.5 units on all sides from scene edges. ALL objects MUST be positioned within these margins.
2. **Minimum Spacing**: 0.3 units between ANY two Manim objects (measured edge to edge). NO overlaps allowed.
3. **Frame Limits**: Frame width=14.22, height=8.0, center=(0,0,0). X limits: [-7.0, 7.0], Y limits: [-4.0, 4.0]
4. **Positioning Requirements**:
   - ONLY use relative positioning: next_to(), align_to(), shift(), to_corner(), move_to(ORIGIN)
   - NO absolute coordinates allowed
   - Reference points: ORIGIN, margins, or other objects only

# MANDATORY POSITIONING RULES:
1. Always use 'Scene' as the base class (not VoiceoverScene unless specifically requested)
2. Always use 'construct' method as the main animation function
3. Always include proper imports: from manim import *
4. Use clear, descriptive variable names
5. Add helpful comments for complex animations
6. Follow Manim best practices for smooth animations
7. **VALIDATE ALL POSITIONS**: Ensure every object respects safe margins and minimum spacing
8. **USE VGroup**: Group related elements for better spatial control

# Code Structure Template:
```python
from manim import *

class GeneratedScene(Scene):
    def construct(self):
        # ALWAYS verify objects are within safe area [-6.5, 6.5] x [-3.5, 3.5]
        # ALWAYS maintain 0.3 unit minimum spacing between objects
        # Your animation code here
        pass
```

SPATIAL VALIDATION CHECKLIST:
- [ ] All objects within safe margins (0.5 units from edges)
- [ ] Minimum 0.3 unit spacing between all objects
- [ ] Only relative positioning used
- [ ] No absolute coordinates
- [ ] VGroup used for related elements

IMPORTANT: Return ONLY the Python code, no explanations or markdown.
""" # noqa

        # 数学动画专用系统提示词
        math_system_prompt = """
You are a mathematical animation expert specializing in Manim Community with STRICT spatial quality control.

# SPATIAL CONSTRAINTS (NON-NEGOTIABLE):
- **Safe Area**: 0.5 units margin from all edges. Objects MUST be within [-6.5, 6.5] x [-3.5, 3.5]
- **Minimum Spacing**: 0.3 units between ANY objects (text, shapes, equations)
- **Positioning**: ONLY relative methods (next_to, align_to, shift, move_to(ORIGIN))
- **NO absolute coordinates allowed**

# Mathematical Animation Rules:
1. Use LaTeX for all mathematical expressions: MathTex("\\frac{1}{2}")
2. Color-code different mathematical concepts consistently
3. Use proper mathematical notation and symbols
4. Include step-by-step visual proofs when applicable
5. Add geometric constructions that illustrate mathematical principles
6. Use coordinate systems when showing geometric relationships
7. **GROUP FORMULAS**: Use VGroup for multi-part equations with proper spacing

# SPATIAL VALIDATION FOR MATH:
- Math formulas centered with move_to(ORIGIN)
- Related equations grouped in VGroup with 0.3+ unit spacing
- Labels positioned with next_to() maintaining minimum spacing
- Diagrams positioned relative to ORIGIN or other elements
- All elements validated within safe area bounds

# Standard Colors for Math:
- BLUE: Primary shapes and main concepts
- RED: Emphasis and important results
- GREEN: Secondary elements and comparisons
- YELLOW: Highlights and final conclusions
- WHITE: Standard text and labels

# Animation Patterns for Math:
- Create(): For drawing geometric shapes
- Write(): For mathematical text and equations
- Transform(): For showing mathematical transformations
- Flash(): For emphasizing important results
- LaggedStart(): For sequential element animations

MANDATORY SPACING EXAMPLE:
```python
formula1 = MathTex("E = mc^2").move_to(ORIGIN)
formula2 = MathTex("F = ma").next_to(formula1, DOWN, buff=0.5)  # 0.5 > 0.3 minimum
group = VGroup(formula1, formula2)
# Verify group is within safe area [-6.5, 6.5] x [-3.5, 3.5]
```

RETURN ONLY PYTHON CODE, NO EXPLANATIONS.
"""

        # 科普动画系统提示词 - 针对科学知识传播优化
        educational_system_prompt = """
You are a SCIENCE COMMUNICATION expert specializing in Manim Community animations with ADVANCED spatial quality control.

# STRICT SPATIAL CONSTRAINTS:
**SAFE AREA ENFORCEMENT**: All objects MUST be within 0.5 units from scene edges
- Effective area: [-6.5, 6.5] x [-3.5, 3.5]
- Frame dimensions: 14.22 x 8.0, center at (0,0,0)

**MINIMUM SPACING RULES**:
- 0.3 units minimum between ANY two objects
- Text elements: 0.4 units spacing for readability
- Diagrams: 0.5 units spacing from text
- Formulas: 0.3 units from explanatory text
- Use buff parameter in positioning methods

**POSITIONING CONSTRAINTS**:
- FORBIDDEN: Absolute coordinates like [1, 2, 0] or UP*3+RIGHT*2
- REQUIRED: Relative positioning only
  - move_to(ORIGIN) for centering
  - next_to(obj, direction, buff=0.3+) for relative placement
  - align_to(obj, direction) for alignment
  - shift(direction*distance) for minor adjustments
  - to_corner(corner) for corner placement

# SCIENCE COMMUNICATION PRINCIPLES:
1. **Clarity First**: Simple, clear visualizations that explain complex concepts
2. **Progressive Disclosure**: Build complexity step by step
3. **Visual Metaphors**: Use familiar objects to explain abstract concepts
4. **Multi-Modal Learning**: Combine text, diagrams, formulas, and animations
5. **Engagement**: Use colors, movements, and visual effects to maintain attention
6. **Accessibility**: Ensure content is understandable to general audiences

# SCIENTIFIC CONTENT SPECIALIZATIONS:
## Mathematics & Physics:
- Use MathTex for equations: MathTex("E = mc^2")
- Show step-by-step derivations with Transform()
- Use coordinate systems for geometric concepts
- Color-code variables consistently
- Include unit labels and dimensions

## Technology & AI:
- Use flowcharts and process diagrams
- Show data flows with arrows and connections
- Use modern colors (BLUE, GREEN, PURPLE for tech)
- Include visual representations of algorithms
- Show input → process → output patterns

## General Science:
- Use descriptive titles and labels
- Include cause-and-effect relationships
- Show before/after comparisons
- Use analogies and real-world examples
- Include summary points

# ENHANCED VISUAL ELEMENTS FOR SCIENCE:
1. **Title**: Always include descriptive titles with to_edge(UP, buff=0.5)
2. **Definitions**: Use colored Text boxes for key terms
3. **Formulas**: Center important equations with move_to(ORIGIN)
4. **Diagrams**: Use shapes, arrows, and labels to illustrate concepts
5. **Examples**: Include practical applications and real-world connections
6. **Summaries**: End with key takeaways positioned safely

# SPATIAL ORGANIZATION FOR SCIENCE CONTENT:
```python
# SCIENCE COMMUNICATION TEMPLATE:
title = Text("Science Topic", font_size=36).to_edge(UP, buff=0.5)
main_concept = Circle(color=BLUE).move_to(ORIGIN)
definition = Text("Key definition").next_to(main_concept, DOWN, buff=0.4)
formula = MathTex("Formula").next_to(definition, DOWN, buff=0.3)
example = Text("Real-world example").next_to(formula, DOWN, buff=0.4)
```

# RECOMMENDED TIMING FOR SCIENCE:
- self.wait(2) for complex concepts absorption
- run_time=3 for important transformations
- run_time=1 for transitions between ideas
- Progressive reveal: Create() then FadeIn() supporting elements

# COLOR SCHEME FOR SCIENCE:
- PRIMARY: BLUE (main concepts)
- SECONDARY: GREEN (examples, applications)
- ACCENT: YELLOW (important highlights)
- FORMULAS: WHITE or LIGHT_BLUE
- DEFINITIONS: LIGHT_GRAY background with dark text

# MANDATORY SPATIAL VALIDATION FOR SCIENCE:
# All elements within safe area [-6.5, 6.5] x [-3.5, 3.5]
# Minimum 0.3 unit spacing between all objects
# Text readability with proper font sizes
# Formulas and diagrams properly centered
# VGroup used for related scientific concepts
# No overlapping elements or text

RETURN ONLY PYTHON CODE, NO EXPLANATIONS OR MARKDOWN.
"""

        return {
            'basic':
            ManimPromptTemplate(
                system_prompt=base_system_prompt,
                user_prompt_template='Generate Manim code for: {content}',
                few_shot_examples=[],
                validation_rules=[
                    'from manim import', 'class', 'Scene', 'def construct',
                    'move_to', 'next_to'
                ]),
            'mathematical':
            ManimPromptTemplate(
                system_prompt=math_system_prompt,
                user_prompt_template=
                'Create a mathematical animation for: {content}\n\nSPATIAL REQUIREMENTS:\n{requirements}\n\nENFORCE: '
                'Safe margins, 0.3+ unit spacing, relative positioning only',
                few_shot_examples=[],
                validation_rules=[
                    'MathTex', 'from manim import', 'move_to', 'next_to',
                    'VGroup'
                ]),
            'educational':
            ManimPromptTemplate(
                system_prompt=educational_system_prompt,
                user_prompt_template=
                'Create an educational animation explaining: {content}\n\nTarget audience: {audience}\nKey '
                'concepts: {concepts}\n\nSPATIAL CONSTRAINTS: Safe area [-6.5,6.5]x[-3.5,3.5], 0.3+ unit spacing, '
                'relative positioning only',
                few_shot_examples=[],
                validation_rules=[
                    'to_edge', 'move_to', 'next_to', 'self.wait', 'VGroup'
                ])
        }

    def _load_few_shot_examples(self):
        """加载一些代码示例"""

        return {
            'mathematical': [{
                'description':
                'Show the Pythagorean theorem with visual proof',
                'code':
                '''from manim import *

class PythagoreanScene(Scene):
    def construct(self):
        # Title
        title = Tex("Pythagorean Theorem", font_size=48).to_edge(UP)
        self.play(Write(title))

        # Right triangle
        A = [-2, -1, 0]
        B = [2, -1, 0]
        C = [-2, 2, 0]
        triangle = Polygon(A, B, C, color=BLUE, fill_opacity=0.3)
        self.play(Create(triangle))

        # Labels
        a_label = MathTex("a", color=RED).next_to(Line(A, C), LEFT)
        b_label = MathTex("b", color=GREEN).next_to(Line(A, B), DOWN)
        c_label = MathTex("c", color=YELLOW).next_to(Line(B, C), UR)
        self.play(Write(a_label), Write(b_label), Write(c_label))

        # Squares on each side
        square_a = Square(side_length=1.5, color=RED, fill_opacity=0.2).next_to(Line(A, C), LEFT, buff=0)
        square_b = Square(side_length=2, color=GREEN, fill_opacity=0.2).next_to(Line(A, B), DOWN, buff=0)

        self.play(Create(square_a), Create(square_b))

        # Equation
        equation = MathTex("a^2", "+", "b^2", "=", "c^2").to_edge(DOWN)
        equation.set_color_by_tex("a^2", RED)
        equation.set_color_by_tex("b^2", GREEN)
        equation.set_color_by_tex("c^2", YELLOW)
        self.play(Write(equation))

        self.wait(2)'''
            }, {
                'description':
                'Visualize derivative as slope of tangent line',
                'code':
                '''from manim import *

class DerivativeVisualization(Scene):
    def construct(self):
        # Set up axes
        axes = Axes(x_range=[-1, 4], y_range=[-1, 3])
        self.play(Create(axes))

        # Function curve
        func = axes.plot(lambda x: 0.5 * x**2, color=BLUE)
        func_label = MathTex("f(x) = \\\\frac{1}{2}x^2").to_corner(UL)
        self.play(Create(func), Write(func_label))

        # Point on curve
        x_val = 2
        point = Dot(axes.c2p(x_val, 0.5 * x_val**2), color=RED)
        self.play(Create(point))

        # Tangent line
        slope = x_val  # derivative of 0.5x^2 is x
        tangent = axes.plot(lambda x: slope * (x - x_val) + 0.5 * x_val**2,
                           x_range=[x_val-1, x_val+1], color=RED)
        self.play(Create(tangent))

        # Slope label
        slope_label = MathTex(f"f'({x_val}) = {slope}").next_to(point, UR)
        self.play(Write(slope_label))

        self.wait(2)'''
            }],
            'educational': [{
                'description':
                'Explain machine learning concept step by step',
                'code':
                '''from manim import *

class MLConceptScene(Scene):
    def construct(self):
        # Title with background
        title = Text("Machine Learning", font_size=48, color=BLUE)
        title_bg = SurroundingRectangle(title, color=BLUE, fill_opacity=0.1)
        self.play(DrawBorderThenFill(title_bg), Write(title))
        self.play(title.animate.scale(0.7).to_edge(UP))

        # Data points
        dots = VGroup(*[Dot(2*np.random.random(3)-1, color=BLUE) for _ in range(10)])
        self.play(LaggedStart(*[Create(dot) for dot in dots], lag_ratio=0.1))

        # Learning process
        line = Line(LEFT*2, RIGHT*2, color=RED)
        learning_text = Text("Learning Pattern...", font_size=24).to_edge(DOWN)
        self.play(Write(learning_text), Create(line))

        # Result
        result_text = Text("Pattern Found!", font_size=32, color=GREEN).to_edge(DOWN)
        self.play(Transform(learning_text, result_text))

        self.wait(2)'''
            }]
        }

    def _load_validation_rules(self):
        """代码检查规则"""
        return {
            'required_imports': ['from manim import'],
            'required_structure': ['class', 'Scene', 'def construct'],
            'best_practices': ['self.play', 'self.wait', 'color='],
            'mathematical': ['MathTex', 'LaTeX'],
            'educational': ['Text', 'title', 'explanation']
        }

    def enhance_prompt_with_context(self,
                                    content,
                                    animation_type,
                                    context_info=None,
                                    few_shot=True):
        """
        增强提示词，添加上下文和少样本学习
        """

        template = self.templates.get(animation_type, self.templates['basic'])

        # 构建系统提示词
        system_prompt = template.system_prompt

        # 添加少样本示例
        if few_shot and animation_type in self.few_shot_examples:
            examples = self.few_shot_examples[animation_type]
            if examples:
                system_prompt += '\n\n# Example Code Patterns:\n'
                for i, example in enumerate(examples[:2]):  # 最多2个示例
                    system_prompt += f"\n## Example {i+1}: {example['description']}\n"
                    system_prompt += f"```python\n{example['code']}\n```\n"

        # 构建用户提示词
        if context_info is None:
            context_info = {}

        user_prompt = template.user_prompt_template.format(
            content=content, **context_info)

        # 添加特定要求
        requirements = self._generate_requirements(content, animation_type,
                                                   context_info)
        if requirements:
            user_prompt += f'\n\nSpecific Requirements:\n{requirements}'

        return system_prompt, user_prompt

    def _generate_requirements(self, content, animation_type, context_info):
        """根据内容和类型生成具体要求"""

        requirements = []

        # 基础要求
        requirements.append('- Use clear, descriptive variable names')
        requirements.append('- Include appropriate wait times for viewing')
        requirements.append('- Use consistent color scheme')

        # 类型特定要求
        if animation_type == 'mathematical':
            requirements.append('- Use LaTeX for all mathematical expressions')
            requirements.append('- Include proper mathematical notation')
            requirements.append('- Color-code different mathematical concepts')

            # 检测数学概念
            if any(keyword in content.lower()
                   for keyword in ['theorem', 'proof', 'equation']):
                requirements.append('- Include step-by-step visual proof')
            if any(keyword in content.lower()
                   for keyword in ['geometry', 'triangle', 'circle']):
                requirements.append('- Use geometric constructions')

        elif animation_type == 'educational':
            requirements.append('- Start with a clear title')
            requirements.append('- Build concepts progressively')
            requirements.append('- Include explanatory text')
            requirements.append('- End with summary or conclusion')

            # 根据上下文调整
            if context_info.get('audience') == 'beginner':
                requirements.append('- Use simple, clear animations')
                requirements.append('- Include more explanatory text')

        # 内容特定要求
        if any(keyword in content.lower()
               for keyword in ['data', 'graph', 'chart']):
            requirements.append('- Include proper axes and labels')
            requirements.append('- Use data visualization best practices')

        if any(keyword in content.lower()
               for keyword in ['process', 'step', 'algorithm']):
            requirements.append('- Show process step-by-step')
            requirements.append('- Use visual indicators for current step')

        return '\n'.join(requirements)

    def validate_generated_code(self, code, animation_type):
        """验证生成的代码是否符合空间约束规则和质量标准"""
        validation_issues = []
        suggestions = []
        score = 100

        # 检查基本Manim结构
        required_elements = [
            'from manim import', 'class', 'Scene', 'def construct'
        ]
        for element in required_elements:
            if element not in code:
                validation_issues.append(f'缺少必需元素: {element}')
                score -= 20

        # 检查Python语法错误和Markdown污染
        if '```python' in code or '```' in code:
            validation_issues.append('代码包含Markdown格式标记，这会导致Python语法错误')
            score -= 30

        # 检查基本Python语法
        try:
            # 尝试编译代码检查语法
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            validation_issues.append(f'Python语法错误: {str(e)}')
            score -= 25
        except Exception as e:
            validation_issues.append(f'代码编译错误: {str(e)}')
            score -= 15

        # 空间约束验证 - 核心质量控制
        spatial_keywords = [
            'move_to', 'next_to', 'align_to', 'shift', 'to_edge', 'to_corner'
        ]
        has_positioning = any(keyword in code for keyword in spatial_keywords)
        if not has_positioning:
            validation_issues.append('代码中缺少相对定位方法，可能导致元素重叠或越界')
            score -= 25

        # 检查是否使用了绝对坐标（常见错误模式）
        absolute_coord_patterns = [
            r'\[\s*[-+]?\d+\.?\d*\s*,\s*[-+]?\d+\.?\d*\s*,\s*[-+]?\d+\.?\d*\s*\]',  # [x, y, z]
            r'UP\s*\*\s*\d+\s*\+\s*RIGHT\s*\*\s*\d+',  # UP*n + RIGHT*m
            r'LEFT\s*\*\s*\d+\s*\+\s*DOWN\s*\*\s*\d+',  # LEFT*n + DOWN*m
            r'RIGHT\s*\*\s*\d+\s*\+\s*UP\s*\*\s*\d+',  # RIGHT*n + UP*m
        ]

        for pattern in absolute_coord_patterns:
            if re.search(pattern, code):
                validation_issues.append(
                    '发现绝对坐标使用，应该使用相对定位方法（move_to, next_to等）')
                score -= 20
                break

        # 检查越界风险（大数值）
        large_number_pattern = r'(UP|DOWN|LEFT|RIGHT)\s*\*\s*([5-9]|\d{2,})'
        if re.search(large_number_pattern, code):
            validation_issues.append('发现可能导致越界的大数值移动，建议使用较小值或相对定位')
            score -= 15

        # 检查是否使用了VGroup（推荐做法）
        code_lines = len(code.split('\n'))
        if 'VGroup' not in code and code_lines > 20:  # 对于复杂代码推荐使用VGroup
            suggestions.append('建议使用VGroup对相关元素进行分组管理，提高空间控制能力')
            score -= 5

        # 检查是否有适当的缓冲区设置
        if 'next_to' in code and 'buff=' not in code:
            suggestions.append('使用next_to时建议设置buff参数（如buff=0.3）确保适当间距')
            score -= 5

        # 检查基本动画质量
        if 'self.play' not in code:
            validation_issues.append('缺少动画播放指令')
            score -= 15

        if 'self.wait' not in code:
            suggestions.append('建议添加等待时间以改善动画节奏')
            score -= 3

        # 类型特定验证
        if animation_type == 'mathematical':
            if 'MathTex' not in code and 'Tex' not in code:
                suggestions.append('数学动画建议使用MathTex显示公式')
                score -= 5

        elif animation_type == 'educational':
            if 'Text' not in code and 'Tex' not in code:
                suggestions.append('教育动画建议添加解释性文本')
                score -= 5

        # 检查颜色使用
        if 'color=' not in code:
            suggestions.append('建议使用颜色增强视觉效果')
            score -= 3

        return {
            'is_valid':
            len(validation_issues) == 0,
            'issues':
            validation_issues,
            'suggestions':
            suggestions,
            'validation_score':
            max(0, score),
            'spatial_quality':
            'high' if score >= 80 else 'medium' if score >= 60 else 'low'
        }

    def create_enhanced_prompt(self,
                               content,
                               content_type='educational',
                               context_segments=None,
                               main_theme=None,
                               audio_duration=None,
                               existing_code=None):
        """
        创建增强的提示词，整合所有最佳实践，包括布局优化
        """

        # 如果有现有代码，分析其布局问题
        layout_issues = []
        if existing_code:
            # 简单的布局问题检测（替代 get_layout_fix_suggestions）
            if 'move_to(' in existing_code and 'ORIGIN' not in existing_code:
                layout_issues.append('避免使用绝对坐标，建议使用相对定位')
            if 'shift(' in existing_code and existing_code.count('shift(') > 3:
                layout_issues.append('过多的shift操作可能导致布局混乱')

        # 使用内置模板生成提示（替代 create_optimized_manim_prompt）
        if content or layout_issues:
            template = self.templates.get(content_type,
                                          self.templates['educational'])
            optimized_prompt = template.system_prompt + '\n\n'
            optimized_prompt += template.user_prompt_template.format(
                content=content or '')

            # 如果有布局问题，在提示中强调修复
            if layout_issues:
                optimized_prompt += '\n\n## 紧急修复问题\n'
                for issue in layout_issues:
                    optimized_prompt += f'- {issue}\n'
                optimized_prompt += '\n请确保生成的代码完全解决以上所有布局问题。'

            return optimized_prompt, ''

        # 原有逻辑作为备选
        # 准备上下文信息
        context_info = {
            'audience': 'general',
            'concepts': [],
            'requirements': ''
        }

        if main_theme:
            context_info['theme'] = main_theme

        if audio_duration:
            context_info[
                'duration'] = f'approximately {audio_duration:.1f} seconds'

        if context_segments:
            # 从上下文段落中提取关键概念
            all_content = ' '.join(
                [seg.get('content', '') for seg in context_segments])
            context_info['full_context'] = all_content[:500]  # 限制长度

        # 选择动画类型
        animation_type = self._detect_animation_type(content, content_type)

        # 生成增强提示词
        system_prompt, user_prompt = self.enhance_prompt_with_context(
            content=content,
            animation_type=animation_type,
            context_info=context_info,
            few_shot=True)
        return system_prompt, user_prompt

    def _detect_animation_type(self, content, content_type):
        """智能检测最佳动画类型"""

        content_lower = content.lower()
        math_keywords = [
            'equation', 'formula', 'theorem', 'proof', 'derivative',
            'integral', 'geometry', 'algebra', 'calculus', 'function', 'graph',
            'plot'
        ]
        if any(keyword in content_lower for keyword in math_keywords):
            return 'mathematical'

        edu_keywords = [
            'explain', 'understand', 'learn', 'concept', 'principle', 'theory',
            'introduction', 'overview', 'basics', 'fundamental'
        ]
        if any(keyword in content_lower for keyword in edu_keywords):
            return 'educational'

        if content_type in ['example', 'definition', 'explanation']:
            return 'educational'
        elif content_type in ['mathematical', 'formula']:
            return 'mathematical'

        return 'educational'

    def generate_creation_prompt(self,
                                 content,
                                 content_type='educational',
                                 main_theme=None,
                                 audio_duration=None):
        """
        生成创建提示词（兼容方法）
        """
        template = self.templates.get(content_type,
                                      self.templates['educational'])
        prompt = template.system_prompt + '\n\n'
        prompt += template.user_prompt_template.format(content=content or '')

        if main_theme:
            prompt += f'\n\n主题：{main_theme}'
        if audio_duration:
            prompt += f'\n\n动画时长：{audio_duration}秒'

        return prompt
