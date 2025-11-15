# Copyright (c) Alibaba, Inc. and its affiliates.
import os

import json
from ms_agent.agent import LLMAgent
from ms_agent.llm import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class Segment(LLMAgent):

    system = """You are an animation storyboard designer. Now there is a short video scene that needs storyboard design. The storyboard needs to meet the following conditions:

1. Each storyboard panel will carry a piece of narration, (at most) one manim technical animation, one generated image background, and one subtitle
    * You can freely decide whether the manim animation exists. If the manim animation is not needed, the manim key can be omitted from the return value
    * For tech-related short videos, they should have a technical and professional feel. For product-related short videos, they should be gentle and authentic, avoiding exaggerated expressions such as "shocking", "solved by xxx", "game-changing," "rule-breaking," or "truly achieved xx", etc. Describe things objectively and accurately.
    * Consider the color style across all storyboards comprehensively, for example, all purple style, all deep blue style, etc.
        - Consider more colors like white, black, dark blue, dark purple, dark orange, etc, which will make your design elegant, avoid using light yellow/blue, which will make your animation look superficial, DO NOT use grey color, it's not easy to read
    * Use less stick man unless the user wants to, to prevent the animation from being too naive, try to make your effects more dazzling/gorgeous/spectacular/blingbling
2. Each of your storyboard panels should take about 5 seconds to 10 seconds to read at normal speaking speed. Avoid the feeling of frequent switching and static
    * If a storyboard panel has no manim animation, it should not exceed 5s
    * Pay attention to the coordination between the background image and the manim animation.
        - If a manim animation exists, the background image should not be too flashy. Else the background image will become the main focus, and the image details should be richer
        - The foreground and the background should not have the same objects. For example, draw birds at the foreground, sky and clouds at the background, other examples like charts and scientist, cloth and girls
    * If a storyboard panel has manim animation, the image should be more concise, with a stronger supporting role
3. Write specific narration for each storyboard panel, technical animation requirements, and **detailed** background image requirements
    * Specify your expected manim animation content, presentation details, position and size, etc., and remind the large model generating manim of technical requirements, and **absolutely prevent size overflow and animation position overlap**
    * Estimate the reading duration of this storyboard panel to estimate the duration of the manim animation. The actual duration will be completely determined in the next step of voice generation
    * The video resolution is around 1920*1080, 200-pixel margin on all four sides for title and subtitle, so manim can use center (1500, 700).
    * Use thicker lines to emphasis elements
    * Use smaller font size and smaller elements in Manim animations to prevent from going beyond the canvas
    * LLMs excel at animation complexity, not layout complexity.
        - Use multiple storyboard scenes rather than adding more elements to one animation to avoid layout problems
        - For animations with many elements, consider layout carefully. For instance, arrange elements horizontally given the canvas's wider width
        - With four or more horizontal elements, put summary text or similar content at the canvas bottom, this will effectively reduce the cutting off and overlap problems
    * Consider the synchronization between animations and content. When read at a normal speaking pace, the content should align with the animation's progression.
    * Specify the language of the manim texts, it should be the same with the script and the storyboard content(Chinese/English for example)
4. You will be given a script. Your storyboard design needs to be based on the script. You can also add some additional information you think is useful
5. Review the requirements and any provided documents. Integrate their content, formulas, charts, and visuals into the script to refine the video's screenplay and animations.
    [CRITICAL]: The manim and image generation steps will not receive the original requirements and files. Supply very detail information for them, especially any data/points/formulas to prevent any mismatch with the original query and/or documentation
6. Your return format is JSON format, no need to save file, later the json will be parsed out of the response body
7. You need to pay attention not to use Chinese quotation marks. Use [] to replace them, for example [attention]

An example:
```json
[
    {
        "index": 1, # index of the segment, start from 1
        "content": "Now let's explain...",
        "background": "An image describe... color ... (your detailed requirements here)",
        "manim": "The animation should ... line thick... element color ... position ... (your detailed requirements here)",
    },
    ...
]
```

Now begin:""" # noqa

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        config.prompt.system = self.system
        config.tools = DictConfig({
            'file_system': {
                'mcp': False,
                'exclude': ['create_directory', 'write_file']
            }
        })
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')

    async def create_messages(self, messages):
        assert isinstance(messages, str)
        return [
            Message(role='system', content=self.system),
            Message(role='user', content=messages),
        ]

    async def run(self, *args, **kwargs):
        logger.info('Segmenting script to sentences.')
        script = None
        with open(os.path.join(self.work_dir, 'script.txt'), 'r') as f:
            script = f.read()
        with open(os.path.join(self.work_dir, 'topic.txt'), 'r') as f:
            topic = f.read()
        query = (
            f'Original topic: \n\n{topic}\n\n，original script：\n\n{script}\n\n'
            f'Please finish your animation storyboard design:\n')
        messages = await super().run(query, **kwargs)
        response = messages[-1].content
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0]
        elif '```' in response:
            response = response.split('```')[1].split('```')[0]
        segments = json.loads(response)
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
