# Copyright (c) Alibaba, Inc. and its affiliates.
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
        foreground = segment.get('foreground', [])
        for idx, _req in enumerate(foreground):
            foreground_image = os.path.join(
                image_dir, f'illustration_{i + 1}_foreground_{idx + 1}.png')
            size = GenerateManimCode.get_image_size(foreground_image)
            image_info = {
                'filename': foreground_image,
                'size': size,
                'description': _req,
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
            images_info = 'No images offered.'

        if config.foreground == 'image':
            image_usage = f"""**Image usage**
- You'll receive an actual image list with three fields per image: filename, size, and description，consider deeply how to resize and use them in your animation
- Pay attention to the size field, write Manim code that respects the image's aspect ratio, size it.
- Consider the image integration with the background and overall animation. Use blending/glow effects, frames, movements, borders etc. to make it more beautiful and gorgeous
    * You can more freely consider the integration of images to achieve a better presentation
    * Image sizes should be **medium OR small** to prevent them from occupying the entire screen or most of the screen, **huge image is strictly forbidden**
    * Ensure aspect ratios of non-square images remain correct
    * DO NOT crop image to circular
    * Images must be decorated with frames
    * IMPORTANT: **Use smaller image sizes for generated images and larger image sizes for user doc images. DO NOT crop image to circular**
- IMPORTANT: If images files are not empty, **you must use them all at the appropriate time and position in your animation**. Here is the image files list:

{images_info}

DO NOT let the image and the manim element overlap. Reorganize them in your animation.

* Scale the images. Do not use the original size, carefully rescale the images to match the requirements below:
    a. The image size on the canvas depend on its importance, important image occupies more spaces
        * Consider the image placement in the manim requirements, resize the image until it will not be cut off by the edge(within x∈(-6.0, 6.0), y∈(-3.4, 3.4) with minimum buff=0.5)
        * Resize generated images by scale(<0.4), if 2 images, resize by scale(<0.3)
    b. Use 1/4 space of the canvas for each image""" # noqa
        else:
            image_usage = ''

        prompt = f"""You are a professional Manim animation expert, creating clear and beautiful educational animations.

**Task**: Create animation
- Class name: {class_name}
- Content: {content}
- Requirement from the storyboard designer: {manim_requirement}
    * If the storyboard designer's layout is poor, create a better custom layout
- Duration: {audio_duration} seconds
- Code language: **Python**

{image_usage}

* Canvas size ratio: 16:9
* Ensure all content stays within safe bounds x∈(-6.0, 6.0), y∈(-3.4, 3.4) with minimum buff=0.5 from any edge to prevent cropping.
* [CRITICAL]Absolutely prevent **element spatial overlap** or **elements going out of bounds** or **elements not aligned**.
* [CRITICAL]Connection lines between boxes/text are of proper length, with **both endpoints attached to the objects**.
* All boxes must have thick strokes for clear visibility
* Keep text within frame by controlling font sizes. Use smaller fonts for Latin script than Chinese due to longer length.
* Use clear, high-contrast font colors to prevent text from blending with the background
* Use a cohesive color palette of 2-4 colors for the entire video. Avoid cluttered colors, bright blue, and bright yellow. Prefer deep, dark tones
* Low-quality animations such as stick figures are forbidden
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

Please create Manim animation code that meets the above requirements.""" # noqa

        logger.info(f'Generating manim code for: {content}')
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
