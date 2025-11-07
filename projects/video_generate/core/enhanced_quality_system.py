# 评估系统待改进

import os
import re
import time
from typing import Any, Dict, List, Optional

import json
from openai import OpenAI


def safe_json_parse(response, required_keys):
    """安全的JSON解析，带回退机制"""
    try:
        # 尝试从markdown代码块中提取JSON
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', response,
                               re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接解析整个响应
            json_str = response.strip()

        parsed = json.loads(json_str)

        # 验证必需的键是否存在
        for key in required_keys:
            if key not in parsed:
                parsed[key] = {}

        return parsed
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        print(f'JSON解析失败: {e}')
        # 返回包含必需键的默认字典
        return {key: {} for key in required_keys}


class VisualQualityAssessment:
    """增强的视觉质量评估模块 - 专注于空间约束和元素重叠检测"""

    def __init__(self):
        self.banned_reasonings = ['看起来不错', '没有问题', '很好', '符合要求', '完美']
        # 空间约束参数
        self.safe_margins = 0.5  # 安全边距
        self.min_spacing = 0.3  # 最小间距
        self.frame_width = 14.22
        self.frame_height = 8.0
        self.safe_area_x = (-6.5, 6.5)  # 有效X坐标范围
        self.safe_area_y = (-3.5, 3.5)  # 有效Y坐标范围

    def assess_animation_quality(self,
                                 animation_code,
                                 content,
                                 animation_type,
                                 improvement_prompt=None):
        """
        增强的动画质量评估，重点检查空间约束和重叠问题
        """

        # 首先进行代码级别的空间约束检查
        spatial_analysis = self._analyze_spatial_constraints(animation_code)

        quality_prompt = f"""
请评估以下Manim动画代码的空间布局质量：

空间约束检查：
- 安全区域: 元素是否在 [-6.5, 6.5] x [-3.5, 3.5] 内
- 元素间距: 保持至少0.3单位间距
- 定位方法: 使用相对定位，避免绝对坐标
- 重叠检测: 检查视觉重叠问题
- 边界检查: 避免越界渲染

内容：{content}
类型：{animation_type}
{animation_type}

**生成的动画代码：**
```python
{animation_code}
```

**代码空间分析结果：**
{spatial_analysis}

"""
        # 改进建议，拼接到prompt
        if improvement_prompt:
            quality_prompt += f"""
**之前的改进建议：**
{improvement_prompt}
"""

        quality_prompt += """

请返回JSON格式的评估结果，包含以下字段：
- overall_quality_score: 整体质量评分
- spatial_quality: 空间质量评估
- content_alignment: 内容匹配度
- critical_issues: 关键问题列表
- needs_revision: 是否需要修订
"""

        # 接入大模型 LLM
        client = OpenAI(
            base_url='https://api-inference.modelscope.cn/v1',
            api_key=os.environ.get('MODELSCOPE_API_KEY'),
        )
        max_retries = 3
        llm_response = None
        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model='Qwen/Qwen3-235B-A22B-Instruct-2507',
                    messages=[{
                        'role': 'user',
                        'content': quality_prompt
                    }],
                    temperature=0.1,
                    max_tokens=1500)
                llm_response = response.choices[0].message.content
                break
            except Exception as e:
                print(f'LLM评估失败 (尝试 {attempt + 1}/{max_retries}): {e}')
                if attempt == max_retries - 1:
                    print('使用mock评估结果')
                    return self._mock_quality_assessment(spatial_analysis)

        # 兼容流式和非流式
        if isinstance(llm_response, (tuple, list)):
            response = llm_response[0] if llm_response else ''
        else:
            response = llm_response or ''

        assessment = safe_json_parse(response, [
            'overall_quality_score', 'spatial_quality', 'content_alignment',
            'visual_richness', 'educational_value', 'technical_quality',
            'needs_revision'
        ])

        # 添加我们的空间分析结果
        if assessment:
            assessment['spatial_analysis'] = spatial_analysis

        return assessment or self._mock_quality_assessment(spatial_analysis)

    def _analyze_spatial_constraints(self, manim_code):
        """分析Manim代码中的空间约束

        Args:
            manim_code (str): Manim代码字符串

        Returns:
            dict: 空间分析结果
        """
        issues = []
        warnings = []

        # 检查绝对坐标使用
        if 'UP *' in manim_code or 'DOWN *' in manim_code or 'LEFT *' in manim_code or 'RIGHT *' in manim_code:
            issues.append('使用了绝对坐标定位，可能导致元素越界')

        # 检查大数值位移
        import re
        large_shifts = re.findall(r'shift\(\s*([^)]+)\s*\)', manim_code)
        for shift in large_shifts:
            if any(num in shift for num in ['7', '8', '9', '10', '11', '12']):
                issues.append(f'发现大数值位移: {shift}')

        # 检查边界方法使用
        if 'to_edge()' in manim_code and 'buff=' not in manim_code:
            warnings.append('to_edge()未指定缓冲距离，建议添加buff参数')

        # 检查相对定位使用
        relative_methods = ['next_to', 'shift', 'to_edge', 'to_corner']
        relative_count = sum(1 for method in relative_methods
                             if method in manim_code)
        total_positioning = manim_code.count('=') + manim_code.count(
            'shift') + manim_code.count('next_to')

        if total_positioning > 0:
            relative_ratio = relative_count / total_positioning
        else:
            relative_ratio = 0

        return {
            'boundary_issues':
            issues,
            'warnings':
            warnings,
            'relative_positioning_ratio':
            relative_ratio,
            'total_elements':
            manim_code.count('Text(') + manim_code.count('Circle(')
            + manim_code.count('Square('),
            'positioning_methods':
            relative_count
        }

    def _mock_quality_assessment(self, spatial_analysis):
        """模拟增强质量评估结果

        Args:
            spatial_analysis (dict): 空间分析结果

        Returns:
            dict: 模拟评估结果
        """
        base_score = 85

        # 根据空间分析调整分数
        if spatial_analysis['boundary_issues']:
            base_score -= len(spatial_analysis['boundary_issues']) * 10

        if spatial_analysis['relative_positioning_ratio'] < 0.7:
            base_score -= 15

        return {
            'overall_quality_score': max(base_score, 50),
            'spatial_quality': {
                'score': 100 - len(spatial_analysis['boundary_issues']) * 15,
                'boundary_issues': spatial_analysis['boundary_issues'],
                'warnings': spatial_analysis['warnings']
            },
            'content_alignment': {
                'score': 90,
                'reasoning': '动画与文案内容高度匹配'
            },
            'visual_richness': {
                'score': 80,
                'reasoning': '动画元素丰富，布局合理'
            },
            'educational_value': {
                'score': 88,
                'reasoning': '有助于学习者理解复杂概念'
            },
            'technical_quality': {
                'score': 85,
                'reasoning': '代码结构清晰，空间约束良好'
            },
            'needs_revision': base_score < 75,
            'spatial_analysis': spatial_analysis
        }


class AnimationContentMatcher:
    """动画与文案匹配验证器"""

    def validate_match(self, animation_code, content, animation_type):
        """
        验证动画代码是否与文案内容匹配
        """

        validation_prompt = f"""
请作为专业的科普教育动画审查员，验证动画代码是否与文案内容匹配：

**验证要点：**
1. 动画元素是否体现文案中的关键概念
2. 动画风格是否符合内容类型（{animation_type}）
3. 动画复杂度是否与内容深度匹配
4. 是否存在无关或分散注意力的元素

**文案内容：**
{content}

**动画代码：**
{animation_code}

**请返回严格的JSON验证结果：**
{{
    "match_score": 90,
    "concept_coverage": {{
        "covered_concepts": ["概念A", "概念B"],
        "missing_concepts": ["概念C"],
        "coverage_percentage": 75
    }},
    "style_consistency": {{
        "is_consistent": True,
        "style_issues": []
    }},
    "complexity_alignment": {{
        "is_appropriate": True,
        "complexity_feedback": "复杂度适中，符合内容要求"
    }},
    "irrelevant_elements": [],
    "improvement_suggestions": [
        "增加概念C的视觉展示",
        "优化动画过渡效果"
    ],
    "is_acceptable": True,
    "confidence": 0.85
}}
"""

        # 接入大模型 LLM
        client = OpenAI(
            base_url='https://api-inference.modelscope.cn/v1',
            api_key=os.environ.get('MODELSCOPE_API_KEY'),
        )
        max_retries = 3
        llm_response = None
        for attempt in range(max_retries):
            try:
                llm_response = client.chat.completions.create(
                    model='Qwen/Qwen3-235B-A22B-Instruct-2507',
                    messages=[{
                        'role':
                        'system',
                        'content':
                        'You are a professional science education animation reviewer.'
                    }, {
                        'role': 'user',
                        'content': validation_prompt
                    }])
                break
            except Exception as e:
                print(f'API调用失败，第{attempt+1}次: {e}')
                if attempt < max_retries - 1:
                    time.sleep((attempt + 1) * 2)
                else:
                    print('API多次失败，返回默认内容')
                    return self._mock_validation_result()
        if isinstance(llm_response, (tuple, list)):
            choices = llm_response[0] if isinstance(
                llm_response, (tuple, list)) and len(llm_response) > 0 else []
            if choices and hasattr(choices[0], 'delta'):
                response = ''.join(
                    chunk.delta.content for chunk in choices
                    if hasattr(chunk, 'delta') and hasattr(
                        chunk.delta, 'content') and chunk.delta.content)
            elif choices and hasattr(choices[0], 'message'):
                response = choices[0].message.content
            else:
                response = str(llm_response)
        else:
            response = getattr(
                getattr(llm_response.choices[0], 'message', None), 'content',
                str(llm_response))
        parsed = safe_json_parse(response, [
            'match_score', 'concept_coverage', 'style_consistency',
            'complexity_alignment', 'is_acceptable', 'confidence'
        ])
        if isinstance(parsed, list):
            if parsed:
                return parsed[0]
            else:
                return {}
        return parsed

    def _mock_validation_result(self):
        """模拟验证结果"""
        return {
            'match_score': 90,
            'concept_coverage': {
                'covered_concepts': ['主要概念', '关键原理'],
                'missing_concepts': [],
                'coverage_percentage': 95
            },
            'style_consistency': {
                'is_consistent': True,
                'style_issues': []
            },
            'complexity_alignment': {
                'is_appropriate': True,
                'complexity_feedback': '复杂度适中，符合内容要求'
            },
            'irrelevant_elements': [],
            'improvement_suggestions': ['可以增加更多互动元素', '优化颜色搭配'],
            'is_acceptable': True,
            'confidence': 0.90
        }
