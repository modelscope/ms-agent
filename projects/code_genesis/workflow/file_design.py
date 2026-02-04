import os
from typing import List

import json
from ms_agent import LLMAgent
from ms_agent.llm import Message


class FileDesignAgent(LLMAgent):

    async def run(self, messages, **kwargs):
        with open(os.path.join(self.output_dir, 'topic.txt'), 'r') as f:
            topic = f.read()

        with open(os.path.join(self.output_dir, 'framework.txt'), 'r') as f:
            framework = f.read()

        with open(os.path.join(self.output_dir, 'modules.txt'), 'r') as f:
            modules = f.read()

        query = f'Topic: {topic}\nFramework: {framework}\nModules: {modules}\nPlease give your design.'

        messages = [
            Message(role='system', content=self.config.prompt.system),
            Message(role='user', content=query),
        ]
        return await super().run(messages, **kwargs)

    async def after_tool_call(self, messages: List[Message]):
        await super().after_tool_call(messages)

        if self.runtime.should_stop:
            query = None

            if os.path.isfile(
                    os.path.join(self.output_dir, 'file_design.txt')):
                with open(
                        os.path.join(self.output_dir, 'file_design.txt'),
                        'r') as f:
                    file_design = json.load(f)

                with open(os.path.join(self.output_dir, 'modules.txt'),
                          'r') as f:
                    modules = f.readlines()

                files1 = set()
                files2 = set()
                for file in file_design:
                    name = file['module']
                    files1.add(name)

                for module in modules:
                    files2.add(module.strip())

                if len(files1) < len(files2):
                    query = (
                        f'The file design you provided misses some modules: {files2 - files1}, '
                        f'please provide the complete file order including these files.'
                    )
                elif len(files1) > len(files2):
                    query = (
                        f'The file design you provided has some extra modules: {files1 - files2}, '
                        f'please provide the correct file order without these files.'
                    )
            else:
                query = ('The file design you provided is missing, '
                         'please provide the complete file design.')

            if query:
                messages.append(Message(role='user', content=query))
                self.runtime.should_stop = False

    async def on_task_end(self, messages: List[Message]):
        assert os.path.isfile(os.path.join(self.output_dir, 'file_design.txt'))
        with open(os.path.join(self.output_dir, 'file_design.txt'), 'r') as f:
            file_design = json.load(f)

        with open(os.path.join(self.output_dir, 'modules.txt'), 'r') as f:
            modules = f.readlines()

        assert len(modules) == len(file_design)

        _modules = [content['module'] for content in file_design]
        modules = [module.strip() for module in _modules if module.strip()]
        assert not (set(modules) - set(_modules))
