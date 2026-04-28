# Copyright (c) ModelScope Contributors. All rights reserved.
import glob
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Union

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig
from PIL import Image

logger = get_logger()


class GenerateRemotionCode(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.num_parallel = getattr(self.config, 'llm_num_parallel', 10)
        self.images_dir = os.path.join(self.work_dir, 'images')
        self.remotion_code_dir = os.path.join(self.work_dir, 'remotion_code')
        os.makedirs(self.remotion_code_dir, exist_ok=True)

    async def execute_code(self, messages: Union[str, List[Message]],
                           **kwargs) -> List[Message]:
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)
        with open(os.path.join(self.work_dir, 'audio_info.txt'), 'r') as f:
            audio_infos = json.load(f)
        logger.info('Generating remotion code.')

        tasks = []
        for i, (segment, audio_info) in enumerate(zip(segments, audio_infos)):
            # "remotion" field takes precedence, fall back to "manim"
            animation_requirement = segment.get('remotion')
            if animation_requirement is not None:
                # Check if file already exists
                remotion_file = os.path.join(self.remotion_code_dir,
                                             f'Segment{i + 1}.tsx')
                if os.path.exists(remotion_file):
                    continue
                tasks.append((segment, audio_info['audio_duration'], i))

        remotion_code = [''] * len(segments)

        # Load existing files for skipped segments
        for i in range(len(segments)):
            remotion_file = os.path.join(self.remotion_code_dir,
                                         f'Segment{i + 1}.tsx')
            if os.path.exists(remotion_file):
                with open(remotion_file, 'r', encoding='utf-8') as f:
                    remotion_code[i] = f.read()

        with ThreadPoolExecutor(max_workers=self.num_parallel) as executor:
            futures = {
                executor.submit(self._generate_remotion_code_static, seg, dur,
                                idx, self.config, self.images_dir): idx
                for seg, dur, idx in tasks
            }
            for future in as_completed(futures):
                idx = futures[future]
                remotion_code[idx] = future.result()

        for i, code in enumerate(remotion_code):
            remotion_file = os.path.join(self.remotion_code_dir,
                                         f'Segment{i + 1}.tsx')
            with open(remotion_file, 'w', encoding='utf-8') as f:
                f.write(code)
        return messages

    @staticmethod
    def _generate_remotion_code_static(segment, audio_duration, i, config,
                                       image_dir):
        """Static method for multiprocessing"""
        llm = LLM.from_config(config)
        return GenerateRemotionCode._generate_remotion_impl(
            llm, segment, audio_duration, i, image_dir, config)

    @staticmethod
    def get_image_size(filename):
        with Image.open(filename) as img:
            return f'{img.width}x{img.height}'

    @staticmethod
    def get_all_images_info(segment, i, image_dir):
        all_images_info = []

        foreground = segment.get('foreground', [])
        for idx, _req in enumerate(foreground):
            foreground_image = os.path.join(
                image_dir, f'illustration_{i + 1}_foreground_{idx + 1}.png')
            if os.path.exists(foreground_image):
                size = GenerateRemotionCode.get_image_size(foreground_image)
                image_info = {
                    'filename':
                    os.path.join('images', os.path.basename(
                        foreground_image)),  # Use basename for Remotion
                    'size':
                    size,
                    'description':
                    _req,
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
    def _generate_remotion_impl(llm, segment, audio_duration, i, image_dir,
                                config):
        component_name = f'Segment{i + 1}'
        content = segment['content']
        animation_requirement = segment['remotion']
        images_info = GenerateRemotionCode.get_all_images_info(
            segment, i, image_dir)

        # Inject image info with code snippets.
        images_info_str = ''
        if images_info:
            images_info_str += '可用图片（你必须使用以下**确切的带路径**导入/使用代码）：\n'
            for img in images_info:
                fname = img['filename']
                images_info_str += f"- 名称：{fname}（{img['size']}，{img['description']}）\n"
        else:
            images_info_str = '未提供图片。仅使用 CSS 形状/文本。'

        if config.foreground == 'image':
            image_usage = f"""**图片使用说明**
    - 你将收到一个实际的图片列表，每张图片包含三个字段：文件名、尺寸和描述，请深入考虑如何在动画中调整大小和使用这些图片
    - 确保非正方形图片的宽高比正确，编写Remotion代码时需保持图片的宽高比
    - 考虑图片与背景及整体动画的融合。使用混合/发光效果、边框、动效、装饰边等使其更美观华丽
        * 禁止将图片裁剪为圆形
        * 图片必须添加边框装饰
        * 缩放图片。不要使用原始尺寸，使图片在你的动画中的位置和大小美观合适。不要将图片放在角落
        * 禁止让图片和remotion元素重叠。请在动画中重新组织它们
    - 重要：如果图片文件列表不为空，**你必须在动画中的适当时机和位置使用所有图片**。以下是图片文件列表：

    {images_info_str}
"""
        else:
            image_usage = ''

        prompt = f"""你是一位**资深动态图形设计师**，
    使用 React（Remotion）创建高端、电影级、美观的教育动画。你的目标是创建补充旁白的视觉体验，而不仅仅是屏幕上的字幕。

    **任务**：创建 Remotion 组件
    - 组件名称：{component_name}
    - 场景要求: {animation_requirement}
    - 内容（旁白）：{content}
    - 时长：{audio_duration} 秒
    - 代码语言：**TypeScript (React)**

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
    - 使用命名导出而非默认导出(export SegmentN)
    - 文字大小不得小于25px，重点介绍文字不小于45px
    - 引用图片时使用静态资源，例子：staticFile('images/illustration_M_foreground_N.png');
    - 注意元素层叠顺序，确保z-index正确，互相位置合理
    - 防止元素超出边界：
        * **所有内容必须限制在安全区域内**：水平5%-95%，垂直10%-90%
        * **主容器必须使用**：
            1. maxWidth: '90%' 或 width: '90%'
            2. maxHeight: '80%' 或 height: '80%'
            3. margin: 'auto'（确保居中时不超出边界）
            4. translate/radial-gradient等元素，以及顶部/底部/左右对齐的使用必须考虑元素宽高的一半是否超出
        * **禁止使用固定像素值**定位元素（如 left: 300, width: 1500），必须使用百分比
        * **图片必须限制尺寸**：style={{{{maxWidth: '85%', maxHeight: '85%', objectFit: 'contain'}}}}
        * **绝对定位时检查边界**：确保 left/right/top/bottom 值在 5%-95% 和 10%-90% 范围内
    请创建满足以上要求的 Remotion 代码，打造视觉震撼的动画效果。
"""

        logger.info(f'正在生成 remotion 代码：{content}')
        _response_message = llm.generate(
            [Message(role='user', content=prompt)], temperature=0.3)
        response = _response_message.content

        # Robust code extraction using regex
        code_match = re.search(
            r'```(?:typescript|tsx|js|javascript)?\s*(.*?)```', response,
            re.DOTALL)
        if code_match:
            code = code_match.group(1)
        else:
            # Fallback: if no code blocks, assume the whole response is code
            # but try to strip leading/trailing text if it looks like markdown
            code = response

        code = code.strip()

        def fix_easing_syntax(code: str) -> str:
            pattern = r'Easing\.(\w+)\(Easing\.(\w+)\}\)'
            replacement = r'Easing.\1(Easing.\2)'

            return re.sub(pattern, replacement, code)

        code = fix_easing_syntax(code)
        return code
