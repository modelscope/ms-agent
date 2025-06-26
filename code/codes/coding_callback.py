# Copyright (c) Alibaba, Inc. and its affiliates.
from typing import List

import json
from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.tools.filesystem_tool import FileSystemTool
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class CodingCallback(Callback):
    """Add more prompts when coding
    """

    _frontend_prompt = """* **Overall Style:** Consider magazine-style, publication-style, or other modern web design styles you deem appropriate. The goal is to create a page that is both informative and visually appealing, like a well-designed digital magazine or in-depth feature article.

    * **Hero Section (Optional but Strongly Recommended):** If you think it's appropriate, design an eye-catching Hero section. It can include a main headline, subtitle, an engaging introductory paragraph, and a high-quality background image or illustration.

    * **Typography:**
      * Carefully select font combinations (serif and sans-serif) to enhance the reading experience.
      * Use different font sizes, weights, colors, and styles to create a clear visual hierarchy.
      * Consider using refined typographic details (such as drop caps, hanging punctuation) to enhance overall quality.
      * Font Awesome has many icons - choose appropriate ones to add visual interest and playfulness.

    * **Color Scheme:**
      * Choose a color palette that is both harmonious and visually impactful.
      * Consider using high-contrast color combinations to highlight important elements.
      * Explore gradients, shadows, and other effects to add visual depth.

    * **Layout:**
      * Use a grid-based layout system to organize page elements.
      * Make full use of negative space (whitespace) to create visual balance and breathing room.
      * Consider using cards, dividers, icons, and other visual elements to separate and organize content.

    * **Tone:** Overall style should be refined, creating a sense of sophistication.

    * **Data Visualization:**
      * Design one or more data visualization elements to showcase key concepts of Naval's thinking and their relationships.
      * Consider using mind maps, concept relationship diagrams, timelines, or thematic clustering displays.
      * Ensure visualization design is both beautiful and insightful, helping users intuitively understand the overall framework of Naval's thought system.
      * Use Mermaid.js to implement interactive charts that allow users to explore connections between different concepts.

    **Technical Specifications:**

    *   Use HTML5、Font Awesome、Tailwind CSS and necessary JavaScript。
        *   Font Awesome: [https://cdn.staticfile.org/font-awesome/6.4.0/css/all.min.css](https://cdn.staticfile.org/font-awesome/6.4.0/css/all.min.css)
        *   Tailwind CSS: [https://cdn.staticfile.org/tailwindcss/2.2.19/tailwind.min.css](https://cdn.staticfile.org/tailwindcss/2.2.19/tailwind.min.css)
        *   Font for non-Chinese: [https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;500;600;700&family=Noto+Sans+SC:wght@300;400;500;700&display=swap](https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;500;600;700&family=Noto+Sans+SC:wght@300;400;500;700&display=swap)
        *   `font-family: Tahoma,Arial,Roboto,"Droid Sans","Helvetica Neue","Droid Sans Fallback","Heiti SC","Hiragino Sans GB",Simsun,sans-self;`
        *   Mermaid: [https://cdn.jsdelivr.net/npm/mermaid@latest/dist/mermaid.min.js](https://cdn.jsdelivr.net/npm/mermaid@latest/dist/mermaid.min.js)

    * Implement a complete dark/light mode toggle functionality that follows system settings by default and allows users to manually switch.
    * Code structure should be clear and semantic, including appropriate comments.
    * Implement complete responsiveness that must display perfectly on all devices (mobile, tablet, desktop).
    """  # noqa

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.file_system = FileSystemTool(config)

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        await self.file_system.connect()

    async def on_tool_call(self, runtime: Runtime, messages: List[Message]):
        if not messages[-1].tool_calls or messages[-1].tool_calls[0][
                'tool_name'] != 'split_to_sub_task':
            return
        assert messages[0].role == 'system'
        arch_design = messages[2].content
        files = await self.file_system.list_files()
        arguments = messages[-1].tool_calls[0]['arguments']
        arguments = json.loads(arguments)
        tasks = arguments['tasks']
        if isinstance(tasks, str):
            tasks = json.loads(tasks)
        for task in tasks:
            task['_system'] = task['system']
            task['system'] = (
                f'{task["system"]}\n\n'
                f'The architectural design is {arch_design}\n\n'
                f'The coding instruction of frontend: {self._frontend_prompt}\n\n'
                f'The files existing on the filesystem is: {files}\n\n'
                f'If you have code files to save, output your code with this format:\n\n'
                f'```js:index.js\n'
                f'... code ...\n'
                f'```\n'
                f'The `index.js` will be used to saving. '
                f'You only need to generate/fix/analyze the files listed in the query, '
                f'other modules will be handled in other tasks.\n'
                f'You need consider the interfaces between your and other modules '
                f'according to the architectural design.\n\n '
                f'Do not leave a blank image placeholder, you should use image links from unsplash\n\n'
                f'Now Begin:\n')
        messages[-1].tool_calls[0]['arguments'] = json.dumps({'tasks': tasks})

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        if not messages[-2].tool_calls or messages[-2].tool_calls[0][
                'tool_name'] != 'split_to_sub_task':
            return
        assert messages[0].role == 'system'
        arguments = messages[-2].tool_calls[0]['arguments']
        arguments = json.loads(arguments)
        tasks = arguments['tasks']
        if isinstance(tasks, str):
            tasks = json.loads(tasks)
        for task in tasks:
            task['system'] = task['_system']
            task.pop('_system')
        messages[-2].tool_calls[0]['arguments'] = json.dumps({'tasks': tasks})
