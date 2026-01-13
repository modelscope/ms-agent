# Copyright (c) Alibaba, Inc. and its affiliates.
import base64
import os
import re
import shutil
import subprocess
import threading
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple, Union

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig
from PIL import Image, ImageDraw

logger = get_logger()


class RenderRemotion(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.num_parallel = getattr(self.config, 'llm_num_parallel', 5)
        # When enabled, render compositions one-by-one and attempt a fix immediately on failure.
        # This reduces wasted work when one broken Segment TSX causes global bundler failure.
        self.render_immediate_fix = getattr(self.config,
                                            'render_immediate_fix', True)

        self.render_dir = os.path.join(self.work_dir, 'remotion_render')
        self.remotion_project_dir = os.path.join(self.work_dir,
                                                 'remotion_project')
        self.remotion_code_dir = os.path.join(self.work_dir, 'remotion_code')
        self.images_dir = os.path.join(self.work_dir, 'images')
        self.code_fix_dir = os.path.join(self.work_dir, 'code_fix')
        self.code_fix_round = getattr(self.config, 'code_fix_round', 3)
        # Default to 1 to ensure visual quality check runs at least once unless explicitly disabled (-1)
        self.mllm_check_round = getattr(self.config, 'mllm_fix_round', 1)
        # Maximum times to attempt automatic visual fixes per segment
        self.max_visual_fix_rounds = getattr(self.config,
                                             'max_visual_fix_rounds', 2)
        # Track per-segment visual failure counts
        self.visual_fail_counts = defaultdict(int)

        os.makedirs(self.render_dir, exist_ok=True)
        os.makedirs(self.code_fix_dir, exist_ok=True)

    async def execute_code(self, messages: Union[str, List[Message]],
                           **kwargs) -> List[Message]:
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)
        with open(os.path.join(self.work_dir, 'audio_info.txt'), 'r') as f:
            audio_infos = json.load(f)

        logger.info('Setting up Remotion project.')
        self._setup_remotion_project(segments, audio_infos)

        # Ensure browser is installed before parallel rendering
        self._ensure_browser(self.remotion_project_dir)

        # Initialize status for all segments: None = not started, True = success, False = failed
        segment_status = {i: None for i in range(len(segments))}

        for round_idx in range(self.code_fix_round + 1):
            # Identify segments needing render (all initially, then only failed ones)
            segments_to_render = [
                i for i, status in segment_status.items() if status is not True
            ]

            if not segments_to_render:
                logger.info('All segments rendered successfully.')
                break

            logger.info(
                f'Round {round_idx + 1}: Rendering {len(segments_to_render)} segments...'
            )

            results = {}

            def _read_current_code(seg_i: int) -> str:
                code_path = os.path.join(self.remotion_code_dir,
                                         f'Segment{seg_i+1}.tsx')
                if os.path.exists(code_path):
                    with open(code_path, 'r', encoding='utf-8') as f:
                        return f.read()
                project_code_path = os.path.join(self.remotion_project_dir,
                                                 'src',
                                                 f'Segment{seg_i+1}.tsx')
                if os.path.exists(project_code_path):
                    with open(project_code_path, 'r', encoding='utf-8') as f:
                        return f.read()
                return ''

            def _extract_error_segment_indices(
                    log_text: Optional[str]) -> List[int]:
                if not log_text:
                    return []
                # esbuild/webpack error lines usually include: ...\src\Segment15.tsx:...
                segs = []
                for m in re.finditer(r'src[\\/]+Segment(\d+)\.tsx', log_text):
                    try:
                        segs.append(int(m.group(1)) - 1)
                    except Exception:
                        continue
                return segs

            # Render sequentially; if any render fails, fix immediately and retry once.
            for i in segments_to_render:
                i, success, error_log = self._render_remotion_scene_static(
                    i,
                    segments[i],
                    audio_infos[i]['audio_duration'],
                    self.config,
                    self.work_dir,
                    self.render_dir,
                    self.remotion_project_dir,
                    self.mllm_check_round,
                )
                results[i] = (success, error_log)
                segment_status[i] = success

                if success or round_idx >= self.code_fix_round:
                    continue

                # Immediate fix: prefer the actual offending Segment file referenced by bundler errors.
                # If bundler fails globally, error_log points to the culprit file.
                culprit_indices = _extract_error_segment_indices(error_log)
                to_fix = culprit_indices if culprit_indices else [i]
                to_fix = sorted(
                    {idx
                     for idx in to_fix if 0 <= idx < len(segments)})

                # If the error points to OTHER segments, it means the current segment failed due to global breakage.
                # Pause and fix the root cause first.
                logger.info(
                    f'Immediate fix triggered by failure on segment {i+1}. Fix targets: {[x+1 for x in to_fix]}'
                )

                # Apply fixes
                fix_applied = False
                for fix_i in to_fix:
                    err_text = error_log or 'Unknown error'
                    error_file = os.path.join(self.code_fix_dir,
                                              f'code_fix_{fix_i + 1}.txt')
                    with open(error_file, 'w', encoding='utf-8') as f:
                        f.write(err_text)

                    current_code = _read_current_code(fix_i)
                    _, fixed_code = self._fix_code_static(
                        fix_i, err_text, current_code, self.config,
                        self.remotion_project_dir)
                    if fixed_code:
                        self._update_segment_code(fix_i, fixed_code)
                        fix_applied = True
                        # If we fixed a different segment, we should probably reset its status too
                        if fix_i != i:
                            segment_status[
                                fix_i] = None  # Force re-render of the culprit later if it was skipped

                # Retry the current segment once after applying fixes.
                if fix_applied:
                    logger.info(
                        f'Retrying segment {i+1} after fixes applied...')
                    _, success2, error_log2 = self._render_remotion_scene_static(
                        i,
                        segments[i],
                        audio_infos[i]['audio_duration'],
                        self.config,
                        self.work_dir,
                        self.render_dir,
                        self.remotion_project_dir,
                        self.mllm_check_round,
                    )
                    results[i] = (success2, error_log2)
                    segment_status[i] = success2

            # Check results
            failed_segments = [
                i for i, (success, _) in results.items() if not success
            ]

            # --- VISUAL AUDIT (Post-Render Batch) ---
            # Now that rendering is physically complete for this round, we perform visual checks
            # on the *successful* segments. If they fail visual check, we demote them to "failed_segments"
            # and provide the MLLM feedback as the "error log" for the fixer.

            succeeded_segments = [
                i for i, (success, _) in results.items() if success
            ]
            if succeeded_segments and self.mllm_check_round > 0:
                logger.info(
                    f'Performing Batch Visual Audit on {len(succeeded_segments)} segments...'
                )
                # We can reuse the thread pool for checking since it's IO bound (LLM calls)
                visual_check_tasks = []
                for i in succeeded_segments:
                    # Construct paths
                    segment_data = segments[i]

                    # Load Visual Plan to check keywords
                    visual_plan_path = os.path.join(self.work_dir,
                                                    'visual_plans',
                                                    f'plan_{i+1}.json')
                    if os.path.exists(visual_plan_path):
                        try:
                            with open(
                                    visual_plan_path, 'r',
                                    encoding='utf-8') as f:
                                plan = json.load(f)
                                segment_data = {
                                    **segment_data,
                                    **plan
                                }  # Merge plan into segment data
                        except Exception:
                            pass

                    # Read the current Code for auditing
                    code_to_check = _read_current_code(i)

                    duration = audio_infos[i]['audio_duration']
                    visual_check_tasks.append(
                        (i, code_to_check, segment_data, duration))

                with ThreadPoolExecutor(
                        max_workers=self.num_parallel) as executor:
                    check_futures = {
                        executor.submit(self.check_code_quality, v_code, v_i,
                                        self.config, v_seg, v_dur): v_i
                        for v_i, v_code, v_seg, v_dur in visual_check_tasks
                    }

                    for future in as_completed(check_futures):
                        idx = check_futures[future]
                        visual_feedback = future.result()

                        if visual_feedback:  # If not None, it failed check
                            self.visual_fail_counts[idx] += 1
                            logger.warning(
                                f'Segment {idx+1} rejected by Visual Audit '
                                f'(attempt {self.visual_fail_counts[idx]}): '
                                f'{visual_feedback}')

                            if self.visual_fail_counts[
                                    idx] <= self.max_visual_fix_rounds:
                                # Mark as failed
                                failed_segments.append(idx)
                                # Update the result tuple to reflect failure and new error log
                                results[idx] = (
                                    False,
                                    f'VISUAL_AUDIT_FAIL:\n{visual_feedback}')
                                segment_status[
                                    idx] = False  # Mark for re-render next round
                            else:
                                logger.warning(
                                    f'Segment {idx+1} reached max visual fix attempts '
                                    f'({self.max_visual_fix_rounds}). Accepting with defects.'
                                )
                                # Do NOT add to failed_segments, effectively accepting it.
                                # results[idx] is currently (True, None) from the render step, or update it to warn?
                                results[idx] = (
                                    True,
                                    f'WARNING: Accepted with visual defects: {visual_feedback}'
                                )
                                segment_status[idx] = True
                        else:
                            logger.info(
                                f'Segment {idx+1} passed Visual Audit.')

            failed_segments = sorted(list(set(failed_segments)))  # Deduplicate

            def _extract_error_segment_indices(
                    log_text: Optional[str]) -> List[int]:
                if not log_text:
                    return []
                # esbuild/webpack error lines usually include: ...\src\Segment15.tsx:...
                segs = []
                for m in re.finditer(r'src[\\/]+Segment(\d+)\.tsx', log_text):
                    try:
                        segs.append(int(m.group(1)) - 1)
                    except Exception:
                        continue
                return segs

            if not failed_segments:
                logger.info('All rendered segments succeeded in this round.')
                continue  # Loop will break at start of next iteration

            if round_idx == self.code_fix_round:
                logger.warning(
                    f'Max fix rounds reached. Failed segments: {failed_segments}'
                )
                break

            logger.info(
                f'Round {round_idx + 1}: {len(failed_segments)} segments failed. Attempting to fix...'
            )

            # If the bundler fails, Remotion cannot render ANY composition.
            # In that case, the error log will reference the *actual* offending Segment file,
            # and fixing every failed segment is counterproductive.
            # The error log for ALL segments will point to the ONE broken file.
            referenced = set()
            for seg_idx, (success, error_log) in results.items():
                if success:
                    continue
                # Extract any referenced "SegmentX.tsx" from the error log
                found_indices = _extract_error_segment_indices(error_log)
                for idx in found_indices:
                    # Only care if the error points to a file that is NOT the current file
                    if 0 <= idx < len(segments):
                        referenced.add(idx)

            if referenced:
                logger.info(
                    'Detected global bundling failure caused by specific '
                    'segments. Prioritizing fix for: '
                    f'{sorted([i+1 for i in referenced])}')
                # If we found culprit(s), we IGNORE the general list of failures for this repair round,
                # and ONLY fix the culprit(s). This prevents the agent from hallucinating fixes for innocent files.
                failed_segments = sorted(list(referenced))

            # Prepare fix tasks
            fix_tasks = []
            for i in failed_segments:
                success, error_log = results[i]
                # Write error log
                error_file = os.path.join(self.code_fix_dir,
                                          f'code_fix_{i + 1}.txt')
                with open(error_file, 'w', encoding='utf-8') as f:
                    f.write(error_log or 'Unknown error')

                # Read current code
                current_code = _read_current_code(i)

                fix_tasks.append((i, error_log, current_code))

            # Run parallel fix
            with ThreadPoolExecutor(max_workers=self.num_parallel) as executor:
                futures = {
                    executor.submit(self._fix_code_static, i, error_log, code,
                                    self.config, self.remotion_project_dir): i
                    for i, error_log, code in fix_tasks
                }
                for future in as_completed(futures):
                    i, fixed_code = future.result()
                    if fixed_code:
                        # Update source files in both locations
                        self._update_segment_code(i, fixed_code)

        return messages

    def _update_segment_code(self, i, code):
        # Enforce transparent output: remove backgrounds before writing.
        code = self._strip_background_color(code)
        code = self._strip_background_images(code)

        # Enforce universal bounds safety
        try:
            code = self._enforce_image_constraints(code)
            code = self._enforce_layout_safety(code)
        except Exception:
            pass

        # Best-effort TSX sanitizer to prevent bundling failures.
        try:
            code = RenderRemotion._auto_fix_template_parens(code)
            code = RenderRemotion._auto_fix_common_concat_syntax(code)

            # Auto-fix: Convert standard <img> to <Img> and inject imports
            # 1. Convert <img src="/images/..."> to <Img src={staticFile("images/...")}>
            if '<img' in code:
                code = re.sub(
                    r'<img\s+([^>]*?)src=["\']/images/([^"\']+)["\']([^>]*?)>',
                    r'<Img \1src={staticFile("images/\2")} \3>', code)
                code = code.replace('<img ', '<Img ')

            # 2. Ensure staticFile and Img are imported if used
            needed = []
            # Check if used but not imported (simple heuristic)
            if 'staticFile' in code and not re.search(
                    r'import\s+.*staticFile.*from', code):
                needed.append('staticFile')
            if 'Img' in code and not re.search(r'import\s+.*Img.*from', code):
                needed.append('Img')

            if needed:
                imports_str = ', '.join(needed)
                # Try to append to existing Remotion import
                if re.search(r'import\s+\{.*\}\s+from\s+[\'"]remotion[\'"]',
                             code):
                    # Use a function for replacement to handle the string safely
                    def _add_import(m):
                        return f', {imports_str} }} from \'remotion\''

                    code = re.sub(
                        r'\}\s*from\s*[\'"]remotion[\'"]',
                        _add_import,
                        code,
                        count=1)
                else:
                    code = f"import {{ {imports_str} }} from 'remotion';\n" + code

        except Exception:
            pass
        # Update in remotion_code_dir (source of truth)
        src_file = os.path.join(self.remotion_code_dir, f'Segment{i+1}.tsx')
        with open(src_file, 'w', encoding='utf-8') as f:
            f.write(code)

        # Update in remotion_project_dir (execution env)
        dst_file = os.path.join(self.remotion_project_dir, 'src',
                                f'Segment{i+1}.tsx')
        with open(dst_file, 'w', encoding='utf-8') as f:
            f.write(code)

    def _setup_remotion_project(self, segments, audio_infos):
        # 1. Create project structure
        os.makedirs(
            os.path.join(self.remotion_project_dir, 'src'), exist_ok=True)
        os.makedirs(
            os.path.join(self.remotion_project_dir, 'public', 'images'),
            exist_ok=True)
        # Some generated TSX may import assets via relative paths like `./images/foo.png`.
        # Keep a mirrored copy under `src/images` to avoid bundler module resolution failures.
        os.makedirs(
            os.path.join(self.remotion_project_dir, 'src', 'images'),
            exist_ok=True)

        # 2. Copy images and validate them.
        def write_placeholder(dest_path, w=1280, h=720, color=(240, 240, 240)):
            try:
                img = Image.new('RGB', (w, h), color)
                draw = ImageDraw.Draw(img)
                draw.text((20, 20),
                          os.path.basename(dest_path),
                          fill=(80, 80, 80))
                img.save(dest_path, format='PNG')
                return
            except Exception:
                transparent_png_b64 = (
                    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII='
                )
                with open(dest_path, 'wb') as _f:
                    _f.write(base64.b64decode(transparent_png_b64))

        if os.path.exists(self.images_dir):
            for file in os.listdir(self.images_dir):
                src = os.path.join(self.images_dir, file)
                dst_public = os.path.join(self.remotion_project_dir, 'public',
                                          'images', file)
                dst_src = os.path.join(self.remotion_project_dir, 'src',
                                       'images', file)

                for dst in (dst_public, dst_src):
                    try:
                        shutil.copy(src, dst)
                        try:
                            with Image.open(dst) as im:
                                im.verify()
                        except Exception:
                            write_placeholder(dst)
                    except Exception:
                        write_placeholder(dst)

        # Create placeholders for likely referenced names
        for i in range(1, len(segments) + 1):
            bg_name = f'illustration_{i}_background.png'
            for base_dir in ('public', 'src'):
                bg_dst = os.path.join(self.remotion_project_dir, base_dir,
                                      'images', bg_name)
                if not os.path.exists(bg_dst):
                    write_placeholder(bg_dst)
            for j in range(1, 4):
                fg_name = f'illustration_{i}_foreground_{j}.png'
                for base_dir in ('public', 'src'):
                    fg_dst = os.path.join(self.remotion_project_dir, base_dir,
                                          'images', fg_name)
                    if not os.path.exists(fg_dst):
                        write_placeholder(fg_dst)

        # 3. Copy generated code
        for i in range(len(segments)):
            src_file = os.path.join(self.remotion_code_dir,
                                    f'Segment{i+1}.tsx')
            dst_file = os.path.join(self.remotion_project_dir, 'src',
                                    f'Segment{i+1}.tsx')
            if os.path.exists(src_file):
                # Sanitize code to reduce common esbuild/TSX syntax failures.
                with open(src_file, 'r', encoding='utf-8') as f:
                    code = f.read()

                # Apply proactive fixes
                try:
                    code = RenderRemotion._auto_fix_template_parens(code)
                    code = RenderRemotion._auto_fix_common_concat_syntax(code)
                except Exception:
                    pass

                # Enforce universal bounds safety and layout on SETUP
                try:
                    code = RenderRemotion._enforce_image_constraints(code)
                    code = RenderRemotion._enforce_layout_safety(code)
                except Exception:
                    pass

                # Enforce transparent output: remove full-screen backgrounds.
                code = self._strip_background_color(code)
                code = self._strip_background_images(code)
                with open(dst_file, 'w', encoding='utf-8') as f:
                    f.write(code)
            else:
                # Create a dummy file if missing to prevent build failure
                with open(dst_file, 'w') as f:
                    f.write(
                        f"import React from 'react';\nexport const Segment{i+1} = () => <div>Missing Segment</div>;"
                    )

        # 4. Create package.json with locked versions
        package_json = {
            'name': 'remotion-project',
            'version': '1.0.0',
            'dependencies': {
                'react': '^18.2.0',
                'react-dom': '^18.2.0',
                'remotion': '^4.0.0',
                '@remotion/cli': '^4.0.0',
                '@remotion/bundler': '^4.0.0',
                '@remotion/renderer': '^4.0.0',
                '@remotion/shapes': '^4.0.0',
                '@remotion/media-utils': '^4.0.0'
            }
        }
        with open(
                os.path.join(self.remotion_project_dir, 'package.json'),
                'w') as f:
            json.dump(package_json, f, indent=2)

        # 5. Create src/index.ts
        with open(
                os.path.join(self.remotion_project_dir, 'src', 'index.ts'),
                'w') as f:
            f.write("import { registerRoot } from 'remotion';\n")
            f.write("import { RemotionRoot } from './Root';\n")
            f.write('registerRoot(RemotionRoot);\n')

        # 6. Create src/Root.tsx
        fps = self.config.video.fps
        width = 1280
        height = 720
        if hasattr(self.config.video, 'size'):
            try:
                w, h = self.config.video.size.split('x')
                width = int(w)
                height = int(h)
            except Exception:
                pass

        root_content = "import React from 'react';\n"
        root_content += "import { Composition } from 'remotion';\n"
        for i in range(len(segments)):
            root_content += f"import * as Segment{i+1}_NS from './Segment{i+1}';\n"

        root_content += '\nexport const RemotionRoot: React.FC = () => {\n'
        for i in range(len(segments)):
            root_content += (
                f'  const Segment{i+1} = Segment{i+1}_NS.default || '
                f'Segment{i+1}_NS.Segment{i+1} || (() => null);\n')

        root_content += '  return (\n'
        root_content += '    <>\n'

        for i, audio_info in enumerate(audio_infos):
            duration_in_frames = int(audio_info['audio_duration'] * fps)
            root_content += '      <Composition\n'
            root_content += f"        id=\"Segment{i+1}\"\n"
            root_content += f'        component={{Segment{i+1}}}\n'
            root_content += f'        durationInFrames={{{duration_in_frames}}}\n'
            root_content += f'        fps={{{fps}}}\n'
            root_content += f'        width={{{width}}}\n'
            root_content += f'        height={{{height}}}\n'
            root_content += '      />\n'

        root_content += '    </>\n'
        root_content += '  );\n'
        root_content += '};\n'

        with open(
                os.path.join(self.remotion_project_dir, 'src', 'Root.tsx'),
                'w') as f:
            f.write(root_content)

        # 7. Create tsconfig.json
        tsconfig = {
            'compilerOptions': {
                'allowJs': True,
                'checkJs': True,
                'esModuleInterop': True,
                'forceConsistentCasingInFileNames': True,
                'resolveJsonModule': True,
                'skipLibCheck': True,
                'sourceMap': True,
                'strict': True,
                'target': 'esnext',
                'module': 'esnext',
                'moduleResolution': 'node',
                'jsx': 'react-jsx',
                'noEmit': True,
                'isolatedModules': True
            },
            'include': ['src']
        }
        with open(
                os.path.join(self.remotion_project_dir, 'tsconfig.json'),
                'w') as f:
            json.dump(tsconfig, f, indent=2)

        # 8. Install dependencies
        node_modules_dir = os.path.join(self.remotion_project_dir,
                                        'node_modules')
        if not os.path.exists(node_modules_dir):
            logger.info('Installing dependencies...')
            subprocess.run(
                'npm install',
                cwd=self.remotion_project_dir,
                shell=True,
                check=True)

    def _ensure_browser(self, remotion_project_dir):
        # Check for global browser cache to avoid re-downloading.
        user_home = os.path.expanduser('~')
        global_browser_cache = os.path.join(user_home,
                                            '.ms_agent_remotion_browser')
        local_browser_cache = os.path.join(remotion_project_dir,
                                           'node_modules', '.remotion')

        # Link or copy cached browser if available.
        if os.path.exists(global_browser_cache):
            logger.info(
                f'Found cached Chrome in {global_browser_cache}. Linking to project...'
            )
            if not os.path.exists(local_browser_cache):
                try:
                    # Windows usually requires admin for symlinks, so we copy.
                    # Copying is still much faster than downloading 300MB+
                    shutil.copytree(global_browser_cache, local_browser_cache)
                    logger.info('Browser restored from cache.')
                    return
                except Exception as e:
                    logger.warning(f'Failed to copy cached browser: {e}')

        # Check if browser is already installed in project (standard check)
        browser_found = False
        if os.path.exists(local_browser_cache):
            for root, _, files in os.walk(local_browser_cache):
                if 'chrome-headless-shell.exe' in files or 'chrome-headless-shell' in files:
                    browser_found = True
                    break

        if browser_found:
            logger.info(
                "Remotion browser detected locally. Skipping 'browser ensure'."
            )
            # Cache it for next time!
            if not os.path.exists(global_browser_cache):
                try:
                    logger.info(
                        f'Caching browser to {global_browser_cache} for future runs...'
                    )
                    shutil.copytree(local_browser_cache, global_browser_cache)
                except Exception as e:
                    logger.warning(f'Failed to cache browser: {e}')
            return

        # 1. Try to download from manual mirror first.
        logger.info(
            'Attempting to manually download Remotion browser from npmmirror...'
        )

        # Use a specific version known to work.
        # Link: https://npmmirror.com/mirrors/chrome-for-testing/134.0.6998.35/win64/chrome-headless-shell-win64.zip
        version = '134.0.6998.35'
        platform_str = 'win64' if os.name == 'nt' else 'linux64'
        filename = f'chrome-headless-shell-{platform_str}.zip'
        mirror_url = f'https://npmmirror.com/mirrors/chrome-for-testing/{version}/{platform_str}/{filename}'

        try:
            logger.info(f'Downloading {mirror_url}...')
            zip_target = os.path.join(remotion_project_dir, filename)
            urllib.request.urlretrieve(mirror_url, zip_target)

            logger.info('Extracting browser...')
            os.makedirs(local_browser_cache, exist_ok=True)
            with zipfile.ZipFile(zip_target, 'r') as zip_ref:
                zip_ref.extractall(local_browser_cache)

            if os.path.exists(zip_target):
                os.remove(zip_target)

            logger.info('Browser downloaded and extracted successfully.')

            # Cache it globally immediately
            if not os.path.exists(global_browser_cache):
                try:
                    logger.info(
                        f'Caching browser to {global_browser_cache} for future runs...'
                    )
                    shutil.copytree(local_browser_cache, global_browser_cache)
                except Exception as e:
                    logger.warning(f'Failed to cache browser: {e}')

            return

        except Exception as e:
            logger.warning(
                f'Failed to manually download browser from mirror: {e}')

        # Fallback to standard ensuring if manual download fails
        logger.info("Falling back to standard 'browser ensure'...")
        os.environ['PUPPETEER_DOWNLOAD_HOST'] = 'https://npmmirror.com/mirrors'

        if os.name == 'nt':
            remotion_cmd = os.path.abspath(
                os.path.join(remotion_project_dir, 'node_modules', '.bin',
                             'remotion.cmd'))
        else:
            remotion_cmd = os.path.abspath(
                os.path.join(remotion_project_dir, 'node_modules', '.bin',
                             'remotion'))

        if not os.path.exists(remotion_cmd):
            remotion_cmd = 'npx remotion'

        try:
            if os.name == 'nt' and 'remotion.cmd' in remotion_cmd:
                cmd_str = f'"{remotion_cmd}" browser ensure'
                subprocess.run(
                    cmd_str, cwd=remotion_project_dir, shell=True, check=True)
            else:
                cmd = [remotion_cmd, 'browser', 'ensure']
                if isinstance(
                        remotion_cmd,
                        str) and ' ' in remotion_cmd and 'npx' in remotion_cmd:
                    cmd = remotion_cmd.split() + ['browser', 'ensure']
                subprocess.run(cmd, cwd=remotion_project_dir, check=True)
            logger.info('Browser download successful (via standard ensure).')
            return
        except subprocess.CalledProcessError as e:
            logger.warning(
                f'Failed to download browser from mirror via CLI: {e}')

        # 2. Fallback to System Chrome (ONLY IF DOWNLOAD FAILS)
        logger.info('Falling back to System Chrome detection...')
        # shutil is already imported at module level
        system_chrome = (
            shutil.which('chrome') or shutil.which('google-chrome')
            or shutil.which('chromium') or shutil.which('chromium-browser'))

        if not system_chrome and os.name == 'nt':
            possible_paths = [
                r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
                os.path.expandvars(
                    r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
                r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                r'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
            ]
            for p in possible_paths:
                if os.path.exists(p):
                    system_chrome = p
                    break

        if system_chrome:
            logger.info(
                f'System Chrome detected at {system_chrome}. Configuring Remotion to use it.'
            )
            os.environ['REMOTION_BROWSER_EXECUTABLE'] = system_chrome
            os.environ['PUPPETEER_EXECUTABLE_PATH'] = system_chrome
            return

        logger.error(
            'Could not find any browser (Download failed and no System Chrome found). Rendering will likely fail.'
        )

    @staticmethod
    def check_code_quality(code, i, config, segment, duration):
        """
        Use LLM to audit code quality, checking for layout issues (e.g. Flexbox vs Absolute).
        """
        # If no code, we can't check.
        if not code or len(code) < 50:
            return 'FAIL: Empty or invalid code.'

        llm = LLM.from_config(config)

        system_prompt = """You are a Senior React/Remotion Code Auditor.
Your goal is to ensure the generated video code is robust, responsive, and uses modern layout practices (Flexbox).

**CRITICAL FAILURE CRITERIA (Report these as FAIL)**:
1.  **Absolute Overlap Risk**: Using `position: 'absolute'` with `top: '50'`, `left: '50'` on MULTIPLE elements
    without distinct margins or transforms. This causes overlap.
2.  **Lack of Flexbox**: The main container should use `display: 'flex'` to manage layout structure (Text vs Image).
    - **VIOLATION**: If you see `AbsoluteFill` containing only direct children with `position: 'absolute'`, FAIL IT.
    - **REQUIREMENT**: There must be a flex container that separates content.
3.  **Hardcoded Dimensions (Universal Bounds Issue)**:
    - **VIOLATION**: Using fixed pixel widths/heights (e.g., `width: 500`, `left: 300`) for MAIN containers.
    - **REQUIREMENT**: Use percentages (e.g., `width: '50%'`) to ensure generic compatibility across resolutions.
4.  **Z-Index Chaos**: Elements using random high z-indexes (100, 999) to force visibility
    instead of proper DOM order.
5.  **Text Visibility**: Text containers MUST have a background color (e.g., `rgba(0,0,0,0.5)`)
    if they are overlaying images to prevent contrast issues.

**Context**:
- This is a 16:9 video (1280x720).
- We want a clean, high-end presentation style.

**Output Format**:
- If Clean: Output exactly `PASS`.
- If Issues: Output `FAIL: <Concise explanation of the code flaw and how to fix it>`.
"""

        user_prompt = f"""
Audit this Remotion Component Code for Segment {i+1}:

```typescript
{code}
```

Does this code follow best practices for layout safety (Flexbox) and avoid obvious overlap risks?
"""

        try:
            response = llm.generate([
                Message(role='system', content=system_prompt),
                Message(role='user', content=user_prompt)
            ])
            result = response.content.strip()

            if 'FAIL' in result:
                return result
            # If the LLM just chats but doesn't explicitly fail, we assume pass or look for negative keywords?
            # The prompt asks for explicit PASS/FAIL.
            if 'PASS' in result:
                return None

            # Fallback: if ambiguous, treat as pass but log? No, safe to pass if not explicit fail.
            return None

        except Exception as e:
            logger.warning(f'Code Audit Check failed: {e}')
            return None

    @staticmethod
    def _render_remotion_scene_static(
            i,
            segment,
            duration,
            config,
            work_dir,
            render_dir,
            remotion_project_dir,
            mllm_check_round=0) -> Tuple[int, bool, Optional[str]]:
        """Static method for multiprocessing"""
        composition_id = f'Segment{i+1}'
        output_dir_scene = os.path.join(render_dir, f'scene_{i+1}')
        os.makedirs(output_dir_scene, exist_ok=True)
        output_path = os.path.abspath(
            os.path.join(output_dir_scene, f'Scene{i+1}.mov'))

        logger.info(f'Rendering {composition_id} to {output_path}')

        # Determine remotion command
        if os.name == 'nt':
            remotion_cmd = os.path.abspath(
                os.path.join(remotion_project_dir, 'node_modules', '.bin',
                             'remotion.cmd'))
        else:
            remotion_cmd = os.path.abspath(
                os.path.join(remotion_project_dir, 'node_modules', '.bin',
                             'remotion'))

        if not os.path.exists(remotion_cmd):
            remotion_cmd = 'npx remotion'

        base_cmd = [
            'render', 'src/index.ts', composition_id, output_path,
            '--codec=prores', '--prores-profile=4444',
            '--pixel-format=yuva444p10le', '--image-format=png'
        ]

        # Try to find browser executable (Local > System)
        browser_executable = None
        remotion_cache_dir = os.path.join(remotion_project_dir, 'node_modules',
                                          '.remotion')

        # 1. Check Local Cache
        if os.path.exists(remotion_cache_dir):
            for root, _, files in os.walk(remotion_cache_dir):
                if 'chrome-headless-shell.exe' in files:
                    browser_executable = os.path.abspath(
                        os.path.join(root, 'chrome-headless-shell.exe'))
                    break
                elif 'chrome-headless-shell' in files:
                    browser_executable = os.path.abspath(
                        os.path.join(root, 'chrome-headless-shell'))
                    break

        # 2. Check System Chrome if not found locally
        if not browser_executable:
            browser_executable = os.environ.get('REMOTION_BROWSER_EXECUTABLE')

            if not browser_executable:
                # shutil is imported at module level
                browser_executable = (
                    shutil.which('chrome') or shutil.which('google-chrome')
                    or shutil.which('chromium')
                    or shutil.which('chromium-browser'))

                if not browser_executable and os.name == 'nt':
                    possible_paths = [
                        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
                        os.path.expandvars(
                            r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'
                        ),
                        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
                        os.path.expandvars(
                            r'%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe'
                        ),
                    ]
                    for p in possible_paths:
                        if os.path.exists(p):
                            browser_executable = p
                            break

        if browser_executable:
            logger.info(f'Using browser executable: {browser_executable}')
            base_cmd.extend(['--browser-executable', browser_executable])
            # Add stability flags
            base_cmd.extend([
                '--chromium-options',
                'no-sandbox,disable-setuid-sandbox,disable-gpu,disable-dev-shm-usage'
            ])

        if os.name == 'nt' and 'remotion.cmd' in remotion_cmd:
            cmd = [remotion_cmd] + base_cmd
        else:
            if 'npx' in remotion_cmd:
                cmd = remotion_cmd.split() + base_cmd
            else:
                cmd = [remotion_cmd] + base_cmd

        try:
            if isinstance(cmd, list):
                # On Windows, if we are running a .cmd file, we need shell=True.
                # But subprocess.run with shell=True and a list is tricky.
                # It's safer to join the command into a string for shell=True on Windows.
                if os.name == 'nt':
                    cmd_str = ' '.join(
                        [f'"{arg}"' if ' ' in arg else arg for arg in cmd])
                    result = subprocess.run(
                        cmd_str,
                        cwd=remotion_project_dir,
                        shell=True,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='ignore')
                else:
                    result = subprocess.run(
                        cmd,
                        cwd=remotion_project_dir,
                        shell=False,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='ignore')
            else:
                result = subprocess.run(
                    cmd,
                    cwd=remotion_project_dir,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore')

            if result.returncode != 0:
                # Capture output was set to True to allow smart error detection.
                log_content = (result.stderr or '') + '\n' + (
                    result.stdout or '')
                logger.warning(
                    f'Rendering failed for {composition_id}. Log (excerpt): {log_content[:500]}...'
                )
                return i, False, log_content
            else:
                logger.info(f'Rendered {composition_id} successfully.')

                # --- VISUAL CHECK MOVED TO STEP 14 (Global Check) ---
                # As per user request, we delay the MLLM visual inspection to the final composition stage.
                # This avoids blocking the render loop for every segment.

                return i, True, None

        except Exception as e:
            logger.error(f'Exception during rendering {composition_id}: {e}')
            return i, False, str(e)

    @staticmethod
    def _fix_code_static(i,
                         error_log,
                         code,
                         config,
                         remotion_project_dir=None):
        """Static method for multiprocessing fix"""
        if not code:
            return i, ''


# 1. Auto-fix template/parentheses issues.
        fixed_code = RenderRemotion._auto_fix_template_parens(code)
        if fixed_code != code:
            logger.info(f'Auto-fixed template/syntax issues for segment {i+1}')
            # Continue to use this fixed code, but still check if we need LLM.
            code = fixed_code

        # 2. Auto-fix common concatenation issues.
        fixed_code = RenderRemotion._auto_fix_common_concat_syntax(code)
        if fixed_code != code:
            logger.info(f'Auto-fixed concatenation syntax for segment {i+1}')
            # If this was a build failure, this simple fix might be enough.
            if error_log and ('Module build failed' in error_log
                              or 'Transform failed' in error_log):
                return i, fixed_code
            code = fixed_code

        # 3. Use LLM to fix remaining issues.
        llm = LLM.from_config(config)
        logger.info(f'Fixing code for segment {i+1} with LLM...')
        fixed_code = RenderRemotion._fix_code_impl(llm, error_log, code,
                                                   remotion_project_dir)

        # 4. Post-fix cleanup.
        if fixed_code:
            fixed_code = RenderRemotion._strip_background_color(fixed_code)
            fixed_code = RenderRemotion._strip_background_images(fixed_code)

        if fixed_code and RenderRemotion._is_valid_segment_component(
                fixed_code, i + 1):
            return i, fixed_code

        logger.warning(
            f'LLM returned invalid/partial code for segment {i+1}; keeping previous code to avoid breaking the project.'
        )
        return i, code

    @staticmethod
    def _strip_background_color(code: str) -> str:
        """Remove root-level background colors to ensure transparency."""
        try:
            # Replace backgroundColor: 'black' with backgroundColor: undefined
            # Also cover rgb/rgba black/white
            pattern = (
                r"backgroundColor:\s*['\"](black|white|#000|#fff|#000000|#ffffff|"
                r"rgb\(0,\s*0,\s*0\)|rgba\(0,\s*0,\s*0,\s*1\))['\"]")
            code = re.sub(
                pattern,
                'backgroundColor: undefined',
                code,
                flags=re.IGNORECASE,
            )
        except Exception:
            pass
        return code

    @staticmethod
    def _strip_background_images(code: str) -> str:
        """
        Remove background images to ensure ProRes 4444 transparency.
        The background is composed in a later step.
        """
        if not code:
            return code

        try:
            # Remove common wrapper pattern:
            # <AbsoluteFill ...> <Img src={staticFile("images/illustration_X_background.png")} ... /> </AbsoluteFill>
            code = re.sub(
                (r"<AbsoluteFill[^>]*>\s*<Img[\s\S]*?staticFile\(\s*['\"]"
                 r"images/illustration_\d+_background\.png['\"]\s*\)"
                 r'[\s\S]*?<\/AbsoluteFill>'),
                '',
                code,
                flags=re.IGNORECASE,
            )

            # Remove any remaining Img referencing illustration_*_background.png
            code = re.sub(
                (r"<Img[\s\S]*?staticFile\(\s*['\"]images/illustration_\d+_background\.png"
                 r"['\"]\s*\)[\s\S]*?\/?>"),
                '',
                code,
                flags=re.IGNORECASE,
            )

            # Remove inline CSS backgroundImage that references illustration_*_background.png
            code = re.sub(
                r'backgroundImage\s*:\s*[^,\n}]*illustration_\d+_background\.png[^,\n}]*,?',
                '',
                code,
                flags=re.IGNORECASE,
            )

            # Heuristic: Remove any full-screen image component with zIndex: -1 (often used as background)
            # e.g., <Img ... style={{width: '100%', height: '100%', zIndex: -1}} ... />
            # Matches src="..." then style with zIndex: -1 around it
            code = re.sub(
                r'<Img[^>]*style=\{[^}]*zIndex:\s*-1[^}]*\}[^>]*\/?>',
                '',
                code,
                flags=re.IGNORECASE)

            # Remove <AbsoluteFill zIndex={-1}> ... <Img ... width: '100%' ... /> ... </AbsoluteFill>
            # This is harder with regex, but we can catch the simple AbsoluteFill style={{zIndex: -1}} pattern
            code = re.sub(
                r'<AbsoluteFill[^>]*style=\{[^}]*zIndex:\s*-1[^}]*\}[^>]*>[\s\S]*?</AbsoluteFill>',
                '',
                code,
                flags=re.IGNORECASE)

            return code
        except Exception:
            return code

    @staticmethod
    def _is_valid_segment_component(code: str, segment_number: int) -> bool:
        """Heuristic validation to avoid overwriting with snippets.

        We require the code to contain an export for the expected Segment component.
        """
        if not code or len(code) < 50:
            return False
        expected = f'Segment{segment_number}'
        if f'export const {expected}' in code:
            return True
        if f'export function {expected}' in code:
            return True
        if f'export {{ {expected} }}' in code:
            return True
        return False

    @staticmethod
    def _fix_code_impl(llm, error_log, code, remotion_project_dir=None):
        available_images_info = ''
        if remotion_project_dir:
            try:
                images_path = os.path.join(remotion_project_dir, 'public',
                                           'images')
                if os.path.exists(images_path):
                    files = sorted(os.listdir(images_path))
                    available_images_info = '\nAvailable images in public/images/:\n' + '\n'.join(
                        [f'- {f}' for f in files])
            except Exception:
                pass

        if 'VISUAL CHECK FAILED' in error_log:
            fix_prompt = f"""
The Remotion code rendered successfully, but the AI Visual Inspector found layout/visual issues.
Visual Feedback:
{error_log}

**Original Code**:
```typescript
{code}
```

Please fix the code to resolve the VISUAL issues reported above.
- **SCALING & SIZING**: If images are cut off or too small, adjust `width`, `maxWidth` or `scale` intelligently.
- **LAYOUT STRATEGY**: If elements overlap, switch to Flexbox (`display: 'flex', flexDirection: 'column/row'`)
    to enforce separation, or adjust absolute coordinates.
- **BOUNDARIES**: Ensure content stays within the visible frame (1280x720).
- Do not change the component name.
- Return the full corrected code.
"""
        else:
            fix_prompt = f"""
The following Remotion/React code failed to render.
Error Log:
{error_log}

**Original Code**:
```typescript
{code}
```

Please fix the code to resolve the error.
- Focus on the error described in the log.
- Ensure the code is a valid React Functional Component.
- Do not change the component name or export style if possible.

**SPECIFIC ERROR GUIDANCE**:
1. **"inputRange must be strictly monotonically increasing"**:
   - You used `interpolate(frame, [20, 0], ...)` or similar unsorted array.
   - FIX: Sort the `inputRange` to `[0, 20]`.
   - CRITICAL: You MUST also reorder `outputRange` to match the new input order.

2. **"Failed to load resource" / 404 Errors**:
   - You are referencing an image that does not exist.
   - {available_images_info}
   - FIX: Use ONLY filenames from the list above. If the file isn't there, remove the `Img` tag.
   - Use `staticFile("images/filename.png")`.
   - FORBIDDEN: `http://...`, `/public/...` paths.

3. **UNIVERSAL LAYOUT RULES (PREVENT OVERLAP)**:
   - **Flexbox Protocol**: Use `display: 'flex'` on the container.
   - **Separation**: Put Text in a top container, Images in a bottom container (or side-by-side).
   - **Safe/Transparent**: Ensure text is readable (use background cards if needed) and verify `width: '85%'` safe area.
   - **No Absolute Center Collisions**: Never put two different elements at `top: 50%, left: 50%`.

4. **Transparency**:
   - Ensure `backgroundColor: undefined` (transparent) for the root.
   - Do NOT render full-screen background images.

Return the full corrected code.
"""
        inputs = [Message(role='user', content=fix_prompt)]
        _response_message = llm.generate(inputs)
        response = _response_message.content

        # Robust code extraction using regex
        code_match = re.search(
            r'```(?:typescript|tsx|js|javascript)?\s*(.*?)```', response,
            re.DOTALL)
        if code_match:
            code = code_match.group(1)
        else:
            code = response
            if 'import React' in code:
                idx = code.find('import React')
                code = code[idx:]

        return code.strip()

        # NOTE: `_auto_fix_common_concat_syntax` is implemented further below.
        code = re.sub(r'\+\s*"\)\)\s*\+\s*"\)', '+ ")"', code)  # Fallback

        # Pattern 2: `+ ')) + '` -> `+ '` (middle of chain)
        code = re.sub(r"\+\s*'\)\)\s*\+\s*'", "+ '", code)
        code = re.sub(r'\+\s*"\)\)\s*\+\s*"', '+ "', code)

        # Pattern 3: Stray `+ ')'` at end of transform sometimes if double added?
        # But be careful not to remove valid ones.

        return code

    @staticmethod
    def _auto_fix_template_parens(code: str) -> str:
        """Auto-fix common LLM TSX generation issues.

        1) Fix mismatched parentheses inside `${...}` template expressions.
        2) Convert `transform: `...${expr}...`` template literals into string concatenation.
           This avoids esbuild parse errors from complex nested braces/parens.
        """

        try:
            code = RenderRemotion._auto_fix_common_tsx_typos(code)
        except Exception:
            pass

        # Fix common pattern: `config: { ... ) }` (stray ')' before closing brace)
        try:
            code = re.sub(
                r'(\bconfig\s*:\s*\{[^}]*?)\)(\s*\})',
                r'\1\2',
                code,
                flags=re.DOTALL)
        except Exception:
            pass

        def _repair(match):
            inner = match.group(1)
            open_parens = inner.count('(')
            close_parens = inner.count(')')
            if open_parens > close_parens:
                inner = inner + (')' * (open_parens - close_parens))
            elif close_parens > open_parens:
                # Common LLM bug: extra closing parens right before `}` like `${0.3 + x)}`
                trimmed = inner.rstrip()
                extra = close_parens - open_parens
                while extra > 0 and trimmed.endswith(')'):
                    trimmed = trimmed[:-1].rstrip()
                    extra -= 1
                inner = trimmed
            return '${' + inner + '}'

        try:
            code = re.sub(r'\$\{([^}]*)\}', _repair, code)
        except Exception:
            pass

        # Fix a common typo: extra ')' inside spring config objects.
        # Example: config: {damping: 200)}  ->  config: {damping: 200}
        try:
            code = re.sub(r'(\bconfig\s*:\s*\{[^}]*?)\)(\s*\})', r'\1\2', code)
        except Exception:
            pass

        try:
            code = RenderRemotion._convert_transform_template_literals(code)
        except Exception:
            pass

        # Fix common malformed string concatenation in transforms (non-template literal case)
        try:
            code = RenderRemotion._auto_fix_common_concat_syntax(code)
        except Exception:
            pass

        try:
            code = RenderRemotion._auto_fix_input_range(code)
        except Exception:
            pass

        try:
            code = RenderRemotion._remove_background_color(code)
        except Exception:
            pass

        return code

    @staticmethod
    def _auto_fix_common_tsx_typos(code: str) -> str:
        """Fix small, common TSX typos that frequently break esbuild bundling."""
        if not code:
            return code

        # Fix malformed arrow function parameter list like: (t}) => ...
        # Seen in: easing: (t}) => 1 - Math.pow(1 - t, 3)
        code = re.sub(
            r'\(\s*([A-Za-z_$][\w$]*)\s*\}\s*\)\s*=>',
            r'(\1) =>',
            code,
        )

        # Fix common misspellings for interpolate extrapolation options
        code = code.replace('extrapulateRight', 'extrapolateRight')
        code = code.replace('extrapulateLeft', 'extrapolateLeft')

        # Fix broken imports caused by bad injection logic
        # e.g. import { A } , staticFile } from 'remotion' -> import { A, staticFile } from 'remotion'
        code = re.sub(r'\}\s*,\s*staticFile\s*\}', ', staticFile }', code)
        code = re.sub(r'\}\s*,\s*staticFile\s*,\s*Img\s*\}',
                      ', staticFile, Img }', code)

        return code

    @staticmethod
    def _auto_fix_common_concat_syntax(code: str) -> str:
        """Fix common malformed string concatenations that break esbuild.

        Example observed in the wild (breaks bundling):
        transform: 'translateY(' + (interpolate(...) + ')) + 'px)'

        This function rewrites common translateX/translateY/rotate transform lines
        into a stable concatenation form.
        """
        # 1. Fix interpolate(..., { ... )) -> interpolate(..., { ... })
        # Pattern: interpolate call ending in ) where the last arg is an object but missing }
        try:
            code = re.sub(r'(interpolate\s*\([^)]*\{[^})]*)\)', r'\1})', code)
        except Exception:
            pass

        def _extract_balanced_parens(s: str, start_idx: int) -> str:
            depth = 0
            in_single = False
            in_double = False
            escaped = False
            for j in range(start_idx, len(s)):
                ch = s[j]
                if escaped:
                    escaped = False
                    continue
                if ch == '\\':
                    escaped = True
                    continue
                if ch == "'" and not in_double:
                    in_single = not in_single
                    continue
                if ch == '"' and not in_single:
                    in_double = not in_double
                    continue
                if in_single or in_double:
                    continue
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        return s[start_idx:j + 1]
            return ''

        def _fix_transform_line(line: str) -> str:
            if 'transform' not in line or 'interpolate(' not in line:
                return line
            # Skip template literals handled elsewhere
            if '`' in line:
                return line

            func = None
            unit = None
            if "'translateY('" in line:
                func, unit = 'translateY', 'px'
            elif "'translateX('" in line:
                func, unit = 'translateX', 'px'
            elif "'rotate('" in line:
                func, unit = 'rotate', 'deg'
            else:
                return line

            idx = line.find('interpolate(')
            call = _extract_balanced_parens(line, idx)
            if not call:
                return line

            indent = re.match(r'^\s*', line).group(0)
            trailing_comma = ',' if line.rstrip().endswith(',') else ''
            return f"{indent}transform: '{func}(' + {call} + '{unit})'{trailing_comma}"

        try:
            lines = code.splitlines()
            lines = [_fix_transform_line(ln) for ln in lines]
            code = '\n'.join(lines)
        except Exception:
            pass

        # Fix a common typo introduced by LLM
        try:
            code = re.sub(r'\bfps\s*:\s*FPS\b', 'fps: fps', code)
        except Exception:
            pass

        return code

    @staticmethod
    def _auto_fix_input_range(code: str) -> str:
        """Sort numeric inputRange arrays to satisfy Remotion monotonicity requirement.

        Note: This is a heuristic. It only sorts strictly numeric arrays.
        It does NOT reorder outputRange, which might break animation logic,
        but it fixes the crash. The LLM fix is preferred, but this helps simple cases.
        """

        def _sort_range(match):
            content = match.group(1)
            # Check if it looks like a list of numbers (int or float)
            if not re.match(r'^[\d\.\s,\-]+$', content):
                return match.group(0)
            try:
                nums = [
                    float(x.strip()) for x in content.split(',') if x.strip()
                ]
                # If already sorted, do nothing
                if nums == sorted(nums) and len(nums) == len(set(nums)):
                    return match.group(0)

                # Sort
                sorted_nums = sorted(nums)
                # Deduplicate if needed (Remotion requires strict monotonicity)
                # But changing length breaks outputRange matching.
                # So we just sort. If duplicates exist, it will still crash, but sorting helps [20, 0] -> [0, 20]
                return f'inputRange: [{", ".join(str(n) for n in sorted_nums)}]'
            except Exception:
                return match.group(0)

        # Regex for `inputRange: [...]`
        return re.sub(r'inputRange\s*:\s*\[([^\]]+)\]', _sort_range, code)

    @staticmethod
    def _remove_background_color(code: str) -> str:
        """Remove solid background colors from root styles to ensure transparency."""
        # Remove backgroundColor: 'black', 'white', '#000', etc.
        # We target common patterns.

        # 1. Remove `backgroundColor: 'black'` or similar in style objects
        code = re.sub(
            r'backgroundColor\s*:\s*[\'"](black|white|#000|#000000|#fff|#ffffff)[\'"]\s*,?',
            '', code)

        # 2. Remove `backgroundColor: 'black'` if it's the only prop in a style object? No, too risky.

        return code

    @staticmethod
    def _convert_transform_template_literals(code: str) -> str:
        """Convert `transform: `...`` template literals to string concatenation.

        Handles multi-line template literals and nested `{}` inside `${...}` by using a small scanner
        (instead of fragile regex-only rewriting).
        """

        def _escape_single_quotes(text: str) -> str:
            return text.replace('\\', '\\\\').replace("'", "\\'")

        def _parse_template(template: str) -> str:
            # Turn a template literal body (no backticks) into `'a' + (expr) + 'b'`.
            parts = []
            i = 0
            literal_buf = []

            def flush_literal():
                nonlocal literal_buf
                if literal_buf:
                    parts.append("'"
                                 + _escape_single_quotes(''.join(literal_buf))
                                 + "'")
                    literal_buf = []

            while i < len(template):
                if template.startswith('${', i):
                    flush_literal()
                    i += 2
                    depth = 1
                    expr_buf = []
                    in_str = None
                    escape = False
                    while i < len(template) and depth > 0:
                        ch = template[i]
                        if escape:
                            expr_buf.append(ch)
                            escape = False
                            i += 1
                            continue

                        if in_str is not None:
                            expr_buf.append(ch)
                            if ch == '\\':
                                escape = True
                            elif ch == in_str:
                                in_str = None
                            i += 1
                            continue

                        if ch in ('"', "'"):
                            in_str = ch
                            expr_buf.append(ch)
                            i += 1
                            continue

                        if ch == '{':
                            depth += 1
                            expr_buf.append(ch)
                            i += 1
                            continue
                        if ch == '}':
                            depth -= 1
                            if depth == 0:
                                i += 1
                                break
                            expr_buf.append(ch)
                            i += 1
                            continue

                        expr_buf.append(ch)
                        i += 1

                    expr = ''.join(expr_buf).strip()
                    # Wrap in parentheses to be safe when concatenating.
                    parts.append(f'({expr})' if expr else "''")
                    continue

                literal_buf.append(template[i])
                i += 1

            flush_literal()

            # Join parts: remove empty string literals when possible
            # e.g. '' + (x) -> (x), (x) + '' -> (x)
            joined = ' + '.join(parts)
            joined = joined.replace("'' + ", '')
            joined = joined.replace(" + ''", '')
            return joined

        out = []
        idx = 0
        # Find occurrences of `transform: ` and replace the following template literal.
        while True:
            m = re.search(r'(\btransform\s*:\s*)`', code[idx:])
            if not m:
                out.append(code[idx:])
                break

            start = idx + m.start()
            prefix_end = idx + m.end()  # points right after opening backtick
            out.append(code[idx:start])
            prefix = code[
                start:prefix_end]  # includes `transform: ` + opening backtick

            # Locate closing backtick
            j = prefix_end
            while j < len(code) and code[j] != '`':
                j += 1
            if j >= len(code):
                # Unclosed template literal; bail.
                out.append(code[start:])
                break

            template_body = code[prefix_end:j]
            converted = _parse_template(template_body)
            # Replace prefix `transform: `
            prefix_no_tick = prefix[:-1]  # remove opening backtick
            out.append(prefix_no_tick)
            out.append(converted)
            idx = j + 1  # skip closing backtick

        return ''.join(out)

    @staticmethod
    def _enforce_image_constraints(code: str) -> str:
        """
        [DISABLED - Agentic Approach]
        Previously injecting hard constraints (maxWidth: '90%').
        Now letting LLM decide scaling. If it fails visual check, LLM fixes it.
        """
        return code

    @staticmethod
    def _enforce_layout_safety(code: str) -> str:
        """Enforce basic technical safety (no flickering), but allow LLM layout freedom."""

        # 1. Anti-Flickering: Remove rapid modulo-based opacity/visibility
        # Pattern: `opacity: frame %` or `opacity: (frame %`
        code = re.sub(r'opacity:\s*(\(frame|frame)\s*%',
                      'opacity: 1; // fixed flickering ', code)

        # 2. Universal Overflow Protection
        # Inject overflow: hidden into the root AbsoluteFill to physically cut off out-of-bounds content
        if '<AbsoluteFill' in code:
            if 'style={{' in code:
                # Be careful not to double inject if run multiple times
                if "overflow: 'hidden'" not in code:
                    code = code.replace(
                        '<AbsoluteFill style={{',
                        "<AbsoluteFill style={{ overflow: 'hidden', ", 1)
            else:
                code = code.replace(
                    '<AbsoluteFill',
                    "<AbsoluteFill style={{ overflow: 'hidden' }}", 1)

        # 3. [DISABLED] Aggressive Absolute Positioning Neutralizer
        # We now rely on the Visual Audit loop to catch overlaps, allowing the model
        # to use absolute positioning if it does so correctly (e.g. non-overlapping coordinates).

        return code
