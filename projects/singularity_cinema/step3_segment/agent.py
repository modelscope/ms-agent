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

- Each storyboard panel will carry a piece of narration, one manim technical animation, one generated image background, and one subtitle
    * Use clear, high-contrast font colors to prevent text from blending with the background
    * Use a cohesive color palette of 2-4 colors for the entire video. Avoid cluttered colors, bright blue, and bright yellow. Prefer deep, dark tones
    * Low-quality animations such as stick figures are forbidden

- Each of your storyboard panels should take about 5 seconds to 10 seconds to read at normal speaking speed. Avoid the feeling of frequent switching and static
    * Pay attention to the coordination between the background image and the manim animation.
        - If a manim animation exists, the background image should not be too flashy. Else the background image will become the main focus, and the image details should be richer
        - The foreground and the background should not have the same objects. For example, draw birds at the foreground, sky and clouds at the background, other examples like charts and scientist, cloth and girls
    * If a storyboard panel has manim animation, the image should be more concise, with a stronger supporting role

- Write specific narration for each storyboard panel, technical animation requirements, and **detailed** background image requirements
    * Specify your expected manim animation content, presentation details, position and size, etc., and remind the large model generating manim of technical requirements, and **absolutely prevent size overflow and animation position overlap**
    * Estimate the reading duration of this storyboard panel to estimate the duration of the manim animation. The actual duration will be completely determined in the next step of voice generation
    * The video resolution is around 1920*1080, 200-pixel margin on all four sides for title and subtitle, so **manim can use center (1250, 700)**.
    * Use thicker lines to emphasis elements
    * Use small and medium font/elements in Manim animations to prevent from going beyond the canvas
    * LLMs excel at animation complexity, not layout complexity.
        - Use multiple storyboard scenes rather than adding more elements to one animation to avoid layout problems
        - For animations with many elements, consider layout carefully. For instance, arrange elements horizontally given the canvas's wider width
        - With four or more horizontal elements, put summary text or similar content at the canvas bottom, this will effectively reduce the cutting off and overlap problems
    * Consider the synchronization between animations and content. When read at a normal speaking pace, the content should align with the animation's progression.
    * Specify the language of the manim texts, it should be the same with the script and the storyboard content(Chinese/English for example)

- You will be given a script. Your storyboard design needs to be based on the script. You can also add some additional information you think is useful

- Review the requirements and any provided documents. Integrate their content, formulas, charts, and visuals into the script to refine the video's screenplay and animations.
    [CRITICAL]: The manim and image generation steps will not receive the original requirements and files. Supply very detail information for them, especially any data/points/formulas to prevent any mismatch with the original query and/or documentation

- Your return format is JSON format, no need to save file, later the json will be parsed out of the response body

- You need to pay attention not to use Chinese quotation marks. Use [] to replace them, for example [attention]

An example:
```json
[
    {
        "index": 1, # index of the segment, start from 1
        "content": "Now let's explain...",
        "background": "An image describe... color ... (your detailed requirements here)",
        "manim": "The animation should ... draw component ...",
    },
    ...
]
```
```

Now begin:""" # noqa

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        _config = deepcopy(config)
        _config.prompt.system = self.system
        _config.tools = DictConfig({})
        super().__init__(_config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.images_dir = os.path.join(self.work_dir, 'images')

    async def create_messages(self, messages):
        assert isinstance(messages, str)
        return [
            Message(role='system', content=self.system),
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

        query = (f'Original topic: \n\n{topic}\n\n'
                 f'Original script：\n\n{script}\n\n'
                 f'Please finish your animation storyboard design:\n')
        messages = await super().run(query, **kwargs)
        response = messages[-1].content
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]
        segments = json.loads(response)
        segments = await self.add_images(segments, topic, script, **kwargs)

        for i, segment in enumerate(segments):
            assert 'content' in segment
            assert 'background' in segment
            logger.info(
                f'\nScene {i}\n'
                f'Content: {segment["content"]}\n'
                f'Image requirement: {segment["background"]}\n'
                f'Manim requirement: {segment.get("manim", "No manim")}')
        with open(os.path.join(self.work_dir, 'segments.txt'), 'w') as f:
            f.write(json.dumps(segments, indent=4, ensure_ascii=False))
        return messages

    async def add_images(self, segments, topic, script, **kwargs):

        system = """You are an animated short video storyboard assistant designer. Your responsibility is to assist storyboard designers in adding foreground images to storyboards. You will be given a storyboard design draft and a list of images from user input that you can freely select and use.

1. Manim animation may contain one or more images, these images come from user's documentation, or a powerful text-to-image model
    * If the user's documentation contains any images, the information will be given to you:
        a. The image information will include content description, size(width*height) and filename
        b. Carefully select useful images in each segment as best as you can and reference the filename in the `user_image` field

    * User-provided images may be insufficient. Trust text-to-image models to generate additional images for more visually compelling videos
        a. Output image generation requirements and the generated filenames(with .png format) in `foreground` field
        b. The shape of generated images are square

2. The manim field is used as guidance for subsequent manim animation generation. Modify this field so that the downstream manim generation model clearly understands how to use these images.

3. The number of images used for each storyboard doesn't need to be the same, and images may not be used at all.

4. To reduce attention dispersion, you only need to focus on the image information and manim fields, and generate three fields: manim, user_image, and foreground. Your return value doesn't need to include content and background.

5. Scale the images
    * The image size on the canvas depend on its importance, important image occupies more spaces
    * Recommended size is from 1/8 to 1/4 on the canvas. If the image if the one unique element, the size can reach 1/2 or more

6. Your return length should be the same as the source storyboard length. If images are not needed, return empty user_image and foreground lists.

An example:

```json
[
    {
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
    },
    ...
]
```

An example of image structures given to the manim LLM:
```json
[
    {
        "file_path": "user_image1.jpg",
        "size": "2000*2000",
        "description": "The image contains ..."
    },
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
            segment.update(_segment)

        return segments
