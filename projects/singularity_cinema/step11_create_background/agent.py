# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import textwrap

from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM
from ms_agent.llm.openai_llm import OpenAI
from ms_agent.utils import get_logger
from omegaconf import DictConfig
from PIL import Image, ImageDraw, ImageFont

logger = get_logger(__name__)


class CreateBackground(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.bg_path = os.path.join(self.work_dir, 'background.jpg')
        self.llm: OpenAI = LLM.from_config(self.config)
        self.fonts = self.config.fonts
        self.slogan = getattr(self.config, 'slogan', [])
        self.style = getattr(self.config.text2image, 't2i_style', 'realistic')

    def get_font(self, size):
        import matplotlib.font_manager as fm
        for font_name in self.fonts:
            try:
                font_path = fm.findfont(fm.FontProperties(family=font_name))
                return ImageFont.truetype(font_path, size)
            except OSError or ValueError:
                continue
        return ImageFont.load_default()

    async def execute_code(self, messages, **kwargs):
        logger.info('Creating background.')
        with open(os.path.join(self.work_dir, 'title.txt'), 'r') as f:
            title = f.read()
        width, height = 1920, 1080
        background_color = (255, 255, 255)
        title_color = (0, 0, 0)

        config = {
            'title_font_size': 50,
            'subtitle_font_size': 54,
            'title_max_width': 15,
            'subtitle_color': (0, 0, 0),
            'line_spacing': 15,
            'padding': 50,
            'line_width': 8,
            'subtitle_offset': 40,
            'line_position_offset': 140
        }

        image = Image.new('RGB', (width, height), background_color)
        draw = ImageDraw.Draw(image)

        title_font = self.get_font(config['title_font_size'])
        subtitle_font = self.get_font(config['subtitle_font_size'])

        title_lines = textwrap.wrap(title, width=config['title_max_width'])
        y_position = config['padding']
        for line in title_lines:
            bbox = draw.textbbox((0, 0), line, font=title_font)
            draw.text((config['padding'], y_position),
                      line,
                      font=title_font,
                      fill=title_color)
            y_position += (bbox[3] - bbox[1]) + config['line_spacing']
        subtitle_lines = self.slogan
        y_position = config['padding']
        for i, line in enumerate(subtitle_lines):
            bbox = draw.textbbox((0, 0), line, font=subtitle_font)
            x_offset = width - bbox[2] - (config['padding'] + 30) + (
                i * config['subtitle_offset'])
            draw.text((x_offset, y_position),
                      line,
                      font=subtitle_font,
                      fill=config['subtitle_color'])
            y_position += bbox[3] - bbox[1] + 5

        line_y = height - config['padding'] - config['line_position_offset']
        draw.line([(0, line_y), (width, line_y)],
                  fill=(0, 0, 0),
                  width=config['line_width'])
        image.save(self.bg_path)
        return messages
