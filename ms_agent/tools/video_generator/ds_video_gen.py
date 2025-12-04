import asyncio
import os
import uuid

import aiohttp
from ms_agent.utils import get_logger

logger = get_logger()


class DSVideoGenerator:

    def __init__(self, config, temp_dir):
        self.config = config
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)

    async def generate_video(self,
                             positive_prompt,
                             size='1280x720',
                             seconds=4):
        video_generator = self.config.tools.video_generator
        base_url = (getattr(video_generator, 'base_url', None)
                    or 'https://dashscope.aliyuncs.com').strip('/')
        api_key = video_generator.api_key
        model_id = video_generator.model
        assert api_key is not None
        task_id = str(uuid.uuid4())[:8]
        output_file = os.path.join(self.temp_dir, f'{task_id}.mp4')
        video_url = await self._generate_video(base_url, api_key, model_id,
                                               positive_prompt, size, seconds)
        await self.download_video(video_url, output_file)
        return output_file

    @staticmethod
    async def download_video(video_url, output_file):
        max_retries = 3
        retry_count = 0

        async with aiohttp.ClientSession() as session:
            headers = {}
            while retry_count < max_retries:
                try:
                    async with session.get(
                            video_url, headers=headers) as video_resp:
                        video_resp.raise_for_status()
                        video_content = await video_resp.read()
                        with open(output_file, 'wb') as f:
                            f.write(video_content)
                        break
                except Exception as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        raise e
                    else:
                        await asyncio.sleep(2**retry_count)

    @staticmethod
    async def _generate_video(base_url, api_key, model, prompt, size, seconds):
        base_url = base_url.strip('/')
        create_endpoint = '/api/v1/services/aigc/model-evaluation/async-inference/'

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'X-DashScope-Async': 'enable',
        }
        payload = {
            'model': model,
            'input': {
                'prompt': prompt,
                'size': size,
                'seconds': seconds,
            },
            'parameters': {}
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    f'{base_url}{create_endpoint}', headers=headers,
                    json=payload) as resp:
                resp.raise_for_status()
                response_data = await resp.json()

                task_id = response_data['output']['task_id']
                if not task_id:
                    raise RuntimeError(
                        f'No task ID in response: {response_data}')

                return await DSVideoGenerator._poll_video_task(
                    session, base_url, task_id, headers)

    @staticmethod
    async def _poll_video_task(session, base_url, task_id, headers):
        max_wait_time = 1800  # 30 minutes
        poll_interval = 5
        max_poll_interval = 30
        elapsed_time = 0

        poll_endpoint = f'/api/v1/tasks/{task_id}'
        success_statuses = ['SUCCEEDED', 'SUCCEED']
        failed_statuses = ['FAILED', 'failed']

        while elapsed_time < max_wait_time:
            await asyncio.sleep(poll_interval)
            elapsed_time += poll_interval

            async with session.get(
                    f'{base_url}{poll_endpoint}', headers=headers) as result:
                result.raise_for_status()
                data = await result.json()
                status = data['output']['task_status']
                logger.info(
                    f'Task {task_id} status: {status}, defailed message: {str(data)}'
                )

                if status in success_statuses:
                    video_url = data['output']['video_url']
                    if not video_url:
                        raise RuntimeError(
                            f'Video URL not found in response: {data}')
                    return video_url
                elif status in failed_statuses:
                    error_msg = data['output'].get(
                        'message') or 'Unknown error'
                    raise RuntimeError(f'Video generation failed: {error_msg}')

            poll_interval = min(poll_interval * 1.2, max_poll_interval)

        raise TimeoutError(
            f'Video generation task {task_id} timed out after {max_wait_time} seconds'
        )
