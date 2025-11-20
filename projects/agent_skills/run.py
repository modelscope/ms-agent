# flake8: noqa
# yapf: disable
# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from pathlib import Path

from ms_agent.agent import create_agent_skill

_PATH = Path(__file__).parent.resolve()


def main():
    """
    Main function to create and run an agent with skills.
    """
    work_dir: str = str(_PATH / 'temp_workspace')
    # Refer to `https://github.com/modelscope/ms-agent/tree/main/projects/agent_skills/skills`
    skills_dir: str = str(_PATH / 'skills')
    example_data_dir: str = str(_PATH / 'example_data')
    use_sandbox: bool = True

    ## Configuration for ModelScope API-Inference, or set your own model with OpenAI API compatible format
    ## Free LLM API inference calls for ModelScope users, refer to [ModelScope API-Inference](https://modelscope.cn/docs/model-service/API-Inference/intro)
    model: str = 'Qwen/Qwen3-235B-A22B-Instruct-2507'
    api_key: str = 'xx-xx'  # For ModelScope users, refer to `https://modelscope.cn/my/myaccesstoken` to get your access token
    base_url: str = 'https://api-inference.modelscope.cn/v1/'

    agent = create_agent_skill(
        skills=skills_dir,
        model=model,
        api_key=os.getenv('OPENAI_API_KEY', api_key),
        base_url=os.getenv('OPENAI_BASE_URL', base_url),
        stream=True,
        # Note: Make sure the `Docker Daemon` is running if use_sandbox=True
        use_sandbox=use_sandbox,
        work_dir=work_dir,
    )

    # Copy the example data files to the working directory for sandbox access
    import shutil
    os.makedirs(work_dir, exist_ok=True)
    shutil.copytree(example_data_dir, work_dir, dirs_exist_ok=True)

    queries = [
        # f'Extract the form field info from pdf: OLYMPIC_MEDAL_TABLE_zh.pdf, generate result file as OLYMPIC_MEDAL_TABLE_zh_fields.json',
        'Create generative art using p5.js with seeded randomness, flow fields, and particle systems, please fill in the details and provide the complete code based on the templates.'
    ]

    for query in queries:
        print(f'** User query:\n{query}\n\n')
        response = agent.run(query)
        print(f'\n\n** Agent skill results: {response}\n')


if __name__ == '__main__':

    main()
