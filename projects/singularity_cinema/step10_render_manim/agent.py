# Copyright (c) Alibaba, Inc. and its affiliates.
import base64
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from os import getcwd
from typing import List, Union

import json
from moviepy import VideoFileClip
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig
from PIL import Image

logger = get_logger()


class RenderManim(CodeAgent):

    window_size = (1250, 700)

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        if not self.config.use_subtitle:
            self.window_size = (1450, 800)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.num_parallel = getattr(self.config, 'llm_num_parallel', 10)
        self.manim_render_timeout = getattr(
            self.config, 'animation_render_timeout',
            getattr(self.config, 'manim_render_timeout', 300))
        self.render_dir = os.path.join(self.work_dir, 'manim_render')
        self.code_fix_round = getattr(self.config, 'code_fix_round', 5)
        self.mllm_check_round = getattr(self.config, 'mllm_fix_round', 1)
        os.makedirs(self.render_dir, exist_ok=True)

    async def execute_code(self, messages: Union[str, List[Message]],
                           **kwargs) -> List[Message]:
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)
        manim_code_dir = os.path.join(self.work_dir, 'manim_code')
        manim_code = []
        for i in range(len(segments)):
            with open(os.path.join(manim_code_dir, f'segment_{i+1}.py'),
                      'r') as f:
                manim_code.append(f.read())
        with open(os.path.join(self.work_dir, 'audio_info.txt'), 'r') as f:
            audio_infos = json.load(f)
        assert len(manim_code) == len(segments)
        logger.info('Rendering manim code.')

        tasks = [
            (i, segment, code, audio_info['audio_duration'])
            for i, (segment, code, audio_info
                    ) in enumerate(zip(segments, manim_code, audio_infos))
        ]

        with ThreadPoolExecutor(max_workers=self.num_parallel) as executor:
            futures = {
                executor.submit(self._render_manim_scene_static, i, segment,
                                code, duration, self.config, self.work_dir,
                                self.render_dir, self.window_size,
                                self.manim_render_timeout, self.code_fix_round,
                                self.mllm_check_round): i
                for i, segment, code, duration in tasks
            }
            for future in as_completed(futures):
                future.result()  # Wait for completion and raise any exceptions

        return messages

    @staticmethod
    def _render_manim_scene_static(i, segment, code, audio_duration, config,
                                   work_dir, render_dir, window_size,
                                   manim_render_timeout, code_fix_round,
                                   mllm_check_round):
        """Static method for multiprocessing"""
        llm = LLM.from_config(config)
        return RenderManim._render_manim_impl(llm, i, segment, code,
                                              audio_duration, work_dir,
                                              render_dir, window_size,
                                              manim_render_timeout, config,
                                              code_fix_round, mllm_check_round)

    @staticmethod
    def _render_manim_impl(llm, i, segment, code, audio_duration, work_dir,
                           render_dir, window_size, manim_render_timeout,
                           config, code_fix_round, mllm_check_round):
        scene_name = f'Scene{i+1}'  # sometimes actual_scene_name cannot find matched class, so do not change this name
        logger.info(f'Rendering manim code for: scene_{i + 1}')
        output_dir = os.path.join(render_dir, f'scene_{i + 1}')
        os.makedirs(output_dir, exist_ok=True)
        if 'manim' not in segment:
            return None
        code_file = os.path.join(output_dir, f'{scene_name}.py')
        class_match = re.search(r'class\s+(\w+)\s*\(Scene\)', code)
        actual_scene_name = class_match.group(1) if class_match else scene_name
        output_path = os.path.join(output_dir, f'{scene_name}.mov')
        manim_requirement = segment.get('manim')
        class_name = f'Scene{i + 1}'
        content = segment['content']
        final_file_path = None
        if os.path.exists(output_path):
            return output_path
        logger.info(f'Rendering scene {actual_scene_name}')
        fix_history = ''
        mllm_max_check_round = mllm_check_round
        cur_check_round = 0
        for retry_idx in range(code_fix_round):
            with open(code_file, 'w') as f:
                f.write(code)

            env = os.environ.copy()
            env['PYTHONWARNINGS'] = 'ignore'
            env['MANIM_DISABLE_OPENCACHING'] = '1'
            env['PYTHONIOENCODING'] = 'utf-8'
            env['LANG'] = 'zh_CN.UTF-8'
            env['LC_ALL'] = 'zh_CN.UTF-8'
            window_size_str = ','.join([str(x) for x in window_size])
            cmd = [
                'manim', 'render', '-ql', '--transparent', '--format=mov',
                f'--resolution={window_size_str}', '--disable_caching',
                f'--media_dir={os.path.dirname(code_file)}', code_file,
                actual_scene_name
            ]

            try:
                process = subprocess.Popen(
                    cmd,
                    cwd=getcwd(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    env=env)

                # Wait for process to complete with timeout
                stdout, stderr = process.communicate(
                    timeout=manim_render_timeout)

                # Create result object compatible with original logic
                class Result:

                    def __init__(self, returncode, stdout, stderr):
                        self.returncode = returncode
                        self.stdout = stdout
                        self.stderr = stderr

                result = Result(process.returncode, stdout, stderr)
                output_text = (result.stdout or '') + (result.stderr or '')
            except subprocess.TimeoutExpired as e:
                output_text = (e.stdout.decode('utf-8', errors='ignore')
                               if e.stdout else '') + (
                                   e.stderr.decode('utf-8', errors='ignore')
                                   if e.stderr else '')  # noqa
                logger.error(
                    f'Manim rendering timed out after {manim_render_timeout} '
                    f'seconds for {actual_scene_name}, output: {output_text}')
                logger.info('Trying to fix manim code.')
                code, fix_history = RenderManim._fix_manim_code_impl(
                    llm, output_text, fix_history, code, manim_requirement,
                    class_name, content, audio_duration, segment, i, work_dir)
                continue

            if result.returncode != 0:
                logger.warning(
                    f'Manim command exited with code {result.returncode}')
                logger.warning(f'Output: {output_text}')

                real_error_indicators = [
                    'SyntaxError', 'NameError', 'ImportError',
                    'AttributeError', 'TypeError', 'ValueError',
                    'ModuleNotFoundError', 'Traceback', 'Error:',
                    'Failed to render', 'unexpected keyword argument',
                    'got an unexpected', 'invalid syntax'
                ]

                if any([
                        error_indicator in output_text
                        for error_indicator in real_error_indicators
                ]):
                    logger.info('Trying to fix manim code.')
                    code, fix_history = RenderManim._fix_manim_code_impl(
                        llm, output_text, fix_history, code, manim_requirement,
                        class_name, content, audio_duration, segment, i,
                        work_dir)
                    continue

            for root, dirs, files in os.walk(output_dir):
                for file in files:
                    if file == f'{actual_scene_name}.mov':
                        found_file = os.path.join(root, file)
                        if not RenderManim.verify_and_fix_mov_file(found_file):
                            fixed_path = RenderManim.convert_mov_to_compatible(
                                found_file)
                            if fixed_path:
                                found_file = fixed_path

                        shutil.copy2(found_file, output_path)
                        scaled_path = RenderManim.scale_video_to_fit(
                            output_path, target_size=window_size)
                        if scaled_path and scaled_path != output_path:
                            shutil.rmtree(output_path, ignore_errors=True)
                            shutil.copy2(scaled_path, output_path)
                        final_file_path = output_path
            if not final_file_path:
                logger.error(
                    f'Manim file: {class_name} not found, trying to fix manim code.'
                )
                code, fix_history = RenderManim._fix_manim_code_impl(
                    llm, output_text, fix_history, code, manim_requirement,
                    class_name, content, audio_duration, segment, i, work_dir)
            else:
                if cur_check_round >= mllm_max_check_round:
                    break
                output_text = RenderManim.check_manim_quality(
                    final_file_path, work_dir, i, config, segment,
                    cur_check_round)
                cur_check_round += 1
                if output_text:
                    try:
                        os.remove(final_file_path)
                        final_file_path = None
                    except OSError:
                        pass
                    logger.info(
                        f'Trying to fix manim code of segment {i+1}, because model checking not passed: \n{output_text}'
                    )
                    code, fix_history = RenderManim._fix_manim_code_impl(
                        llm, output_text, fix_history, code, manim_requirement,
                        class_name, content, audio_duration, segment, i,
                        work_dir)
                    continue
                else:
                    break
        if final_file_path:
            RenderManim._extract_preview_frames_static(final_file_path, i,
                                                       work_dir, 'final')
            manim_code_dir = os.path.join(work_dir, 'manim_code')
            manim_file = os.path.join(manim_code_dir, f'segment_{i + 1}.py')
            with open(manim_file, 'w') as f:
                f.write(code)
        else:
            raise FileNotFoundError(final_file_path)

    @staticmethod
    def check_manim_quality(final_file_path, work_dir, i, config, segment,
                            cur_check_round):
        _mm_config = deepcopy(config)
        delattr(_mm_config, 'llm')
        _mm_config.llm = DictConfig({})
        _mm_config.generation_config = DictConfig({'temperature': 0.3})
        for key, value in _mm_config.mllm.items():
            key = key[len('mllm_'):]
            setattr(_mm_config.llm, key, value)

        test_system = """**Role Definition**
You are a Manim animation layout inspection expert, responsible for checking layout issues in animation frames.

**Background Information**
- The images you receive are video frames rendered by Manim (intermediate frames or final frames)
- Video dimensions: 1920*1080(16:9)

**Inspection Focus**

**Critical issues that must be reported:**
1. Component or text overlap
2. Components or text being cropped by edges (even slight cropping)
3. Pay extra attention to components at canvas edges, especially whether title components are being cut off
4. Parent-child component inconsistency (child elements exceeding parent container boundaries)
5. Chart element misalignment (pie chart center offset, incorrect bar chart/line chart positioning)
6. Text out of text-box
7. The chart has positioning errors in its axes, gridlines, line segments, etc

**Secondary issues that should be reported:**
1. Components with the same function not aligned
2. Connection line start/end point errors, incorrect arrow direction, lines overlapping with components

**Inspection Rules**
- Intermediate frames: Focus only on overlap and edge cropping issues, ignore incomplete components
- Final frames: Check all the above issues
- Ignore: Aesthetic issues, temporary unreasonable positions caused by animation processes
- If images exist in the frame but is not mentioned in the manim requirement, this behavior is correct, ignore them
- Focus only on image position, overlap, and cropping issues, ignoring whether the image content is relevant or correct with the manim requirement

**Output Format**

```
<description>
Detailed description of the image content, including the positions of all components and their distances from edges and other components
</description>

<result>
List discovered issues and fix suggestions. Leave empty if no issues found.
</result>
```

**Example:**
```
<description>
There are four square components in the image. The first component is approximately... from the left edge...
</description>

<result>
The right component is squeezed to the edge. Fix suggestion: Reduce the width of the four left components, move the right component further right...
</result>
```
"""# noqa

        test_images = RenderManim._extract_preview_frames_static(
            final_file_path, i, work_dir, cur_check_round)
        llm = LLM.from_config(_mm_config)
        logger.info(
            f"Using mllm model for manim quality check: {getattr(llm, 'model', None)}"
        )

        frame_names = [
            'the middle frame of the animation',
            'the last frame of the animation'
        ]
        content = segment['content']
        manim_requirement = segment['manim']

        all_issues = []
        for idx, (image_path,
                  frame_name) in enumerate(zip(test_images, frame_names)):
            with open(image_path, 'rb') as image_file:
                image_data = image_file.read()
                base64_image = base64.b64encode(image_data).decode('utf-8')

            _content = [{
                'type':
                'text',
                'text':
                (f'The checked frame is: {frame_name} of this animation\n'
                 f'The content of this animation: {content}\n'
                 f'The manim animation requirement: {manim_requirement}\n'
                 f'You must carefully check the animation layout issues.')
            }, {
                'type': 'image_url',
                'image_url': {
                    'url': f'data:image/png;base64,{base64_image}',
                    'detail': 'high'
                }
            }]

            messages = [
                Message(role='system', content=test_system),
                Message(role='user', content=_content),
            ]
            response = llm.generate(messages)
            response_text = response.content

            pattern = r'<result>(.*?)</result>'
            issues = []
            for issue in re.findall(pattern, response_text, re.DOTALL):
                issues.append(issue)
            issues = '\n'.join(issues).strip()
            if issues:
                issues = (f'The checked frame is: {frame_name}\n'
                          f'Problems found: {issues}\n')

            pattern = r'<description>(.*?)</description>'
            desc = []
            for _desc in re.findall(pattern, response_text, re.DOTALL):
                desc.append(_desc)
            desc = '\n'.join(desc).strip()
            if issues and desc:
                issues = (f'{issues}'
                          f'The detail description of this frame: {desc}\n')
            all_issues.append(issues)

        all_issues = '\n\n'.join(all_issues).strip()
        return all_issues

    @staticmethod
    def _extract_preview_frames_static(video_path, segment_id, work_dir,
                                       cur_check_round):

        test_dir = os.path.join(work_dir, 'manim_test')
        os.makedirs(test_dir, exist_ok=True)
        video = VideoFileClip(video_path)
        duration = video.duration

        timestamps = {1: duration / 2, 2: max(0, duration - 0.5)}

        preview_paths = []
        for frame_idx, timestamp in timestamps.items():
            output_path = os.path.join(
                test_dir,
                f'segment_{segment_id + 1}_round{cur_check_round}_{frame_idx}.png'
            )
            video.save_frame(output_path, t=timestamp)
            preview_paths.append(output_path)
        video.close()
        return preview_paths

    @staticmethod
    def get_image_size(filename):
        with Image.open(filename) as img:
            return f'{img.width}x{img.height}'

    @staticmethod
    def get_all_images_info(segment, i, image_dir):
        all_images_info = []
        foreground = segment.get('foreground', [])
        for idx, _req in enumerate(foreground):
            foreground_image = os.path.join(
                image_dir, f'illustration_{i + 1}_foreground_{idx + 1}.png')
            size = RenderManim.get_image_size(foreground_image)
            image_info = {
                'filename': foreground_image,
                'size': size,
                'description': _req,
            }
            all_images_info.append(image_info)

        image_info_file = os.path.join(
            os.path.dirname(image_dir), 'image_info.txt')
        if os.path.exists(image_info_file):
            with open(image_info_file, 'r') as f:
                for line in f.readlines():
                    if not line.strip():
                        continue
                    image_info = json.loads(line)
                    if image_info['filename'] in segment.get('user_image', []):
                        all_images_info.append(image_info)
        return all_images_info

    @staticmethod
    def _fix_manim_code_impl(llm, error_log, fix_history, manim_code,
                             manim_requirement, class_name, content,
                             audio_duration, segment, i, work_dir):
        image_dir = os.path.join(work_dir, 'images')
        images_info = RenderManim.get_all_images_info(segment, i, image_dir)

        if images_info:
            image_prompt = f"""
- ImageInfo:

{images_info}

These images must be used.

* Important: Use smaller image sizes for generated images and larger image sizes for user doc images. DO NOT crop image to circular**
* Scale the images. Do not use the original size, carefully rescale the images to match the requirements below:
    * The image size on the canvas depend on its importance, important image occupies more spaces
    * Use 1/4 space of the canvas for each image
""" # noqa
        else:
            image_prompt = ''

        fix_request = f"""You are a professional code debugging specialist. You need to help me fix issues in the code. Error messages will be passed directly to you. You need to carefully examine the problems and provide the correct, complete code.
{error_log}

**Original Code**:
```python
{manim_code}
```

{image_prompt}

{fix_history}

**Original code task**: Create manim animation
- Class name: {class_name}
- Content: {content}
- Duration: {audio_duration} seconds
- Code language: **Python**


Manim instructions:

* Canvas size ratio: 16:9
* Ensure all content stays within safe bounds x∈(-6.0, 6.0), y∈(-3.4, 3.4) with minimum buff=0.5 from any edge to prevent cropping.
* [CRITICAL]Absolutely prevent **element spatial overlap** or **elements going out of bounds** or **elements not aligned**.
* [CRITICAL]Connection lines between boxes/text are of proper length, with **both endpoints attached to the objects**.
* All boxes must have thick strokes for clear visibility
* Keep text within frame by controlling font sizes. Use smaller fonts for Latin script than Chinese due to longer length.
* Use clear, high-contrast font colors to prevent text from blending with the background
* Use a cohesive color palette of 2-4 colors for the entire video. Avoid cluttered colors, bright blue, and bright yellow. Prefer deep, dark tones
* Low-quality animations such as stick figures are forbidden
* Do not use any matchstick-style or pixel-style animations. Use charts, images, industrial/academic-style animations
* Text box needs to have a background color, and the background must be opaque, with high contrast between the text color and the background.
* The text box should large enough to contain the text
* Do not create multi-track complex manim animations. One object per segment, or two to three(NO MORE THAN three!) object arranged in a simple manner, manim layout rules:
    1. One object in the middle
    2. Two objects, left-right structure, same y axis, same size, for example, text left, chart right
    3. Three objects, left-middle-right structure, same y axis, same size. No more than 3 elements in one segment
    4. Split complex animation into several segments
    5. Less text boxes in the animation, only titles/definitions/formulas
    6. Use black fonts, **no gray fonts**
    7. CRITICAL: **NEVER put an element to a corner, do use horizonal/vertical grid**
    8. No pie charts should be used, the LLM costs many bugs
    9. Do not use SVGMobject("magnifying_glass") or any other built-in SVG names that might not exist. If you need an icon, use a simple geometric shape (like a Circle with a Line handle) or check if an image file is provided.
    10. Do not use `LineGraph` or `LineChart` classes as they are not available in the current Manim version. Use `Axes` and `plot_line_graph` or construct charts manually using `Axes` and `Line` objects.

    9. Do not use SVGMobject("magnifying_glass") or any other built-in SVG names that might not exist. If you need an icon, use a simple geometric shape (like a Circle with a Line handle) or check if an image file is provided.
    10. Do not use `LineGraph` or `LineChart` classes as they are not available in the current Manim version. Use `Axes` and `plot_line_graph` or construct charts manually using `Axes` and `Line` objects.

    9. [CRITICAL] **Do NOT use `VGroup` for `ImageMobject`**. `ImageMobject` is not a `VMobject`. Use `Group` instead of `VGroup` when grouping images or mixing images with other mobjects.

**Color Suggestions**:
* You need to explicitly specify element colors and make these colors coordinated and elegant in style.
* Consider the advices from the storyboard designer.

Fixing detected issues, plus any other problems you find. Verify:
* All elements follow instructions
* No overlapping or edge cutoff, **ensure all manim elements after rendering are within x∈(-6.0, 6.0), y∈(-3.4, 3.4)**
* No new layout issues introduced
* Prioritize high-impact fixes if needed
* Make minimal code changes to fix the issue while keeping the correct parts unchanged
* Watch for AI-generated code errors
* If the problem is hard to solve, rewrite the code
* The code may contain images & image effects, such as glowing or frames
    - **don't remove any image or its effects when making modifications**

Please precisely fix the detected issues while maintaining the richness and creativity of the animation.
""" # noqa
        inputs = [Message(role='user', content=fix_request)]
        _response_message = llm.generate(inputs)
        response = _response_message.content
        if '```python' in response:
            manim_code = response.split('```python')[1].split('```')[0]
        elif '```' in response:
            manim_code = response.split('```')[1].split('```')[0]
        else:
            manim_code = response
        fix_history = (
            f'You have a fix history which generates the code which is given to you:\n\n{fix_request}\n\n'
            f'If last error is same with latest error, **You probably find a wrong root cause**, '
            f'Check carefully and fix it again.**')
        return manim_code, fix_history

    @staticmethod
    def verify_and_fix_mov_file(mov_path):
        clip = VideoFileClip(mov_path)
        frame = clip.get_frame(0)
        clip.close()
        return frame is not None

    @staticmethod
    def convert_mov_to_compatible(mov_path):
        base_path, ext = os.path.splitext(mov_path)
        fixed_path = f'{base_path}_fixed.mov'
        clip = VideoFileClip(mov_path)
        clip.write_videofile(
            fixed_path,
            codec='libx264',
            audio_codec='aac' if clip.audio else None,
            fps=24,
            verbose=False,
            logger=None,
            ffmpeg_params=['-pix_fmt', 'yuva420p'])

        clip.close()
        if RenderManim.verify_and_fix_mov_file(fixed_path):
            return fixed_path
        else:
            return None

    @staticmethod
    def scale_video_to_fit(video_path, target_size=None):
        if target_size is None:
            target_size = RenderManim.window_size
        if not os.path.exists(video_path):
            return video_path

        clip = VideoFileClip(video_path)
        original_size = clip.size

        target_width, target_height = target_size
        original_width, original_height = original_size

        scale_x = target_width / original_width
        scale_y = target_height / original_height
        scale_factor = min(scale_x, scale_y, 1.0)

        if scale_factor < 0.95:
            scaled_clip = clip.resized(scale_factor)

            base_path, ext = os.path.splitext(video_path)
            scaled_path = f'{base_path}_scaled{ext}'
            scaled_clip.write_videofile(
                scaled_path,
                codec='libx264',
                audio_codec='aac' if scaled_clip.audio else None,
                fps=24,
                verbose=False,
                logger=None)

            clip.close()
            scaled_clip.close()
            return scaled_path
        else:
            return video_path
