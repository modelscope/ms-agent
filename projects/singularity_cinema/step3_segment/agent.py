# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from copy import deepcopy

import json
from ms_agent.agent import LLMAgent
from ms_agent.llm import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class Segment(LLMAgent):

    system = """You are an animation storyboard designer. Now there is a short video scene that needs storyboard design. The storyboard needs to meet the following conditions:

- Each storyboard panel will carry a piece of narration, one manim animation(optional), one image background, and one subtitle, even one video(optional)
    * Use clear, high-contrast font colors to prevent text from blending with the background
    * Use a cohesive color palette of 2-4 colors for the entire video. Avoid cluttered colors, bright blue, and bright yellow. Prefer deep, dark tones
    * Low-quality animations such as stick figures are forbidden
    * If no manim needed, do not output the manim key

- Each of your storyboard panels should take about 5~8 seconds to read at normal speaking speed. Avoid the feeling of frequent switching and static
    * Pay attention to the color and content coordination between the background image and the manim animation.
    * If a manim animation exists, the background image should not be too flashy. Else the background image will become the main focus, and the image details should be richer
    * The foreground and the background should not describe the same thing. For example, draw birds at the foreground, sky and clouds at the background, other examples like charts and scientist, cloth and girls
    * If a storyboard panel has manim animation, the image should be more concise, with a stronger supporting role

{video_prompt}

- Write specific narration for each storyboard panel, technical animation requirements, and **detailed** background image requirements
    * Specify your expected manim animation content, presentation details, position and size, etc., and remind the large model generating manim of technical requirements, and **absolutely prevent size overflow and animation position overlap**
    * Estimate the reading duration of this storyboard panel to estimate the duration of the manim animation. The actual duration will be completely determined in the next step of voice generation
    * The video resolution is around 1920*1080, **the ratio of the manim size is 16:9**.
    * Use thicker lines to emphasis elements
    * Use small/medium size of font/elements in manim animations to prevent from cutting off by the edge
    * LLMs excel at animation complexity, not layout complexity.
        - Use multiple storyboard scenes rather than adding more elements to one animation to avoid layout problems
        - For animations with many elements, consider layout carefully. For instance, arrange elements horizontally given the canvas's wider width
        - With four or more horizontal elements, put summary text or similar content at the canvas bottom, this will effectively reduce the cutting off and overlap problems
    * Consider the synchronization between animations and content. When read at a normal speaking pace, the content should align with the animation's progression.
    * Specify the language of the manim texts, it should be the same with the script and the storyboard content(Chinese/English for example)
    * Do not use any matchstick-style or pixel-style animations. Use charts, images, industrial/academic-style animations
    * Text box needs to have a background color, and the background must be opaque, with high contrast between the text color and the background.
    * The text box should large enough to contain the text
    * Do not create multi-track complex manim animations. One object per segment, or two to three(NO MORE THAN three!) object arranged in a simple manner, manim layout rules:
        1. One object in the middle
        2. Two objects, left-right structure, same y axis, same size, for example, text left, chart right
        3. Three objects, left-middle-right structure, same y axis, same size. No more than 3 elements in one segment
        4. Split complex animation into several segments
        5. Less text boxes in the animation, only titles/definitions/formulas
        6. Use black fonts, **no gray fonts**
        7. CRITICAL: **NEVER put an element to a corner, do use horizonal/vertical grid**
        8. No pie charts should be used, the LLM costs many bugs

- You will be given a script. Your storyboard design needs to be based on the script. You can also add some additional information you think is useful

- Review the requirements and any provided documents. Integrate their content, formulas, charts, and visuals into the script to refine the video's screenplay and animations.
    [CRITICAL]: The manim and image generation steps will not receive the original requirements and files. Supply very detail information for them, especially any data/points/formulas to prevent any mismatch with the original query and/or documentation

- DO NOT print the `content` information in the animation; `content` will be added separately as subtitle to the video

- Your return format is JSON format, no need to save file, later the json will be parsed out of the response body

- You need to pay attention not to use Chinese quotation marks. Use [] to replace them, for example [attention]

An example:
```json
[
    {
        "index": 1, # index of the segment, start from 1
        "content": "Your refine here",
        "background": "An image describe... color ... (your detailed requirements here)",
        "manim": "The animation should ... draw component ...",
    },
    ...
]
```
```

Now begin:""" # noqa

    pure_color_system = """You are an animation storyboard designer. Now there is a short video scene that needs storyboard design. The storyboard needs to meet the following conditions:

- Each storyboard panel will carry a piece of narration, one manim animation(optional), and one subtitle, even one video(optional)
    * Use clear, high-contrast font colors to prevent text from blending with the background
    * Use a cohesive color palette of 2-4 colors for the entire video. Avoid cluttered colors, bright blue, and bright yellow. Prefer deep, dark tones
    * Low-quality animations such as stick figures are forbidden
    * If no manim needed, do not output the manim key

- Each of your storyboard panels should take about 5~8 seconds to read at normal speaking speed. Avoid the feeling of frequent switching and static
    * Pay attention to the color and content coordination between the background image and the manim animation.
    * Based on the background image color, select manim color scheme to make the foreground as clear as possible.

{video_prompt}

- Write specific narration for each storyboard panel, technical animation requirements
    * Specify your expected manim animation content, presentation details, position and size, etc., and remind the large model generating manim of technical requirements, and **absolutely prevent size overflow and animation position overlap**
    * Estimate the reading duration of this storyboard panel to estimate the duration of the manim animation. The actual duration will be completely determined in the next step of voice generation
    * The video resolution is around 1920*1080, **the ratio of the manim size is 16:9**.
    * Use thicker lines to emphasis elements
    * Use small/medium size of font/elements in manim animations to prevent from cutting off by the edge
    * LLMs excel at animation complexity, not layout complexity.
        - Use multiple storyboard scenes rather than adding more elements to one animation to avoid layout problems
        - For animations with many elements, consider layout carefully. For instance, arrange elements horizontally given the canvas's wider width
        - With four or more horizontal elements, put summary text or similar content at the canvas bottom, this will effectively reduce the cutting off and overlap problems
    * Consider the synchronization between animations and content. When read at a normal speaking pace, the content should align with the animation's progression.
    * Specify the language of the manim texts, it should be the same with the script and the storyboard content(Chinese/English for example)
    * Do not use any matchstick-style or pixel-style animations. Use charts, images, industrial/academic-style animations
    * Text box needs to have a background color, and the background must be opaque, with high contrast between the text color and the background.
    * The text box should large enough to contain the text
    * Do not create multi-track complex manim animations. One object per segment, or two to three(NO MORE THAN three!) object arranged in a simple manner, manim layout rules:
        1. One object in the middle
        2. Two objects, left-right structure, same y axis, same size, for example, text left, chart right
        3. Three objects, left-middle-right structure, same y axis, same size. No more than 3 elements in one segment
        4. Split complex animation into several segments
        5. Less text boxes in the animation, only titles/definitions/formulas
        6. Use black fonts, **no gray fonts**
        7. CRITICAL: **NEVER put an element to a corner, do use horizonal/vertical grid**
        8. No pie charts should be used, the LLM costs many bugs

- You will be given a script. Your storyboard design needs to be based on the script. You can also add some additional information you think is useful

- Review the requirements and any provided documents. Integrate their content, formulas, charts, and visuals into the script to refine the video's screenplay and animations.
    [CRITICAL]: The manim steps will not receive the original requirements and files. Supply very detail information for them, especially any data/points/formulas to prevent any mismatch with the original query and/or documentation

- DO NOT print the `content` information in the animation; `content` will be added separately as subtitle to the video

- Your return format is JSON format, no need to save file, later the json will be parsed out of the response body

- You need to pay attention not to use Chinese quotation marks. Use [] to replace them, for example [attention]

An example:
```json
[
    {
        "index": 1, # index of the segment, start from 1
        "content": "Your refine here",
        "manim": "The animation should ... draw component ...",
    },
    ...
]
```

Now begin:"""  # noqa

    video_prompt = """- You can use text-to-video functionality to render certain shots, which can enhance the overall interest and readability of the short video
    * When using text-to-video to render certain shots, the returned structure should only include three fields: index, content, and video. Do not include other fields such as manim, background, etc. In other words, text-to-video shots should not include manim animations or background images
    * Video length is fixed at **5 seconds**, therefore you are additionally required to ensure that the content narration for video shots should not exceed five seconds, meaning it should not exceed 30 Chinese characters or 25 English words
    * Different types of short videos have different text-to-video ratios. Educational/scientific videos should have a lower text-to-video ratio, while short drama videos should have a higher ratio or even be entirely text-to-video
    * **Generate videos with strong dynamics, rather than static scenes with only camera movement. You need to tell your story well within the video**
    * The video field contains your requirements for text-to-video generation. Pay attention to how the generated video coordinates with the preceding and following shots
    * If you use multiple text-to-video shots, pay attention to maintaining consistent IDs for characters, buildings, animals, etc.
    * The content for video shots should not include cinematic language elements like "camera" or "lens," but should instead be used to narrate the visual story, advance the plot, and deepen the theme""" # noqa

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

    async def create_messages(self, messages):
        assert isinstance(messages, str)
        system = self.system if self.config.background == 'image' else self.pure_color_system
        if self.config.use_text2video:
            system = system.replace('{video_prompt}', self.video_prompt)
        else:
            system = system.replace('{video_prompt}', '')
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
            image_prompt = f'\n\nThe background image is pure color: {self.config.background}\n\n'

        query = (f'Original topic: \n\n{topic}\n\n'
                 f'Original script：\n\n{script}\n\n'
                 f'{image_prompt}'
                 f'Please finish your animation storyboard design:\n')
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
                segment.pop('foreground', None)
            logger.info(
                f'\nScene {i}\n'
                f'Content: {segment["content"]}\n'
                f'Image requirement: {segment.get("background", "No background")}\n'
                f'Video requirement: {segment.get("video", "Not a video segment")}\n'
                f'Manim requirement: {segment.get("manim", "No manim")}')
        with open(os.path.join(self.work_dir, 'segments.txt'), 'w') as f:
            f.write(json.dumps(segments, indent=4, ensure_ascii=False))
        return messages

    async def add_images(self, segments, topic, script, **kwargs):

        video_prompt = (
            'Note: No need to modify shots that contain a video field. These shots are text-to-video shots '
            'and do not require background, manim animations, or foreground images. '
            'Simply keep and return the index of these shots in the return value.'
        )
        if not self.config.use_text2video:
            video_prompt = ''

        system = f"""You are an animated short video storyboard assistant designer. Your responsibility is to assist storyboard designers in adding foreground images to storyboards. You will be given a storyboard design draft and a list of images from user input that you can freely select and use.

1. Manim animation may contain one or more images, these images come from user's documentation, or a powerful text-to-image model
    * If the user's documentation contains any images, the information will be given to you:
        a. The image information will include content description, size(width*height) and filename
        b. Carefully select useful images in each segment as best as you can and reference the filename in the `user_image` field

    * User-provided images may be insufficient. Trust text-to-image models to generate additional images for more visually compelling videos
        a. Output image generation requirements and the generated filenames(with .png format) in `foreground` field
        b. The shape of generated images are square

    * Important: Use smaller image sizes for generated images and larger image sizes for user doc images. DO NOT crop image to circular**

2. The manim field is a guidance for subsequent manim animation generation
    * Ignore the input manim, completely rewrite the manim field to ensure that images and other manim animations are neatly arranged. Images should be a reasonable part of the overall manim layout, appearing in reasonable positions.
    * No more than 2 images in a segment, 0 image in one segment is allowed
    * When 2 images, each image should be smaller
    * One image can only use once(one segment and one position)
    * DO NOT put images to the corner, left or right is Ok
    * Images must be decorated with frames

    Manim layouts:
    * Do not create multi-track complex manim animations. One object per segment, or two to three(NO MORE THAN three!) object arranged in a simple manner, manim layout rules:
        1. One object in the middle
        2. Two objects, left-right structure, same y axis, same size, for example, text left, chart right
        3. Three objects, left-middle-right structure, same y axis, same size. No more than 3 elements in one segment
        4. Split complex animation into several segments
        5. Less text boxes in the animation, only titles/definitions/formulas
        6. Use black fonts, **no gray fonts**
        7. CRITICAL: **NEVER put an element to a corner, do use horizonal/vertical grid**
        8. No pie charts should be used, the LLM costs many bugs

3. The number of images used for each storyboard doesn't need to be the same, and images may not be used at all.

4. To reduce attention dispersion, you only need to focus on the image information and manim fields, and generate three fields: manim, user_image, and foreground. Your return value doesn't need to include content and background.

5. Scale the images. Do not use the original size, carefully rescale the images to match the requirements below:
    * The image size on the canvas depend on its importance, important image occupies more spaces
    * Use 1/4 space of the canvas for each image

6. Your return length should be the same as the source storyboard length, do not miss any segment. If images are not needed, return empty user_image and foreground lists.

7. DO NOT print the `content` information in the animation; `content` will be added separately as subtitle to the video

{video_prompt}

An example:

```json
[
    {{
        "index": 1, # index of the segment, start from 1
        "manim": "The animation should ..., use images to... ",
        "user_image": [
            "user_image1.jpg",
            "user_image2.jpg"
        ]
        "foreground": [
            "An image describe... color ... (your detailed requirements here)",
            ...
        ],
    }},
    ...
]
```

An example of image structures given to the manim LLM:
```json
[
    {{
        "file_path": "user_image1.jpg",
        "size": "2000*2000",
        "description": "The image contains ..."
    }},
    ...
]

Now begin:
""" # noqa
        new_image_info = 'No images offered.'
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
            f'Original topic: \n\n{topic}\n\n'
            f'Original script：\n\n{script}\n\n'
            f'Original segments：\n\n{json.dumps(segments, ensure_ascii=False, indent=4)}\n\n'
            f'User offered images: \n\n{new_image_info}\n\n'
            f'Please finish your images design:\n')
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
