import sys
import os
import json
from typing import List, Union

# Ensure ms-agent package can import this module as external code
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from omegaconf import DictConfig
from ms_agent.agent.base import Agent
from ms_agent.llm import Message
from projects.video_generate.core import workflow as video_workflow


class VideoAgent(Agent):
    """A thin wrapper that dispatches to original workflow functions.
    It preserves all original prompts/logic. We only adapt to ms-agent's CodeAgent loading via code_file.
    """

    def __init__(self, config: DictConfig, tag: str, trust_remote_code: bool = False, **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        # work_dir for intermediates
        self.work_dir = os.path.join(self.config.local_dir, 'output') if getattr(self.config, 'local_dir', None) else os.getcwd()
        os.makedirs(self.work_dir, exist_ok=True)
        self.meta_path = os.path.join(self.work_dir, "meta.json")
        # animation mode: auto (default) or human (manual animation workflow)
        import os as _os
        self.animation_mode = _os.environ.get('MS_ANIMATION_MODE', 'auto').strip().lower() or 'auto'
        print(f"[video_agent] Animation mode: {self.animation_mode}")

    def _generate_script(self, topic: str) -> str:
        """
        Generates a video script for the given topic using the original project's logic.
        """
        print(f"[video_agent] Generating script for topic: {topic}")
        script = video_workflow.generate_script(topic)
        print(f"[video_agent] Script generated with length: {len(script)}")
        
        # Create a per-topic directory (preserve original behavior and later path-based topic usage)
        def _safe_topic(name: str) -> str:
            import re
            safe = re.sub(r'[^\w\u4e00-\u9fff\-_]', '_', name or 'topic')
            safe = safe[:50] if len(safe) > 50 else safe
            return safe or 'topic'

        topic_dir = os.path.join(self.work_dir, _safe_topic(topic))
        os.makedirs(topic_dir, exist_ok=True)

        # Save the script to a file to pass to the next step
        script_path = os.path.join(topic_dir, "script.txt")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)
        # persist topic for later steps
        try:
            with open(os.path.join(topic_dir, 'meta.json'), 'w', encoding='utf-8') as mf:
                json.dump({"topic": topic}, mf, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[video_agent] Failed to write meta.json: {e}")
            
        return script_path

    def _generate_assets_from_script(self, script_path: str, topic: str) -> str:
        """
        Parses the script, generates TTS, animations, and subtitles.
        This function is a wrapper around the core logic in workflow.py.
        """
        print("[video_agent] Starting asset generation from script...")
        
        with open(script_path, 'r', encoding='utf-8') as f:
            script = f.read()

        # Resolve topic from meta if available to keep consistent with original query
        try:
            meta_path = os.path.join(os.path.dirname(script_path), 'meta.json')
            if os.path.exists(meta_path):
                meta = json.load(open(meta_path, 'r', encoding='utf-8'))
                topic = meta.get('topic', topic)
        except Exception as e:
            print(f"[video_agent] Failed to read topic from meta.json: {e}")

        # Use the script's directory as the output directory for this topic
        full_output_dir = os.path.dirname(script_path)
        os.makedirs(full_output_dir, exist_ok=True)

        # 1. Parse script into segments
        print("[video_agent] Parsing script into segments...")
        segments = video_workflow.parse_structured_content(script)
        
        # Further split long text segments
        final_segments = []
        for segment in segments:
            if segment['type'] == 'text' and len(segment['content']) > 100:
                subsegments = video_workflow.split_text_by_punctuation(segment['content'])
                for subseg_dict in subsegments:
                    if subseg_dict['content'].strip():
                        final_segments.append({
                            'content': subseg_dict['content'].strip(),
                            'type': 'text',
                            'parent_segment': segment
                        })
            else:
                final_segments.append(segment)
        segments = final_segments
        print(f"[video_agent] Script parsed into {len(segments)} segments.")

        # 2. Generate assets for each segment
        asset_paths = {
            "audio_paths": [],
            "foreground_paths": [],
            "subtitle_paths": [],
            "illustration_paths": [],
            "subtitle_segments_list": []
        }

        tts_dir = os.path.join(full_output_dir, "audio")
        os.makedirs(tts_dir, exist_ok=True)
        
        subtitle_dir = os.path.join(full_output_dir, "subtitles")
        os.makedirs(subtitle_dir, exist_ok=True)

        # Prepare illustration paths list aligned to segments
        illustration_paths: List[str] = []

        for i, segment in enumerate(segments):
            print(f"[video_agent] Processing segment {i+1}/{len(segments)}: {segment['type']}")
            
            # Clean content to avoid issues with markers
            tts_text = video_workflow.clean_content(segment.get('content', ''))

            # Generate TTS
            audio_path = os.path.join(tts_dir, f"segment_{i+1}.mp3")
            if tts_text:
                if video_workflow.edge_tts_generate(tts_text, audio_path):
                    segment['audio_duration'] = video_workflow.get_audio_duration(audio_path)
                else:
                    video_workflow.create_silent_audio(audio_path, duration=3.0)
                    segment['audio_duration'] = 3.0
            else:
                video_workflow.create_silent_audio(audio_path, duration=2.0)
                segment['audio_duration'] = 2.0
            asset_paths["audio_paths"].append(audio_path)

            # Generate Animation (only for non-text types)
            if segment['type'] != 'text' and self.animation_mode != 'human':
                manim_code = video_workflow.generate_manim_code(
                    content=video_workflow.clean_content(segment['content']),
                    content_type=segment['type'],
                    scene_number=i + 1,
                    audio_duration=segment.get('audio_duration', 8.0),
                    main_theme=topic,
                    context_segments=segments,
                    segment_index=i,
                    total_segments=segments
                )
                video_path = None
                if manim_code:
                    scene_name = f"Scene{i+1}"
                    scene_dir = os.path.join(full_output_dir, f"scene_{i+1}")
                    video_path = video_workflow.render_manim_scene(manim_code, scene_name, scene_dir)
                asset_paths["foreground_paths"].append(video_path)
            else:
                # In human mode, skip auto manim rendering (leave placeholders)
                asset_paths["foreground_paths"].append(None)

            # Initialize placeholders for subtitles; will fill after loop
            illustration_paths.append(None)
            asset_paths["subtitle_paths"].append(None)
            asset_paths["subtitle_segments_list"].append([])

        # Generate illustrations for text segments (mirrors original logic)
        try:
            text_segments = [seg for seg in segments if seg.get('type') == 'text']
            if text_segments:
                illustration_prompts_path = os.path.join(full_output_dir, 'illustration_prompts.json')
                if os.path.exists(illustration_prompts_path):
                    illustration_prompts = json.load(open(illustration_prompts_path, 'r', encoding='utf-8'))
                else:
                    illustration_prompts = video_workflow.generate_illustration_prompts([seg['content'] for seg in text_segments])
                    json.dump(illustration_prompts, open(illustration_prompts_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

                images_dir = os.path.join(full_output_dir, 'images')
                os.makedirs(images_dir, exist_ok=True)
                image_paths_path = os.path.join(images_dir, 'image_paths.json')
                if os.path.exists(image_paths_path):
                    image_paths = json.load(open(image_paths_path, 'r', encoding='utf-8'))
                else:
                    image_paths = video_workflow.generate_images(illustration_prompts, output_dir=full_output_dir)
                    # move to images folder for consistent paths
                    for i, img_path in enumerate(image_paths):
                        if os.path.exists(img_path):
                            new_path = os.path.join(images_dir, f'illustration_{i+1}.png' if img_path.lower().endswith('.png') else f'illustration_{i+1}.jpg')
                            try:
                                os.replace(img_path, new_path)
                            except Exception:
                                try:
                                    import shutil
                                    shutil.move(img_path, new_path)
                                except Exception:
                                    new_path = img_path
                            image_paths[i] = new_path
                    json.dump(image_paths, open(image_paths_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

                fg_out_dir = os.path.join(images_dir, 'output_black_only')
                os.makedirs(fg_out_dir, exist_ok=True)
                # process background removal if needed
                if len([f for f in os.listdir(fg_out_dir) if f.lower().endswith('.png')]) < len(image_paths):
                    video_workflow.keep_only_black_for_folder(images_dir, fg_out_dir)

                # map illustrations back to segment indices
                text_idx = 0
                for idx, seg in enumerate(segments):
                    if seg.get('type') == 'text':
                        if text_idx < len(image_paths):
                            transparent_path = os.path.join(fg_out_dir, f'illustration_{text_idx+1}.png')
                            if os.path.exists(transparent_path):
                                illustration_paths[idx] = transparent_path
                            else:
                                illustration_paths[idx] = image_paths[text_idx]
                            text_idx += 1
                        else:
                            illustration_paths[idx] = None
                    else:
                        illustration_paths[idx] = None
            else:
                illustration_paths = [None] * len(segments)
        except Exception as e:
            print(f"[video_agent] Illustration generation failed: {e}")
            illustration_paths = [None] * len(segments)

        # Attach illustration paths to asset_paths
        asset_paths["illustration_paths"] = illustration_paths

        # Generate bilingual subtitles
        def _split_subtitles(text: str, max_chars: int = 30) -> List[str]:
            import re
            sentences = re.split(r'([。！？；，、])', text)
            subs, cur = [], ""
            for s in sentences:
                if not s.strip():
                    continue
                test = cur + s
                if len(test) <= max_chars:
                    cur = test
                else:
                    if cur:
                        subs.append(cur.strip())
                    cur = s
            if cur.strip():
                subs.append(cur.strip())
            return subs

        for i, seg in enumerate(segments):
            try:
                if seg.get('type') != 'text':
                    zh_text = seg.get('explanation', '') or seg.get('content', '')
                    parts = _split_subtitles(zh_text, max_chars=30)
                    img_list = []
                    for idx_p, part in enumerate(parts):
                        sub_en = video_workflow.translate_text_to_english(part)
                        temp_path, _h = video_workflow.create_bilingual_subtitle_image(
                            zh_text=part,
                            en_text=sub_en,
                            width=1720,
                            height=120
                        )
                        if temp_path and os.path.exists(temp_path):
                            final_sub_path = os.path.join(subtitle_dir, f"bilingual_subtitle_{i+1}_{idx_p+1}.png")
                            try:
                                os.replace(temp_path, final_sub_path)
                            except Exception:
                                import shutil
                                shutil.move(temp_path, final_sub_path)
                            img_list.append(final_sub_path)
                    asset_paths["subtitle_segments_list"][i] = img_list
                    asset_paths["subtitle_paths"][i] = img_list[0] if img_list else None
                else:
                    zh_text = seg.get('content', '')
                    en_text = video_workflow.translate_text_to_english(zh_text)
                    temp_path, _h = video_workflow.create_bilingual_subtitle_image(
                        zh_text=zh_text,
                        en_text=en_text,
                        width=1720,
                        height=120
                    )
                    if temp_path and os.path.exists(temp_path):
                        final_sub_path = os.path.join(subtitle_dir, f"bilingual_subtitle_{i+1}.png")
                        try:
                            os.replace(temp_path, final_sub_path)
                        except Exception:
                            import shutil
                            shutil.move(temp_path, final_sub_path)
                        asset_paths["subtitle_paths"][i] = final_sub_path
                        asset_paths["subtitle_segments_list"][i] = [final_sub_path]
            except Exception as e:
                print(f"[video_agent] Subtitle generation failed at segment {i+1}: {e}")

        # Save all necessary info for the next step
        asset_info = {
            "topic": topic,
            "output_dir": full_output_dir,
            "segments": segments,
            "asset_paths": asset_paths,
            "animation_mode": self.animation_mode
        }
        asset_info_path = os.path.join(full_output_dir, "asset_info.json")
        with open(asset_info_path, 'w', encoding='utf-8') as f:
            json.dump(asset_info, f, ensure_ascii=False, indent=2)

        # 兼容工作室的完整合成：同时输出 segments.json
        try:
            with open(os.path.join(full_output_dir, 'segments.json'), 'w', encoding='utf-8') as sf:
                json.dump(segments, sf, ensure_ascii=False, indent=2)
        except Exception as _e:
            print(f"[video_agent] 写入 segments.json 失败: {_e}")

        # In human mode, drop a short README to guide manual studio
        if self.animation_mode == 'human':
            readme_path = os.path.join(full_output_dir, 'HUMAN_README.txt')
            try:
                with open(readme_path, 'w', encoding='utf-8') as rf:
                    rf.write(
                        "本目录为人工动画模式生成的素材预备目录\n"
                        "- 已生成脚本、语音、插画、字幕与占位前景（无自动动画）\n"
                        "- 下一步：进入互动动画工作室制作每个动画片段\n\n"
                        "启动命令示例：\n"
                        "# 先确保将 ms-agent 目录加入 PYTHONPATH 环境变量\n"
                        "# PowerShell:\n"
                        "# $env:PYTHONPATH=\"{}\"\n"
                        "# 然后以模块方式启动工作室：\n"
                        "python -m projects.video_generate.core.human_animation_studio \"{}\"\n".format(
                            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')),  # ms-agent 根目录
                            full_output_dir
                        )
                    )
            except Exception as _e:
                print(f"[video_agent] Failed to write HUMAN_README: {_e}")

        print(f"[video_agent] Asset generation complete. Info saved to {asset_info_path}")
        return asset_info_path

    def _synthesize_video(self, asset_info_path: str) -> Union[str, None]:
        """
        Composes the final video from the generated assets.
        """
        print(f"[video_agent] Starting final video synthesis from {asset_info_path}...")

        with open(asset_info_path, 'r', encoding='utf-8') as f:
            asset_info = json.load(f)

        topic = asset_info["topic"]
        full_output_dir = asset_info["output_dir"]
        segments = asset_info["segments"]
        asset_paths = asset_info["asset_paths"]

        # Generate background
        background_path = video_workflow.create_manual_background(title_text=topic, output_dir=full_output_dir, topic=topic)

        # In human mode, auto-generate placeholder foreground clips for non-text segments
        if self.animation_mode == 'human':
            try:
                from projects.video_generate.core.human_animation_studio import AnimationStudio
                from projects.video_generate.core.animation_production_modes import AnimationProductionMode
                print("[video_agent] Human mode: generating placeholder clips for non-text segments...")
                studio = AnimationStudio(full_output_dir, workflow_instance=video_workflow)
                task_manager = studio.task_manager
                placeholder_gen = studio.placeholder_generator
                fg = asset_paths.get("foreground_paths", [])
                for i, seg in enumerate(segments):
                    if seg.get('type') != 'text' and (i >= len(fg) or not fg[i]):
                        audio_duration = seg.get('audio_duration', 8.0)
                        task_id = task_manager.create_task(
                            segment_index=i+1,
                            content=seg.get('content',''),
                            content_type=seg.get('type'),
                            mode=AnimationProductionMode.HUMAN_CONTROLLED,
                            audio_duration=audio_duration
                        )
                        task = task_manager.get_task(task_id)
                        placeholder_path = os.path.join(full_output_dir, f"scene_{i+1}_placeholder.mov")
                        placeholder_video = placeholder_gen.create_placeholder(task, placeholder_path)
                        # ensure list capacity
                        while len(asset_paths["foreground_paths"]) <= i:
                            asset_paths["foreground_paths"].append(None)
                        asset_paths["foreground_paths"][i] = placeholder_video if placeholder_video else None
                        if placeholder_video:
                            print(f"[video_agent] Placeholder generated for segment {i+1}: {placeholder_video}")
                        else:
                            print(f"[video_agent] Placeholder generation failed for segment {i+1}")
            except Exception as e:
                print(f"[video_agent] Human mode placeholder generation failed: {e}")

        # Compose final video (human mode generates a preview with placeholders)
        final_name = "preview_with_placeholders.mp4" if self.animation_mode == 'human' else "final_video.mp4"
        final_video_path = os.path.join(full_output_dir, final_name)

        composed_path = video_workflow.compose_final_video(
            background_path=background_path,
            foreground_paths=asset_paths["foreground_paths"],
            audio_paths=asset_paths["audio_paths"],
            subtitle_paths=asset_paths["subtitle_paths"],
            illustration_paths=asset_paths["illustration_paths"],
            segments=segments,
            output_path=final_video_path,
            subtitle_segments_list=asset_paths["subtitle_segments_list"]
        )

        if composed_path and os.path.exists(composed_path):
            print(f"[video_agent] Final video successfully composed at: {composed_path}")
            return composed_path
        else:
            print("[video_agent] Final video composition failed.")
            return None

    async def run(self, inputs: Union[str, List[Message]], **kwargs) -> List[Message]:
        """Dispatch by self.tag to keep ChainWorkflow simple.
        Inputs is the query string for first step, else pass file paths between steps via return messages.
        """
        # Normalize inputs
        if isinstance(inputs, list) and inputs and hasattr(inputs[0], 'content'):
            in_text = inputs[0].content
        else:
            in_text = inputs if isinstance(inputs, str) else ''

        result_path = None
        if self.tag == 'generate_script':
            topic = in_text
            result_path = self._generate_script(topic)
        elif self.tag == 'generate_assets':
            # inputs should be the path from previous step
            # fallback: if inputs looks like a path, use it; else assume default script.txt
            script_path = in_text if os.path.exists(in_text) else os.path.join(self.work_dir, 'script.txt')
            # We need topic; reuse the folder name or query text if available
            topic = os.path.basename(os.path.dirname(script_path)) or 'topic'
            result_path = self._generate_assets_from_script(script_path, topic)
        elif self.tag == 'synthesize_video':
            asset_info_path = in_text if os.path.exists(in_text) else os.path.join(self.work_dir, 'asset_info.json')
            result_path = self._synthesize_video(asset_info_path)
        else:
            print(f"[video_agent] Unknown tag: {self.tag}")

        # Return as a single Message list so next agent receives a text content
        out_text = result_path or ''
        return [Message(role='assistant', content=out_text)]
