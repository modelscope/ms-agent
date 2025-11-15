# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Union

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

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
                                idx, self.config): idx
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
    def _generate_manim_code_static(segment, audio_duration, i, config):
        """Static method for multiprocessing"""
        llm = LLM.from_config(config)
        return GenerateManimCode._generate_manim_impl(llm, segment,
                                                      audio_duration, i)

    @staticmethod
    def _generate_manim_impl(llm, segment, audio_duration, i):
        class_name = f'Scene{i + 1}'
        content = segment['content']
        manim_requirement = segment['manim']

        prompt = f"""You are a professional Manim animation expert, creating clear and beautiful educational animations.

**Task**: Create animation
- Class name: {class_name}
- Content: {content}
- Requirement from the storyboard designer: {manim_requirement}
    * If the storyboard designer's layout is poor, create a better custom layout
- Duration: {audio_duration} seconds
- Code language: **Python**

**Spatial Constraints (CRITICAL)**:
• Canvas size: (1500, 700) (width x height) which is the top 3/4 of screen, bottom is left for subtitles
• Safe area: x∈(-6.5, 6.5), y∈(-3.2, 3.2) (0.5 units from edge)
• Element spacing: Use buff=0.3 or larger (avoid overlap)
• Relative positioning: Prioritize next_to(), align_to(), shift()
• Avoid multiple elements using the same reference point
• [CRITICAL]Absolutely prevent **element spatial overlap** or **elements going out of bounds** or **elements not aligned**.
• [CRITICAL]Connection lines between boxes/text are of proper length, with **both endpoints attached to the objects**.

**Box/Rectangle Size Standards**:
• For diagram boxes: Use consistent dimensions, e.g., Rectangle(width=2.5, height=1.5)
• For labels/text boxes: width=1.5~3.0, height=0.8~1.2
• For emphasis boxes: width=3.0~4.0, height=1.5~2.0
• Always specify both width AND height explicitly: Rectangle(width=2.5, height=1.5)
• Avoid using default sizes - always set explicit dimensions
• Maintain consistent box sizes within the same diagram level/category
• All boxes must have thick strokes for clear visibility
• Keep text within frame by controlling font sizes. Use smaller fonts for Latin script than Chinese due to longer length.
• Ensure all pie chart pieces share the same center coordinates. Previous pie charts were drawn incorrectly.

**Visual Quality Enhancement**:
• Use thick, clear strokes for all shapes
    - 4~6 strokes is recommended
• Make arrows bold and prominent
• Add rounded corners for modern aesthetics: RoundedRectangle(corner_radius=0.15)
• Use subtle fill colors with transparency when appropriate: fill_opacity=0.1
• Ensure high contrast between elements for clarity
• Apply consistent spacing and alignment throughout
• Use less stick man unless the user wants to, to prevent the animation from being too naive, try to make your effects more dazzling/gorgeous/spectacular/blingbling

**Layout Suggestions**:
• Content clearly layered
• Key information highlighted
• Reasonable use of space
• Maintain visual balance
• LLMs excel at animation complexity, not layout complexity.
    - Use multiple storyboard scenes rather than adding more elements to one animation to avoid layout problems
    - For animations with many elements, consider layout carefully. For instance, arrange elements horizontally given the canvas's wider width
    - With four or more horizontal elements, put summary text or similar content at the canvas bottom, this will effectively reduce the cutting off and overlap problems

**Animation Requirements**:
• Concise and smooth animation effects
• Progressive display, avoid information overload
• Appropriate pauses and rhythm
• Professional visual presentation with thick, clear lines
• Use GrowArrow for arrows instead of Create for better effect
• Consider using Circumscribe or Indicate to highlight important elements

**Code Style**:
• Clear comments and explanations
• Avoid overly complex structures

**Color Suggestions**:
• You need to explicitly specify element colors and make these colors coordinated and elegant in style.
• Consider the advices from the storyboard designer.
• Don't use light yellow, light blue, etc., as this will make the animation look superficial.
• Consider more colors like white, black, dark blue, dark purple, dark orange, etc. DO NOT use grey color, it's not easy to read

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
