import os
from typing import List

import json
from ms_agent import LLMAgent
from ms_agent.llm import Message


class FileOrderAgent(LLMAgent):

    async def run(self, messages, **kwargs):
        with open(os.path.join(self.output_dir, 'topic.txt'), 'r') as f:
            topic = f.read()

        with open(os.path.join(self.output_dir, 'framework.txt'), 'r') as f:
            framework = f.read()

        with open(os.path.join(self.output_dir, 'file_design.txt'), 'r') as f:
            file_design = f.read()

        query = f'Topic: {topic}\nFramework: {framework}\nFile Design: {file_design}\nPlease give your file order.'

        messages = [
            Message(role='system', content=self.config.prompt.system),
            Message(role='user', content=query),
        ]
        return await super().run(messages, **kwargs)

    async def after_tool_call(self, messages: List[Message]):
        await super().after_tool_call(messages)

        if self.runtime.should_stop:
            query = None

            if os.path.isfile(os.path.join(self.output_dir, 'file_order.txt')):
                with open(
                        os.path.join(self.output_dir, 'file_order.txt'),
                        'r') as f:
                    file_order = json.load(f)

                with open(
                        os.path.join(self.output_dir, 'file_design.txt'),
                        'r') as f:
                    file_design = json.load(f)

                files1 = set()
                files2 = set()
                for file in file_order:
                    files1.update(file['files'])

                for file in file_design:
                    names = [f['name'] for f in file['files']]
                    files2.update(names)

                if len(files1) < len(files2):
                    query = (
                        f'The file order you provided misses some files: {files2 - files1}, '
                        f'please provide the complete file order including these files.'
                    )
                elif len(files1) > len(files2):
                    query = (
                        f'The file order you provided has some extra files: {files1 - files2}, '
                        f'please provide the correct file order without these files.'
                    )
            else:
                query = ('The file order you provided is missing, '
                         'please provide the complete file order.')

            if query:
                messages.append(Message(role='user', content=query))
                self.runtime.should_stop = False

    async def on_task_end(self, messages: List[Message]):
        assert os.path.isfile(os.path.join(self.output_dir, 'file_order.txt'))
        with open(os.path.join(self.output_dir, 'file_order.txt'), 'r') as f:
            file_order = json.load(f)

        with open(os.path.join(self.output_dir, 'file_design.txt'), 'r') as f:
            file_design = json.load(f)

        files1 = set()
        files2 = set()
        for file in file_order:
            files1.update(file['files'])

        for file in file_design:
            names = [f['name'] for f in file['files']]
            files2.update(names)

        assert len(files1) == len(files2)
        assert not (files1 - files2)
