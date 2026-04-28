# Copyright (c) ModelScope Contributors. All rights reserved.
import os
from copy import deepcopy

import json
from ms_agent.agent import LLMAgent
from ms_agent.llm import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class Segment(LLMAgent):

    system = """你是一名动画分镜设计师。现在有一个短视频场景需要进行分镜设计。分镜需要满足以下条件：

- 每个分镜包含：
    1. Required: 一段旁白(content)
    2. Required: 一张背景图片(background)
    3. Optional: 一个动画（manim/remotion）

- 每个分镜画面将包含一段旁白、一个{animation_engine}动画、一张背景图片
    * 使用清晰、高对比度的字体颜色，防止文字与背景混淆
    * 整个视频使用统一的配色方案，最多2种主要颜色。避免杂乱的颜色、亮蓝色或亮黄色，优先使用深色、暗色调
    * 禁止绘制几何图形表达物体，需要表达物体时生成对应的前景图片
    * 如果不需要{animation_engine}，则不要输出{animation_engine}键

- 每个分镜画面不超过10秒钟
    * 注意背景图片与{animation_engine}动画之间的颜色和内容协调。
    * 如果存在{animation_engine}动画，背景图片不应该太花哨，且背景图片中心接近纯色保证观看者聚焦在动画上
    * 前景和背景不应该描述同一事物，背景应当起到前景的烘托作用

{video_prompt}

- 为每个分镜画面编写：
    * 旁白信息
    * 背景图片具体要求
    * 动画内容要求: 描述动画要表达的主旨，组件设计和位置会有专门的worker完成。画面比例为16:9，在设计动画内容时，确保你的内容不会符合比例不会被截断，不要绘制火柴人风格的线条动画，保证动画优雅大气

- 你的分镜设计需要基于给你的脚本信息，你也可以添加一些你认为有用的额外信息

- 审阅需求和任何提供的文档。将其中的内容、公式、图表和视觉效果整合到脚本中，以完善视频的剧本和动画

- 不要在动画中复述旁白信息

- 你的返回格式是JSON格式，无需保存文件，稍后会从响应体中解析json

- 你需要注意不要使用中文引号。用[]替换它们，例如[注意]

示例：
```json
[
    {{
        "index": 1, # 片段索引，从1开始
        "content": "你在这里完善内容",
        "background": "一张图片描述... 颜色 ... （你的详细要求在这里）",
        "{animation_engine}": "动画表述...时期...的历史，需要表达出...的情绪，画面细腻有力，...",
    }},
    ...
]
```
""" # noqa

    video_prompt = """- 你可以使用文生视频功能来渲染某些镜头，这可以增强短视频的整体趣味性和可读性
    * 当使用文生视频渲染某些镜头时，返回的结构应该只包含三个字段：index、content和video。不要包含其他字段如{animation_engine}、background等。换句话说，文生视频镜头不应该包含动画引擎或背景图片
    * 视频长度固定为**5秒**，因此你还需要确保视频镜头的内容旁白不超过五秒，即不超过30个中文字符或25个英文单词
    * 不同类型的短视频有不同的文生视频比例。教育/科普视频应该有较低的文生视频比例，而短剧视频应该有较高的比例，甚至完全是文生视频
    * **生成具有强动态效果的视频，而不是只有镜头移动的静态场景。你需要在视频中讲好你的故事**
    * video字段包含你对文生视频生成的要求。注意生成的视频如何与前后镜头协调
    * 如果你使用多个文生视频镜头，注意保持角色、建筑、动物等的ID一致性
    * 需要叙述摄像机和镜头信息，集中于讲述故事、推进情节和深化主题""" # noqa

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        _config = deepcopy(config)
        _config.tools = DictConfig({})
        super().__init__(_config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.images_dir = os.path.join(self.work_dir, 'images')
        self.engine = getattr(self.config, 'animation_engine', 'remotion')

    async def create_messages(self, messages):
        assert isinstance(messages, str)
        system = self.system

        video_prompt = self.video_prompt if self.config.use_text2video else ''
        video_prompt = video_prompt.format(animation_engine=self.engine)
        system = system.format(
            video_prompt=video_prompt, animation_engine=self.engine)

        return [
            Message(role='system', content=system),
            Message(role='user', content=messages),
        ]

    async def run(self, messages, **kwargs):
        logger.info('Segmenting script to sentences.')
        if os.path.exists(os.path.join(self.work_dir, 'segments.txt')):
            return messages
        with open(os.path.join(self.work_dir, 'script.txt'), 'r') as f:
            script = f.read()
        with open(os.path.join(self.work_dir, 'topic.txt'), 'r') as f:
            topic = f.read()

        image_prompt = ''
        if self.config.background != 'image':
            image_prompt = f'\n\n背景图片无需生成，是纯色：{self.config.background}\n\n'

        query = (f'原始主题：\n\n{topic}\n\n'
                 f'原始脚本：\n\n{script}\n\n'
                 f'{image_prompt}'
                 f'请完成你的动画分镜设计：\n')
        messages = await super().run(query, **kwargs)
        response = messages[-1].content
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]
        segments = json.loads(response)
        if self.config.foreground == 'image':
            segments = await self.add_images(segments, topic, script, **kwargs)

        for i, segment in enumerate(segments):
            assert 'content' in segment
            if self.config.background == 'image':
                assert 'background' in segment or 'video' in segment
            else:
                segment['background'] = self.config.background
            if 'video' in segment:
                segment.pop('background', None)
                segment.pop('manim', None)
                segment.pop(self.engine, None)
                segment.pop('foreground', None)
            logger.info(
                f'\n场景 {i}\n'
                f'内容：{segment["content"]}\n'
                f'图片要求：{segment.get("background", "无背景")}\n'
                f'视频要求：{segment.get("video", "非视频片段")}\n'
                f'动画要求：{segment.get(self.engine, segment.get("manim", "无动画"))}'
            )
        with open(os.path.join(self.work_dir, 'segments.txt'), 'w') as f:
            f.write(json.dumps(segments, indent=4, ensure_ascii=False))
        return messages

    async def add_images(self, segments, topic, script, **kwargs):

        video_prompt = ('注意：不需要修改包含video字段的镜头。这些镜头是文生视频镜头，它不需要背景、动画或前景图片。'
                        '只需在返回值中保留并返回这些镜头的index即可。')
        if not self.config.use_text2video:
            video_prompt = ''

        system = """你是一名动画短视频分镜助理设计师。你的职责是协助分镜设计师为分镜添加前景图片。你将获得一个分镜设计草稿和一个用户输入的图片列表，你可以自由选择和使用。

1. {animation_engine_cap}动画可能包含一张或多张图片；这些图片来自用户的文档，或强大的文生图模型
    * 如果用户的文档包含任何图片，相关信息将提供给你：
        a. 图片信息将包括内容描述、尺寸（宽*高）和文件名
        b. 仔细在每个片段中选择有用的图片，尽你所能并在`user_image`字段中引用文件名

    * 用户提供的图片可能不足。文生图模型可以生成额外的图片以制作更具视觉吸引力的视频
        a. 在`foreground`字段中输出图片生成要求和生成的文件名（使用.png格式）

2. {animation_engine}字段描述了动画需求
    * 如果有必要，你可以重写{animation_engine}字段
    * 每个分镜不超过2张图片，图片越多，每张图片应该越小，反之越大
    * 一张图片只能使用一次（一个分镜中的一个位置）

3. 每个分镜使用的图片数量不需要相同，也可能完全不使用图片。

4. 为减少注意力分散，你只需要关注图片信息和{animation_engine}字段，并生成三个字段：{animation_engine}、user_image和foreground。你的返回值不需要包含content和background。

6. 你的返回长度应该与源分镜长度相同，不要遗漏任何片段。如果不需要图片，返回空的user_image和foreground列表。

{video_prompt}

示例：

```json
[
    {{
        "index": 1, # 片段索引，从1开始
        "{animation_engine}": "动画应该 ...，使用图片来... ",
        "user_image": [
            "user_image1.jpg",
            "user_image2.jpg"
        ]
        "foreground": [
            "一张图片描述... 颜色 ... （你的详细要求在这里）",
            ...
        ],
    }},
    ...
]
```

提供给{animation_engine}大语言模型的图片结构示例：
```json
[
    {{
        "file_path": "user_image1.jpg",
        "size": "2000*2000",
        "description": "图片包含 ..."
    }},
    ...
]

现在开始：
""" # noqa
        # Format the system prompt with the actual engine name
        animation_engine = self.engine
        animation_engine_cap = animation_engine.capitalize()
        system = system.format(
            video_prompt=video_prompt,
            animation_engine=animation_engine,
            animation_engine_cap=animation_engine_cap)

        new_image_info = '未提供图片。'
        name_mapping = {}
        if os.path.exists(os.path.join(self.work_dir, 'image_info.txt')):
            with open(os.path.join(self.work_dir, 'image_info.txt'), 'r') as f:
                image_info = f.readlines()

            image_info = [
                image.strip() for image in image_info if image.strip()
            ]
            image_list = []
            for i, info in enumerate(image_info):
                info = json.loads(info)
                filename = info['filename']
                new_filename = f'user_image_{i}.png'
                name_mapping[new_filename] = filename
                info['filename'] = new_filename
                image_list.append(json.dumps(info, ensure_ascii=False))

            new_image_info = json.dumps(image_list, ensure_ascii=False)

        query = (
            f'原始主题：\n\n{topic}\n\n'
            f'原始脚本：\n\n{script}\n\n'
            f'原始分镜：\n\n{json.dumps(segments, ensure_ascii=False, indent=4)}\n\n'
            f'用户提供的图片：\n\n{new_image_info}\n\n'
            f'请完成你的图片设计：\n')
        messages = [
            Message(role='system', content=system),
            Message(role='user', content=query),
        ]
        message = self.llm.generate(messages, **kwargs)
        response = message.content
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]
        _segments = json.loads(response)

        for i, segment in enumerate(_segments):
            user_images = segment.get('user_image', [])
            new_user_images = []
            for image in user_images:
                if image in name_mapping:
                    new_user_images.append(name_mapping[image])
            segment['user_image'] = new_user_images

        assert len(_segments) == len(segments)
        for segment, _segment in zip(segments, _segments):
            assert segment['index'] == _segment['index']
            if 'video' in segment:
                continue
            segment.update(_segment)

        return segments
