from omegaconf import DictConfig
from ms_agent.agent.llm_agent import LLMAgent

config: DictConfig = DictConfig(
        {
            'llm': {
                'service': 'openai',
                'model': 'qwen3-max',
                'openai_api_key': 'your-api-key',
                'openai_base_url': 'your-base-url'
            },
            'skills': {
                'path': 'examples/skills/claude_skills',
                'work_dir': '/path/to/workspace',
                'auto_execute': True,
            }
        }
    )


async def main():
    """
    Run an LLMAgent with specified skills to generate mock data.
    """
    agent = LLMAgent(config=config)

    results = await agent.run(
        messages="Generate a mock report of Apple's quarterly earnings, output pdf file.",
    )

    for res_msg in results:
        role = res_msg.role
        if role == 'assistant':
            print(f'Final content: {res_msg.content}')


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
