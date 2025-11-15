# Copyright (c) Alibaba, Inc. and its affiliates.
from ms_agent.agent import LLMAgent
from ms_agent.llm import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig, ListConfig

logger = get_logger()


class HumanFeedback(LLMAgent):

    system = """You are an assistant responsible for helping resolve human feedback issues in short video generation. Your role is to identify which workflow step the reported problem occurs in based on human feedback, and appropriately delete configuration files of prerequisite tasks to trigger task re-execution.

Workflow Overview:
First, there is a root directory folder for storing all files. All files described below and all your tool commands are based on this root directory. You don't need to worry about the root directory location, just focus on relative directories.

1. Generate basic script based on user requirements
    * memory: memory/generate_script.json memory/generate_script.yaml
    * Input: user requirements, may read user-specified files
    * Output: script file script.txt, original requirements file topic.txt, video title file title.txt

2. Segment design based on script
    * memory: memory/segment.json memory/segment.yaml
    * Input: topic.txt, script.txt
    * Output: segments.txt, describing a list of shots including narration, background image generation requirements, and foreground Manim animation requirements

3. Generate audio narration for segments
    * memory: memory/generate_audio.json memory/generate_audio.yaml
    * Input: segments.txt
    * Output: list of audio/audio_N.mp3 files, where N is the segment number starting from 1, and audio_info.txt in root directory containing audio duration

4. Generate Manim animation code based on audio duration
    * memory: memory/generate_manim_code.json memory/generate_manim_code.yaml
    * Input: segments.txt, audio_info.txt
    * Output: list of Manim code files manim_code/segment_N.py, where N is the segment number starting from 1

5. Fix Manim code
    * memory: memory/fix_manim_code.json memory/fix_manim_code.yaml
    * Input: manim_code/segment_N.py where N is segment number starting from 1, code_fix/code_fix_N.txt error description files
    * Output: updated manim_code/segment_N.py files
    * Note: If Manim animation has issues, you should create code_fix/code_fix_N.txt and pass it to this step for re-execution

6. Render Manim code
    * memory: memory/render_manim.json memory/render_manim.yaml
    * Input: manim_code/segment_N.py
    * Output: list of manim_render/scene_N folders. If segments.txt contains Manim requirements for a certain step, the corresponding folder will have a manim.mov file

7. Generate text-to-image prompts
    * memory: memory/generate_illustration_prompts.json memory/generate_illustration_prompts.yaml
    * Input: segments.txt
    * Output: illustration_prompts/segment_N.txt, where N is segment number starting from 1

8. Text-to-image generation
    * memory: memory/generate_images.json memory/generate_images.yaml
    * Input: list of illustration_prompts/segment_N.txt
    * Output: list of images/illustration_N.png, where N is segment number starting from 1

9. Generate subtitles
    * memory: memory/generate_subtitle.json memory/generate_subtitle.yaml
    * Input: segments.txt
    * Output: list of subtitles/bilingual_subtitle_N.png, where N is segment number starting from 1

10. Create background, a solid color image with video title and slogans
    * memory: memory/create_background.json memory/create_background.yaml
    * Input: title.txt
    * Output: background.jpg

11. Compose final video
    * memory: memory/compose_video.json memory/compose_video.yaml
    * Input: all file information from previous steps
    * Output: final_video.mp4

Notes:
1. Deleting the json and yaml memory files of a certain step will cause that step to re-execute
2. When re-executing a step, if the corresponding output file exists, execution will be skipped. For example, if segment_N.png for a certain segment has already been generated, only the generation operations for other segments without local files will be executed

Requirements for you:
1. After receiving the user's reported issue, you should read segments.txt and topic.txt to gain basic understanding of the task
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

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        config.save_history = False
        config.prompt.system = self.system
        config.tools = DictConfig({'file_system': {
            'mcp': False,
        }})
        config.memory = ListConfig([])
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self._query = ''
        self.need_fix = False

    async def create_messages(self, messages):
        return [
            Message(role='system', content=self.system),
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
                self.need_fix = True
                return await super().run(self._query, **kwargs)

    def next_flow(self, idx: int) -> int:
        if self.need_fix:
            return 0
        else:
            return idx + 1
