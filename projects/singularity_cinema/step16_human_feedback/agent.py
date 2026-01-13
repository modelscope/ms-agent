# Copyright (c) Alibaba, Inc. and its affiliates.
import os

import json
from ms_agent.agent import LLMAgent
from ms_agent.llm import Message
from ms_agent.tools import SplitTask
from ms_agent.utils import get_logger
from omegaconf import DictConfig, ListConfig

logger = get_logger()

workflow = """Workflow Overview:
First, there is a root directory folder for storing all files. All files described below and all your tool commands are based on this root directory. You don't need to worry about the root directory location, just focus on relative directories.

1. Generate basic script based on user requirements, parse all images from files
    * memory: output_video/.memory/generate_script.json output_video/.memory/generate_script.yaml
    * Input: user requirements, may read user-specified files
    * Output: output_video/script.txt, output_video/topic.txt, output_video/title.txt, output_video/docs.txt

2. Parse and download all images from docs.txt
    * memory: output_video/.memory/parse_images.json output_video/.memory/parse_images.yaml
    * Input: output_video/docs.txt
    * Output: output_video/image_info.txt

3. Segment design based on script
    * memory: output_video/.memory/segment.json output_video/.memory/segment.yaml
    * Input: output_video/topic.txt, output_video/script.txt
    * Output: output_video/segments.txt

4. Generate audio narration for segments
    * memory: output_video/.memory/generate_audio.json output_video/.memory/generate_audio.yaml
    * Input: output_video/segments.txt
    * Output: output_video/audio/audio_N.mp3, output_video/audio_info.txt

5. Visual Director - Scene Planning
    * memory: output_video/.memory/visual_director.json
    * Input: output_video/segments.txt, output_video/audio_info.txt
    * Output: output_video/visual_plans/plan_N.json

6. Generate text-to-image prompts
    * memory: output_video/.memory/generate_illustration_prompts.json output_video/.memory/generate_illustration_prompts.yaml
    * Input: output_video/segments.txt
    * Output: output_video/illustration_prompts/segment_N.txt, output_video/illustration_prompts/segment_N_foreground_M.txt

7. Text-to-image generation
    * memory: output_video/.memory/generate_images.json output_video/.memory/generate_images.yaml
    * Input: output_video/illustration_prompts/segment_N.txt
    * Output: output_video/images/illustration_N.png, output_video/images/illustration_N_foreground_M.png

8. Generate Animation code based on audio duration (Manim or Remotion)
    * memory: output_video/.memory/generate_animation.json
    * Input: output_video/segments.txt, output_video/audio_info.txt, output_video/image_info.txt, output_video/visual_plans/plan_N.json
    * Output: output_video/manim_code/segment_N.py or output_video/remotion_code/segment_N.tsx

9. Fix Animation code
    * memory: output_video/.memory/fix_animation.json
    * Input: Animation code files
    * Output: Fixed code files

10. Render Animation
    * memory: output_video/.memory/render_animation.json
    * Input: code files
    * Output: output_video/manim_render/ or output_video/remotion_render/

11. Generate Video Prompts (for Runaway/Sora etc)
    * memory: output_video/.memory/generate_video_prompts.json

8. Fix Animation code
    * memory: output_video/.memory/fix_animation.json
    * Input: code file, error logs
    * Output: updated code file

9. Render Animation
    * memory: output_video/.memory/render_animation.json
    * Input: code file
    * Output: output_video/manim_render/ or output_video/remotion_render/ folders

10. Generate text-2-video prompts
    * memory: output_video/.memory/generate_video_prompts.json output_video/.memory/generate_video_prompts.yaml
    * Input: output_video/segments.txt
    * Output: output_video/video_prompts/segment_N.txt

11. Generate text-2-video
    * memory: output_video/.memory/generate_video.json output_video/.memory/generate_video.yaml
    * Input: output_video/segments.txt, output_video/video_prompts/segment_N.txt
    * Output: output_video/videos/video_N.txt

12. Generate subtitles
    * memory: output_video/.memory/generate_subtitle.json output_video/.memory/generate_subtitle.yaml
    * Input: output_video/segments.txt
    * Output: output_video/subtitles/bilingual_subtitle_N.png

13. Create background
    * memory: output_video/.memory/create_background.json output_video/.memory/create_background.yaml
    * Input: output_video/title.txt
    * Output: output_video/background.jpg

14. Compose final video
    * memory: output_video/.memory/compose_video.json output_video/.memory/compose_video.yaml
    * Input: all file information from previous steps
    * Output: output_video/final_video.mp4
""" # noqa


class HumanFeedback(LLMAgent):



    system = f"""You are an assistant responsible for helping resolve human feedback issues in short video generation. Your role is to identify which workflow step the reported problem occurs in based on human feedback, and appropriately delete configuration files of prerequisite tasks to trigger task re-execution.

CRITICAL: You are a manager, not a worker. DO NOT try to generate audio, images, or video files yourself using file_system tools. Your ONLY method of fixing issues is to DELETE the corresponding memory files (json/yaml) and local asset files so the workflow can regenerate them automatically.

{workflow}

Notes:
1. Deleting the json and yaml memory files of a certain step will cause that step to re-execute
2. When re-executing a step, if the corresponding output file exists, execution will be skipped. For example, if segment_N.png for a certain segment has already been generated, only the generation operations for other segments without local files will be executed

Requirements for you:
1. After receiving the user's reported issue, you should read segments.txt and topic.txt to gain basic understanding of the task, understand the image/manim/video settings in each segment
2. Analyze which segment numbers and which steps the user-described problem occurs in
    * [Very Important] After reading segments.txt, you need to read the corresponding files based on the approximate steps where the issue occurred, such as manim code (manim_code/segment_N.py), image prompts, etc., to ensure you have a 100% understanding of the user's feedback. You don't need to fix the code yourself. When providing feedback to previous steps, you should be as specific as possible to prevent ineffective fixes from occurring.
3. If there's a Manim animation issue, you can construct code_fix/code_fix_N.txt, where N starts from 1
4. After determining the segment numbers and steps, you should **delete the corresponding local files for those segment numbers, as well as all memory files** for the corresponding step and subsequent steps**
    * If bugs are severe and Manim animation needs to be regenerated, you need to delete the corresponding segments in the `manim_code` folder and delete step 4's memory
    * If animation errors can be fixed based on existing code, **don't delete the manim_code folder files**, start re-execution from step 5, and delete the corresponding segment subfolders in the manim_render folder
5. The workflow will automatically re-execute to generate missing files
6. If you find the reported problem stems from segment design issues, such as difficult-to-fix Manim animation bugs, or consider deleting code files for regeneration (rather than fixing):
    * You need to consider fixing the problem with minimal changes to prevent major perceptual changes to the video
    * Try not to update segments (segments.txt), otherwise the entire video will be completely redone""" # noqa

    spliter_system = f"""You are an assistant responsible for helping resolve human feedback issues in short video generation, your responsibility is to distinguish which storyboard segment these issues originate from, and return to me the list of problems and detailed descriptions that need to be addressed for the corresponding segment.

{workflow}

* Read segments.txt and topic.txt and the any file user ask you to read, no need to read other files.

return format:

```json
[
    {{
        "id": 1, # segment id
        "issue": "The issue you dispatched"
    }},
    ...
]
```
""" # noqa

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        config.save_history = False

        # Fix memory path in system prompt
        output_dir = getattr(config, 'output_dir', 'output')
        fixed_system = self.system.replace('memory/', f'{output_dir}/.memory/')
        config.prompt.system = fixed_system

        config.tools = DictConfig({
            'file_system': {
                'mcp': False,
                'allow_read_all_files': True,
                'exclude': ['list_files']
            }
        })
        config.memory = DictConfig({})
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = output_dir
        self.split_task = SplitTask(config)
        self._query = ''
        self.need_fix = False

    async def create_messages(self, messages):
        return [
            Message(role='system', content=self.spliter_system),
            Message(role='user', content=self._query),
        ]

    async def run(self, inputs, **kwargs):
        blue_color_prefix = '\033[34m'
        blue_color_suffix = '\033[0m'
        print(
            f'{blue_color_prefix}请查看输出文件夹中的final_video.mp4,并给出你的修改意见。请注意:\n'
            '    * 重新生成素材合成video需要一定时间，建议将问题总结起来一并反馈\n'
            '    * 请具体描述问题现象,并尽量描述清楚发生在哪个分镜中,例如在展示...信息时动画向...越界了...重叠了\n'
            f'    * 可以给出对整体视频的评价,例如建议模型重新生成动画,或者对现有动画比较满意直接修改\n{blue_color_suffix}'
        )
        print(
            f'{blue_color_prefix}Please review final_video.mp4 in the output folder and provide your feedback. '
            f'Please note:\n'
            '    * Regenerating assets and composing the video takes time, so it is recommended '
            'to summarize all issues and provide feedback together\n'
            '    * Please describe the problem specifically and try to clearly indicate which segment it occurs in, '
            'for example: when displaying ... information, the animation went out of bounds ... overlapped ...\n'
            '    * You can provide an overall evaluation of the video, such as suggesting the model regenerate '
            f'the animation, or if you are satisfied with the existing animation, '
            f'just make direct modifications\n{blue_color_suffix}')
        while True:
            self._query = input('>>>')
            if self._query.strip() in ('exit', 'quit'):
                self.need_fix = False
                return inputs
            elif not self._query.strip():
                continue
            else:
                # Process feedback with LLM first; only mark for fix if parsed successfully
                self.need_fix = False
                messages = await super().run(self._query, **kwargs)
                response = messages[-1].content
                if '```json' in response:
                    json_str = response.split('```json')[1].split('```')[0]
                elif '```' in response:
                    json_str = response.split('```')[1].split('```')[0]
                else:
                    json_str = response

                try:
                    segments = json.loads(json_str)
                    inputs = []
                    for segment in segments:
                        inputs.append({
                            'system':
                            self.system,
                            'query':
                            f'All issues happens in segment {segment["id"]}: {segment["issue"]}\n'
                        })

                    # Run split tasks to apply file/memory deletions
                    await self.split_task.call_tool(
                        '',
                        tool_name='',
                        tool_args={
                            'tasks': inputs,
                            'execution_mode': 'parallel'
                        })

                    # Mark fix needed and safely remove final video to trigger recomposition
                    self.need_fix = True
                    final_video_path = os.path.join(self.work_dir,
                                                    'final_video.mp4')
                    if os.path.exists(final_video_path):
                        os.remove(final_video_path)
                    return messages
                except json.JSONDecodeError:
                    # If parsing fails, show assistant content and keep existing video untouched
                    print(f'\n[Assistant]: {response}\n')
                    continue

    def next_flow(self, idx: int) -> int:
        if self.need_fix:
            return 0
        else:
            return idx + 1
