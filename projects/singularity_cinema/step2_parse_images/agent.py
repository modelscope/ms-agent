# Copyright (c) Alibaba, Inc. and its affiliates.
import base64
import hashlib
import os
import re
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from urllib.request import urlretrieve

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.llm.openai_llm import OpenAI
from ms_agent.utils import get_logger
from omegaconf import DictConfig
from PIL import Image

logger = get_logger()


class ParseImages(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        _config = deepcopy(config)
        delattr(_config, 'llm')
        _config.llm = DictConfig({})
        for key, value in _config.mllm.items():
            key = key[len('mllm_'):]
            setattr(_config.llm, key, value)
        _config.generation_config = DictConfig({'temperature': 0.3})
        self.mllm: OpenAI = LLM.from_config(_config)
        self.image_dir = os.path.join(self.work_dir, 'images')
        os.makedirs(self.image_dir, exist_ok=True)

    async def execute_code(self, messages, **kwargs):
        if not self.config.use_doc_image:
            return messages
        logger.info('Parsing images.')
        docs_file = os.path.join(self.work_dir, 'docs.txt')
        if not os.path.exists(docs_file):
            return messages
        with open(docs_file, 'r') as f:
            docs = f.readlines()

        if not docs:
            return messages

        docs = [doc.strip() for doc in docs if doc.strip()]
        image_files = []
        for doc in docs:
            image_files.extend(self.parse_images(doc))

        def process_image(image_file):
            size = self.get_image_size(image_file)
            description = self.get_image_description(image_file)
            return image_file, size, description

        with ThreadPoolExecutor(max_workers=4) as executor:
            output = list(executor.map(process_image, image_files))

        filename = os.path.join(self.work_dir, 'image_info.txt')
        with open(filename, 'w') as f:
            for img_tuple in output:
                image_json = {
                    'filename': img_tuple[0],
                    'size': img_tuple[1],
                    'description': img_tuple[2],
                }
                f.write(json.dumps(image_json, ensure_ascii=False) + '\n')
        return messages

    def parse_images(self, filename):
        if not os.path.isfile(filename):
            return []
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()

        image_pattern = r'!\[.*?\]\((.*?)\)'
        urls = re.findall(image_pattern, content)

        image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'}

        local_paths = []
        for url in urls:
            ext = os.path.splitext(url.split('?')[0])[1].lower()
            if ext not in image_exts:
                continue

            if url.startswith(('http://', 'https://')):
                url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                local_file = os.path.join(self.image_dir, f'{url_hash}{ext}')
                if not os.path.exists(local_file):
                    urlretrieve(url, local_file)
                local_paths.append(local_file)
            else:
                if os.path.isfile(url):
                    local_paths.append(url)
                else:
                    path = os.path.dirname(filename)
                    url = os.path.join(path, url)
                    if os.path.isfile(url):
                        local_paths.append(url)

        return local_paths

    @staticmethod
    def get_image_size(filename):
        with Image.open(filename) as img:
            return f'{img.width}x{img.height}'

    def get_image_description(self, filename):
        with open(filename, 'rb') as image_file:
            image_data = image_file.read()
            base64_image = base64.b64encode(image_data).decode('utf-8')

        _content = [{
            'type':
            'text',
            'text':
            ('Describe this image in under 50 words. Be objective and accurate. For charts/graphs, '
             'analyze axis labels and data to explain what the chart shows and its purpose, '
             'not just the chart type. Provide enough detail to distinguish it from other images.'
             'Return only the requested image description. Do not add any other content.'
             )
        }, {
            'type': 'image_url',
            'image_url': {
                'url': f'data:image/png;base64,{base64_image}',
                'detail': 'high'
            }
        }]

        messages = [
            Message(role='user', content=_content),
        ]
        response = self.mllm.generate(messages)
        return response.content
