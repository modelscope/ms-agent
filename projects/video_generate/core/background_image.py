from PIL import Image, ImageDraw, ImageFont
import textwrap
import os
import time
import uuid
import matplotlib.font_manager as fm

class BackgroundImageGenerator:
    def __init__(self, topic=None):
        self.width = 1920
        self.height = 1080
        self.background_color = (255, 255, 255)
        self.title_color = (0, 0, 0)
        self.topic = topic
        
        self.config = {
            'title_font_size': 50,
            'subtitle_font_size': 54,  
            'title_max_width': 15,
            'subtitle_color': (0, 0, 0),
            'line_spacing': 15,
            'output_dir': 'output',
            'padding': 50,
            'line_width': 8,
            'subtitle_offset': 40,  
            'line_position_offset': 190 
        }
        # 创建基础输出目录
        os.makedirs(self.config['output_dir'], exist_ok=True)
        # 如果有主题，创建主题目录
        if self.topic:
            self.theme_dir = os.path.join(self.config['output_dir'], self.topic)
            os.makedirs(self.theme_dir, exist_ok=True)

    def _get_font(self, size):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        font_names = ['SimHei', 'WenQuanYi Micro Hei', 'Heiti TC', 'Microsoft YaHei']
        # 首先尝试加载本地字体文件
        local_font = os.path.join(script_dir, 'asset', '字小魂扶摇手书(商用需授权).ttf')
        try:
            return ImageFont.truetype(local_font, size)
        except Exception as e:
            print(f"本地字体加载失败: {local_font}, 错误: {str(e)}")
        # 尝试使用matplotlib查找系统中的中文字体
        for font_name in font_names:
            try:
                font_path = fm.findfont(fm.FontProperties(family=font_name))
                return ImageFont.truetype(font_path, size)
            except Exception as e:
                print(f"无法找到字体: {font_name}, 错误: {str(e)}")
                continue

        print("所有字体加载失败，使用默认字体")
        return ImageFont.load_default()

    def generate(self, title_text, **kwargs):
        config = {**self.config, **kwargs}
        image = Image.new('RGB', (self.width, self.height), kwargs.get('bg_color', self.background_color))
        draw = ImageDraw.Draw(image)

        title_font = self._get_font(config['title_font_size'])
        subtitle_font = self._get_font(config['subtitle_font_size'])

        title_lines = textwrap.wrap(title_text, width=config['title_max_width'])
        y_position = config['padding']
        for line in title_lines:
            bbox = draw.textbbox((0, 0), line, font=title_font)
            draw.text(
                (config['padding'], y_position),
                line,
                font=title_font,
                fill=kwargs.get('title_color', self.title_color)
            )
            y_position += (bbox[3] - bbox[1]) + config['line_spacing']

        if config.get('subtitle_lines'):
            y_position = config['padding']
            for i, line in enumerate(config['subtitle_lines']):
                bbox = draw.textbbox((0, 0), line, font=subtitle_font)
                x_offset = self.width - bbox[2] - (config['padding'] + 30) + (i * config['subtitle_offset'])
                draw.text(
                    (x_offset, y_position),
                    line,
                    font=subtitle_font,
                    fill=config['subtitle_color']
                )
                y_position += bbox[3] - bbox[1] + 5 

        line_y = self.height - config['padding'] - config['line_position_offset']
        draw.line([
            (0, line_y),
            (self.width, line_y)
        ], fill=(0, 0, 0), width=config['line_width'])

        # 生成输出路径
        if self.topic:
            output_dir = os.path.join(config['output_dir'], self.topic)
            os.makedirs(output_dir, exist_ok=True)
        else:
            output_dir = config['output_dir']
        
        output_path = os.path.join(
            output_dir,
            f'title_{uuid.uuid4()}.png'
        )
        image.save(output_path)
        return output_path
