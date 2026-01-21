# Copyright (c) ModelScope Contributors. All rights reserved.
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Union

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig
from PIL import Image

logger = get_logger()


class GenerateManimCode(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.num_parallel = getattr(self.config, 'llm_num_parallel', 10)
        self.images_dir = os.path.join(self.work_dir, 'images')
        self.manim_code_dir = os.path.join(self.work_dir, 'manim_code')
        os.makedirs(self.manim_code_dir, exist_ok=True)

    async def execute_code(self, messages: Union[str, List[Message]],
                           **kwargs) -> List[Message]:
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)
        with open(os.path.join(self.work_dir, 'audio_info.txt'), 'r') as f:
            audio_infos = json.load(f)
        logger.info('Generating manim code.')

        tasks = []
        for i, (segment, audio_info) in enumerate(zip(segments, audio_infos)):
            manim_requirement = segment.get('manim')
            if manim_requirement is not None:
                tasks.append((segment, audio_info['audio_duration'], i))

        manim_code = [''] * len(segments)

        with ThreadPoolExecutor(max_workers=self.num_parallel) as executor:
            futures = {
                executor.submit(self._generate_manim_code_static, seg, dur,
                                idx, self.config, self.images_dir): idx
                for seg, dur, idx in tasks
            }
            for future in as_completed(futures):
                idx = futures[future]
                manim_code[idx] = future.result()

        for i, code in enumerate(manim_code):
            manim_file = os.path.join(self.manim_code_dir,
                                      f'segment_{i + 1}.py')
            with open(manim_file, 'w') as f:
                f.write(code)
        return messages

    @staticmethod
    def _generate_manim_code_static(segment, audio_duration, i, config,
                                    image_dir):
        """Static method for multiprocessing"""
        llm = LLM.from_config(config)
        return GenerateManimCode._generate_manim_impl(llm, segment,
                                                      audio_duration, i,
                                                      image_dir, config)

    @staticmethod
    def get_image_size(filename):
        with Image.open(filename) as img:
            return f'{img.width}x{img.height}'

    @staticmethod
    def get_all_images_info(segment, i, image_dir):
        all_images_info = []

        descriptions = segment.get('foreground', [])

        # Now check for files corresponding to these descriptions
        for idx, desc in enumerate(descriptions):
            foreground_image = os.path.join(
                image_dir, f'illustration_{i + 1}_foreground_{idx + 1}.png')

            if os.path.exists(foreground_image):
                size = GenerateManimCode.get_image_size(foreground_image)
                image_info = {
                    'filename': foreground_image,
                    'size': size,
                    'description': desc,
                }
                all_images_info.append(image_info)

        image_info_file = os.path.join(
            os.path.dirname(image_dir), 'image_info.txt')
        if os.path.exists(image_info_file):
            with open(image_info_file, 'r') as f:
                for line in f.readlines():
                    if not line.strip():
                        continue
                    image_info = json.loads(line)
                    if image_info['filename'] in segment.get('user_image', []):
                        all_images_info.append(image_info)
        return all_images_info

    @staticmethod
    def _generate_manim_impl(llm, segment, audio_duration, i, image_dir,
                             config):
        class_name = f'Scene{i + 1}'
        content = segment['content']
        manim_requirement = segment['manim']
        images_info = GenerateManimCode.get_all_images_info(
            segment, i, image_dir)
        if images_info:
            images_info = json.dumps(images_info, indent=4, ensure_ascii=False)
        else:
            images_info = '未提供图片。'

        if config.foreground == 'image':
            image_usage = f"""**图片使用说明**
    - 你将收到一个实际的图片列表，每张图片包含三个字段：文件名、尺寸和描述，请深入考虑如何在动画中调整大小和使用这些图片
    - 确保非正方形图片的宽高比正确，编写 Manim 代码时需保持图片的宽高比
    - 考虑图片与背景及整体动画的融合。使用混合/发光效果、边框、动效、装饰边等使其更美观华丽
        * 禁止将图片裁剪为圆形
        * 图片必须添加边框装饰
        * 缩放图片。不要使用原始尺寸，使图片在你的动画中的位置和大小美观合适。不要将图片放在角落
        * 禁止让图片和 manim 元素重叠。请在动画中重新组织它们
    - 重要：如果图片文件列表不为空，**你必须在动画中的适当时机和位置使用所有图片**。以下是图片文件列表：

    {images_info}
"""
        else:
            image_usage = ''

        prompt = f"""你是一位专业的 Manim 动画专家，擅长创建清晰美观的教育动画。

    **任务**：创建动画
    - 类名：{class_name}
    - 内容：{content}
    - 分镜设计师的要求：{manim_requirement}
        * 分镜设计师会给你整体要求。你需要自行定制元素和布局，使整体动画美观高档
    - 时长：{audio_duration} 秒
    - 代码语言：**Python**

    {image_usage}

    - 如果图片存在，你需要使用所有的图片，图片需要放置在屏幕显眼的位置，不要放置在角落
    - 你的动画时长需要符合 Duration 的要求
    - 你的动画需要符合 Content 原始需求，避免视觉杂乱，保持简洁优雅，不允许使用火柴人
    - 你的屏幕是 16:9 的

    **设计原则**：
    - 创建视觉上令人惊艳的动画，而不是简单的文本展示
    - 使用流畅的过渡和专业的动效
    - 保持视觉层次清晰，重要信息突出，使用不超过4个主要元素时间或空间**有序排列**，否则元素遮盖情况会比较严重
    - [关键] 绝对不允许**任何组件（文本框、图片、物体）重叠**或**元素超出16:9边界**或**元素未对齐**。
    - [关键] 方框/文本之间的连接线长度适当，**两端点必须连接到对象上**。
    - [关键] **绝对禁止非透明背景**。你的组件下方存在背景图片，需要显示它
    - 所有方框必须有粗边框以确保清晰可见
    - 通过控制字体大小使文本保持在画面内。由于拉丁字母文本通常较长，其字体应比中文更小。
    - 使用清晰、高对比度的字体颜色，防止文本与背景混淆
    - 整个视频使用约2种颜色的协调配色方案。避免杂乱的颜色、亮蓝色和亮黄色。优先使用深色、暗色调
    - 文字动画布局工整,多利用横向空间，一些推荐的布局：
        * 左右分布：左侧文字，右侧图片或表格，所有元素在16:9的横向纵向范围内
        * 田字格分布：四个格子内放置内容，所有元素在16:9的横向纵向范围内
        * 左中右分布：横向并列放置数个物体，大小相等，所有元素在16:9的横向纵向范围内
        * 不要在上述分布上再增加title或者中心文字

    **代码原则**：
    - 文字大小不得小于25px，重点介绍文字不小于45px
    - 注意元素层叠顺序，确保z-index正确，互相位置合理
    - 防止元素超出边界
    请创建满足以上要求的manim代码，打造视觉震撼的动画效果。
"""

        logger.info(f'正在生成 manim 代码：{content}')
        _response_message = llm.generate(
            [Message(role='user', content=prompt)], temperature=0.3)
        response = _response_message.content
        if '```python' in response:
            manim_code = response.split('```python')[1].split('```')[0]
        elif '```' in response:
            manim_code = response.split('```')[1].split('```')[0]
        else:
            manim_code = response
        return manim_code
