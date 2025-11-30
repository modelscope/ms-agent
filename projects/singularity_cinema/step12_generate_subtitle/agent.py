# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import re
from typing import List

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.llm.openai_llm import OpenAI
from ms_agent.utils import get_logger
from omegaconf import DictConfig
from PIL import Image, ImageDraw, ImageFont

logger = get_logger()


class GenerateSubtitle(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.llm: OpenAI = LLM.from_config(self.config)
        self.subtitle_translate = getattr(self.config, 'subtitle_translate',
                                          None)
        self.subtitle_dir = os.path.join(self.work_dir, 'subtitles')
        os.makedirs(self.subtitle_dir, exist_ok=True)
        self.fonts = self.config.fonts

    async def execute_code(self, messages, **kwargs):
        if not self.config.use_subtitle:
            return messages
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)
        logger.info('Generating subtitles.')
        for i, seg in enumerate(segments):
            text = seg.get('content', '')
            text_chunks = self.split_text_to_chunks(text)         
            for j, chunk_text in enumerate(text_chunks):
                subtitle = None
                if self.subtitle_lang:
                    subtitle = await self.translate_text(chunk_text, self.subtitle_lang)
                
                output_file = os.path.join(self.subtitle_dir,
                                           f'bilingual_subtitle_{i + 1}_{j}.png')
                if os.path.exists(output_file):
                    continue
                
                self.create_bilingual_subtitle_image(
                    source=chunk_text,
                    target=subtitle,
                    output_file=output_file,
                    width=1720,
                    height=180)
        return messages

    def split_text_to_chunks(self, text, max_len: int = 30):
        punct_chars = '。！？；，、,.!?;:：；，、…—-“”""\'()[]{}<>《》【】'
        if not text:
            return []
        
        tokens = re.split(r'(\s+|[' + re.escape(punct_chars) + r'])', text)
        tokens = [t for t in tokens if t and t.strip() != '']

        def is_punct(t: str) -> bool:
            return len(t) == 1 and t in punct_chars

        chunks: List[str] = []
        cur = ''

        for t in tokens:
            if len(t) > max_len:
                if cur:
                    chunks.append(cur.strip())
                    cur = ''
                
                for i in range(0, len(t), max_len):
                    sub_chunk = t[i:i + max_len]
                    if len(sub_chunk) < max_len and i + max_len >= len(t):
                        cur = sub_chunk
                    else:
                        chunks.append(sub_chunk)
                continue

            candidate = cur + t
            
            if len(candidate) <= max_len:
                cur = candidate
                continue

            if is_punct(t) and cur and len(cur) + len(t) <= max_len + 2:
                chunks.append((cur + t).strip())
                cur = ''
                continue

            if cur.strip():
                chunks.append(cur.strip())
            cur = t

            if is_punct(cur) and chunks and len(chunks[-1]) + len(cur) <= max_len + 2:
                chunks[-1] += cur
                cur = ''

        if cur.strip():
            chunks.append(cur.strip())

        cleaned: List[str] = []
        for c in chunks:
            c = c.strip()
            if c and is_punct(c[0]) and cleaned and len(cleaned[-1]) + 1 <= max_len + 2:
                cleaned[-1] += c[0]
                c = c[1:].lstrip()
            if c:
                cleaned.append(c)

        return cleaned

    async def translate_text(self, text, to_lang):

        prompt = f"""You are a professional translation expert specializing in accurately and fluently translating text into {to_lang}.

## Skills

- Upon receiving content, translate it accurately into {to_lang}, ensuring the translation maintains the original meaning, tone, and style.
- Fully consider the context and cultural connotations to make the {to_lang} expression both faithful to the original and in line with {to_lang} conventions.
- Do not generate multiple translations for the same sentence.
- Output must conform to {to_lang} grammar standards, with clear, fluent expression and good readability.
- Accurately convey all information from the original text, avoiding arbitrary additions or deletions.
- Only provide services related to {to_lang} translation.
- Output only the translation result without any explanations.

Now translate:
""" # noqa
        messages = [
            Message(role='system', content=prompt),
            Message(role='user', content=text),
        ]

        _response_message = self.llm.generate(messages)
        return _response_message.content

    def get_font(self, size):
        """Get font using system font manager, same as CreateBackground agent"""
        import matplotlib.font_manager as fm
        for font_name in self.fonts:
            try:
                font_path = fm.findfont(fm.FontProperties(family=font_name))
                return ImageFont.truetype(font_path, size)
            except (OSError, ValueError):
                continue
        return ImageFont.load_default()

    def smart_wrap_text(self, text, max_lines=2, chars_per_line=50):
        """Break text into lines at sentence boundaries, never at commas."""
        sentence_enders = '.!?。！？'
        lines = []
        pos = 0

        while pos < len(text) and len(lines) < max_lines:
            remaining = text[pos:].lstrip()
            if not remaining:
                break

            if len(remaining) <= chars_per_line:
                lines.append(remaining)
                break

            break_pos = -1
            for i in range(chars_per_line, 0, -1):
                if i <= len(remaining) and remaining[i - 1] in sentence_enders:
                    break_pos = i
                    break

            if break_pos == -1:
                for i in range(chars_per_line, 0, -1):
                    if i <= len(remaining) and remaining[i - 1] == ' ':
                        break_pos = i
                        break

            if break_pos == -1:
                break_pos = min(chars_per_line, len(remaining))

            lines.append(remaining[:break_pos].strip())
            pos = break_pos + 1

        return lines if lines else [text]

    def create_subtitle_image(self,
                              text,
                              width=1720,
                              height=120,
                              font_size=28,
                              text_color='black',
                              bg_color='rgba(0,0,0,0)',
                              chars_per_line=50):
        font = self.get_font(font_size)
        min_font_size = 18
        max_height = 500
        original_font_size = font_size
        lines = []
        while font_size >= min_font_size:
            if font_size != original_font_size:
                font = self.get_font(font_size)
            lines = self.smart_wrap_text(
                text, max_lines=2, chars_per_line=chars_per_line)
            line_height = font_size + 8
            total_text_height = len(lines) * line_height

            all_lines_fit = True
            for line in lines:
                bbox = ImageDraw.Draw(Image.new('RGB', (1, 1))).textbbox(
                    (0, 0), line, font=font)
                line_width = bbox[2] - bbox[0]
                if line_width > width * 0.95:
                    all_lines_fit = False
                    break

            if total_text_height <= height and all_lines_fit:
                break
            elif total_text_height <= max_height and all_lines_fit:
                break
            else:
                font_size = int(font_size * 0.9)

        line_height = font_size + 8
        total_text_height = len(lines) * line_height
        actual_height = total_text_height + 16
        img = Image.new('RGBA', (width, actual_height), bg_color)
        draw = ImageDraw.Draw(img)
        y_start = 8
        for i, line in enumerate(lines):
            if not line.strip():
                continue

            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = max(0, (width - text_width) // 2)
            y = y_start + i * line_height

            if y + line_height <= actual_height and x >= 0 and x + text_width <= width:
                draw.text((x, y), line, fill=text_color, font=font)
        return img, actual_height

    def create_bilingual_subtitle_image(self,
                                        source,
                                        output_file,
                                        target='',
                                        width=1720,
                                        height=180):
        main_font_size = 32
        target_font_size = 22
        main_target_gap = 6
        pattern = r'^[a-zA-Z0-9\s.,!?;:\'"()-]+$'
        chars_per_line = 50 if not bool(re.match(pattern, source)) else 100
        if target:
            target_chars_per_line = 50 if not bool(re.match(pattern,
                                                            target)) else 100

        main_img, main_height = self.create_subtitle_image(
            source,
            width,
            height,
            main_font_size,
            'black',
            chars_per_line=chars_per_line)

        if target and target.strip():
            target_chars_per_line = 100
            target_img, target_height = self.create_subtitle_image(
                target,
                width,
                height,
                target_font_size,
                '#404040',  # Darker gray for better visibility
                chars_per_line=target_chars_per_line)
            total_height = main_height + target_height + main_target_gap
            combined_img = Image.new('RGBA', (width, total_height),
                                     (0, 0, 0, 0))
            combined_img.paste(main_img, (0, 0), main_img)
            combined_img.paste(target_img, (0, main_height + main_target_gap),
                               target_img)
            final_img = combined_img
            final_height = total_height
        else:
            final_img = main_img
            final_height = main_height

        final_img.save(output_file)
        return final_height
