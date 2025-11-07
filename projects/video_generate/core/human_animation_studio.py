import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional

import json

from .animation_production_modes import (AnimationProductionMode,
                                         AnimationStatus, AnimationTask,
                                         AnimationTaskManager,
                                         PlaceholderGenerator)

# 添加当前目录到路径，确保能导入其他模块
# current_dir = os.path.dirname(os.path.abspath(__file__))
# if current_dir not in sys.path:
#     sys.path.insert(0, current_dir)

# 导入自动错误处理函数
try:
    from .workflow import clean_llm_code_output, fix_manim_error_with_llm
except Exception as e:
    print('Warning: 无法导入或初始化 workflow 模块的错误处理函数，将使用基础处理')
    print(f'原因: {e}')

    def clean_llm_code_output(code):
        """基础的代码清理函数 - 增强版"""
        if not code:
            return code

        print(f'[DEBUG] 清理前代码长度: {len(code)} 字符')
        print(f'[DEBUG] 清理前代码预览: {code[:200]}...')

        code = code.strip()

        # 检查是否包含完整的代码块
        if '```python' in code:
            start_idx = code.find('```python')
            if start_idx != -1:
                code = code[start_idx + 9:]  # 移除 ```python

                # 查找结束标记
                end_idx = code.find('```')
                if end_idx != -1:
                    code = code[:end_idx]  # 移除结尾的 ```
                else:
                    print('[DEBUG] 警告：未找到代码块结束标记，可能被截断')
        elif code.startswith('```'):
            code = code[3:]
            if code.endswith('```'):
                code = code[:-3]

        code = code.strip()
        print(f'[DEBUG] 清理后代码长度: {len(code)} 字符')
        print(f'[DEBUG] 清理后代码预览: {code[:200]}...')

        # 检查代码完整性
        if 'class Scene12(Scene):' not in code:
            print('[DEBUG] 警告：代码中未找到Scene12类定义')
        if 'def construct(self):' not in code:
            print('[DEBUG] 警告：代码中未找到construct方法')
        if code.count('{') != code.count('}'):
            print('[DEBUG] 警告：大括号不匹配')

        return code

    def fix_manim_error_with_llm(code,
                                 error_message,
                                 content_type,
                                 scene_name,
                                 enable_layout_optimization: bool = False):
        """基础的错误修复函数"""
        print('基础错误修复模式，无法使用高级LLM修复')
        return None


# Try to import robust code cleaning from workflow; provide fallback
try:
    from .workflow import clean_llm_code_output as _global_clean_llm_code_output
except Exception:
    _global_clean_llm_code_output = None


def _clean_code_safely(code):
    if not code:
        return code
    try:
        if _global_clean_llm_code_output:
            return _global_clean_llm_code_output(code)
    except Exception:
        pass
    # Fallback lightweight cleaner
    text = code.strip()
    if text.startswith('```python'):
        text = text[9:]
    if text.startswith('```'):
        text = text[3:]
    if text.endswith('```'):
        text = text[:-3]
    # Normalize common fullwidth punctuation that breaks Python parsing
    text = text.replace('：', ':').replace('，', ',').replace('；', ';')
    # Remove stray backticks
    return text.strip().strip('`').strip()


class AnimationStudio:
    """人工动画制作工作室"""

    def __init__(self, project_dir: str, workflow_instance=None):
        self.project_dir = project_dir
        self.workflow = workflow_instance
        self.task_manager = AnimationTaskManager(project_dir)
        self.placeholder_generator = PlaceholderGenerator()

        # 创建工作目录
        self.studio_dir = os.path.join(project_dir, 'animation_studio')
        self.drafts_dir = os.path.join(self.studio_dir, 'drafts')
        self.previews_dir = os.path.join(self.studio_dir, 'previews')
        self.finals_dir = os.path.join(self.studio_dir, 'finals')

        for dir_path in [
                self.studio_dir, self.drafts_dir, self.previews_dir,
                self.finals_dir
        ]:
            os.makedirs(dir_path, exist_ok=True)

    def start_human_session(self, task_id):
        """开始人工制作会话"""
        task = self.task_manager.get_task(task_id)
        if not task:
            print(f'任务 {task_id} 不存在')
            return None

        print('\n[动画制作] 开始动画制作会话')
        print(f'任务ID: {task_id}')
        print(f'内容: {task.content}')
        print(f'类型: {task.content_type}')
        print(f'时长: {task.audio_duration}秒')

        # 更新任务状态
        self.task_manager.update_task_status(task_id, AnimationStatus.DRAFT)

        return HumanAnimationSession(task, self)

    def generate_preview_with_background(self, task, manim_code):
        """生成预览视频，包含背景、字幕、音频"""
        try:
            print('正在生成完整预览视频（背景+字幕+音频）...')

            scene_name = f'Scene{task.segment_index}'
            scene_dir = os.path.join(self.drafts_dir,
                                     f'scene_{task.segment_index}')
            os.makedirs(scene_dir, exist_ok=True)

            # 1. 使用简化的manim渲染，避免调用workflow的重试逻辑
            animation_path = self._simple_render_animation(
                manim_code, scene_name, scene_dir, attempt_num=0)

            if not animation_path or not os.path.exists(animation_path):
                print('动画渲染失败')
                return None

            print(f'动画渲染成功: {animation_path}')

            # 2. 创建完整预览（背景+字幕+音频） - 使用时间戳确保新文件
            import datetime
            timestamp = datetime.datetime.now().strftime('%H%M%S')
            preview_path = os.path.join(
                self.previews_dir, f'{task.task_id}_preview_{timestamp}.mp4')

            # 清理可能存在的同名旧文件
            if os.path.exists(preview_path):
                try:
                    os.remove(preview_path)
                except:  # noqa
                    pass

            success = self._create_complete_preview(task, animation_path,
                                                    preview_path)

            if success:
                task.preview_video_path = preview_path
                self.task_manager.save_tasks()
                print(f'完整预览视频生成成功: {preview_path}')
                return preview_path
            else:
                print('预览合成失败')
                return None

        except Exception as e:
            print(f'生成预览视频失败: {e}')
            return None

    def _split_long_text_for_subtitles(self, text, max_chars_per_subtitle=50):
        """将长文本智能分割成多个字幕片段"""
        import re

        if len(text) <= max_chars_per_subtitle:
            return [text]

        # 按句子分割
        sentences = re.split(r'([。！？；，、])', text)
        subtitle_parts = []
        current_part = ''

        for sentence in sentences:
            if not sentence.strip():
                continue
            test_part = current_part + sentence
            if len(test_part) <= max_chars_per_subtitle:
                current_part = test_part
            else:
                if current_part:
                    subtitle_parts.append(current_part.strip())
                current_part = sentence

        if current_part.strip():
            subtitle_parts.append(current_part.strip())

        return subtitle_parts

    def _validate_manim_code(self, code, scene_name):
        """验证Manim代码的完整性，并自动修复透明背景设置"""
        try:
            modified_code = code

            # 确保导入BLACK常量
            if 'BLACK' in code and 'from manim import' in code:
                import_line = ''
                for line in code.split('\n'):
                    if line.strip().startswith('from manim import'):
                        import_line = line.strip()
                        break

                if import_line and 'BLACK' not in import_line:
                    print('[DEBUG] 导入语句中缺少BLACK常量，自动添加')
                    # 在导入语句中添加BLACK
                    if import_line.endswith('*'):
                        # 如果是from manim import *，不需要修改
                        pass
                    else:
                        # 添加BLACK到导入列表
                        new_import = import_line.rstrip() + ', BLACK'
                        modified_code = modified_code.replace(
                            import_line, new_import)
                        print('[DEBUG] 已更新导入语句包含BLACK常量')

            # 自动添加透明背景设置（如果缺少）
            if 'camera.background_color' not in code and 'background_color' not in code:
                print('[DEBUG] 代码缺少透明背景设置，自动添加')
                # 在 def construct(self): 后面添加透明背景设置
                construct_pattern = 'def construct(self):'
                if construct_pattern in code:
                    construct_index = modified_code.find(construct_pattern)
                    insert_pos = modified_code.find('\n', construct_index) + 1
                    background_line = '        self.camera.background_color = BLACK\n        \n'
                    modified_code = modified_code[:
                                                  insert_pos] + background_line + modified_code[
                                                      insert_pos:]
                    print('[DEBUG] 已自动添加透明背景设置')

            # 基本结构检查
            required_patterns = [
                f'class {scene_name}', 'def construct', 'from manim import',
                'self.play', 'self.wait'
            ]

            missing_patterns = []
            for pattern in required_patterns:
                if pattern not in modified_code:
                    missing_patterns.append(pattern)

            if missing_patterns:
                print(f'[DEBUG] 代码缺少必要结构: {missing_patterns}')
                # 不是致命错误，继续执行，但记录警告

            # 检查代码块完整性
            if modified_code.count('{{') != modified_code.count('}}'):
                print('[DEBUG] 大括号不匹配')
                return False, modified_code

            if modified_code.count('(') != modified_code.count(')'):
                print('[DEBUG] 括号不匹配')
                return False, modified_code

            # 检查Python语法
            try:
                compile(modified_code, '<string>', 'exec')
                print('[DEBUG] 代码语法检查通过')
                return True, modified_code
            except SyntaxError as e:
                print(f'[DEBUG] 代码语法错误: {e}')
                return False, modified_code

        except Exception as e:
            print(f'[DEBUG] 代码验证异常: {e}')
            return False, code

    def _simple_render_animation(self,
                                 manim_code,
                                 scene_name,
                                 output_dir,
                                 attempt_num=0):
        """简单的manim渲染，不使用重试循环"""
        import subprocess
        import os
        import time

        try:
            print(f'[DEBUG] 开始渲染动画，代码长度: {len(manim_code)} 字符')
            print(f'[DEBUG] 代码预览: {manim_code[:200]}...')

            # 验证代码完整性并自动修复
            is_valid, fixed_code = self._validate_manim_code(
                manim_code, scene_name)
            if not is_valid:
                print('[DEBUG] 代码验证失败，代码不完整或有语法错误')
                return None

            # 使用修复后的代码
            manim_code = fixed_code

            # 创建输出目录
            os.makedirs(output_dir, exist_ok=True)

            # 保存代码到scene文件夹，保留历史记录
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            code_filename = f'{scene_name}_attempt_{attempt_num}_{timestamp}.py'
            code_filepath = os.path.join(output_dir, code_filename)

            # 保存代码文件
            with open(code_filepath, 'w', encoding='utf-8') as f:
                f.write(manim_code)
            print(f'[DEBUG] 代码已保存到: {code_filepath}')

            # 使用glob查找并删除所有相关的.mov文件
            import glob
            for pattern in [
                    os.path.join(output_dir, '**', '*.mov'),
                    os.path.join(output_dir, f'{scene_name}.mov'),
            ]:
                for old_file in glob.glob(pattern, recursive=True):
                    try:
                        os.remove(old_file)
                        print(f'[DEBUG] 删除旧视频文件: {old_file}')
                    except Exception as e:
                        print(f'[DEBUG] 无法删除旧文件 {old_file}: {e}')

            # 使用保存的代码文件进行渲染
            print(f'[DEBUG] 使用保存的代码文件进行渲染: {code_filepath}')

            # 获取代码文件的基本名称（不含扩展名）
            code_name = os.path.splitext(os.path.basename(code_filepath))[0]

            # 构建manim命令 - 使用更强的缓存禁用
            cmd = [
                'manim',
                code_filepath,
                scene_name,
                '-qm',
                '--disable_caching',
                '--transparent',
                '--media_dir',
                output_dir,
                '--format',
                'mov',
                '--flush_cache'  # 强制刷新缓存
            ]

            print(f"[DEBUG] 执行manim命令: {' '.join(cmd)}")

            # 记录渲染开始时间
            render_start_time = time.time()
            print(f'[DEBUG] 渲染开始时间: {time.ctime(render_start_time)}')

            # 执行渲染
            process = subprocess.run(
                cmd, capture_output=True, text=False, timeout=120)

            # 处理编码问题
            try:
                stderr = process.stderr.decode(
                    'utf-8', errors='ignore') if process.stderr else ''
            except:  # noqa
                try:
                    stderr = process.stderr.decode(
                        'gbk', errors='ignore') if process.stderr else ''
                except:  # noqa
                    stderr = str(process.stderr) if process.stderr else ''

            if process.returncode == 0:
                print('[DEBUG] Manim渲染成功')

                # 查找生成的视频文件 - manim通常创建 media/videos/[code_name]/720p30/[scene_name].mov
                possible_paths = [
                    os.path.join(output_dir, f'{scene_name}.mov'),
                    os.path.join(output_dir, 'videos', code_name, '720p30',
                                 f'{scene_name}.mov'),
                    os.path.join(output_dir, 'videos', code_name,
                                 'medium_quality_720p30', f'{scene_name}.mov'),
                ]

                # 递归查找所有.mov文件
                for root, dirs, files in os.walk(output_dir):
                    for file in files:
                        if file.endswith('.mov') and scene_name in file:
                            found_path = os.path.join(root, file)

                            # 检查文件修改时间确保是新生成的
                            file_mtime = os.path.getmtime(found_path)
                            if file_mtime >= render_start_time - 60:  # 1分钟内的文件认为是新的
                                print(
                                    f'[DEBUG] 找到新视频文件: {found_path} (修改时间: {time.ctime(file_mtime)})'
                                )
                                # 保持MOV格式以保留透明通道，不进行格式转换
                                return found_path
                            else:
                                print(
                                    f'[DEBUG] 发现旧视频文件: {found_path} (修改时间: {time.ctime(file_mtime)}) - 继续查找'
                                )

                # 如果没找到新文件，尝试预设路径并检查时间
                for path in possible_paths:
                    if os.path.exists(path):
                        file_mtime = os.path.getmtime(path)
                        if file_mtime >= render_start_time - 60:
                            print(
                                f'[DEBUG] 在预设路径找到新文件: {path} (修改时间: {time.ctime(file_mtime)})'
                            )
                            # 保持MOV格式以保留透明通道，不进行格式转换
                            return path
                        else:
                            print(
                                f'[DEBUG] 预设路径文件过旧: {path} (修改时间: {time.ctime(file_mtime)})'
                            )

                print(f'[DEBUG] 未找到视频文件，输出目录内容: {os.listdir(output_dir)}')
                return None
            else:
                print(f'Manim渲染失败 (返回码: {process.returncode})')
                print(f'stderr: {stderr[:500]}')
                return None

        except Exception as e:
            print(f'渲染过程异常: {e}')
            import traceback
            traceback.print_exc()
            return None

        return None

    def _create_complete_preview(self, task, animation_path, preview_path):
        """创建完整的预览视频（背景+动画+字幕+音频）- 采用主流程的合成逻辑"""
        try:
            # 导入主流程的合成功能
            from .workflow import (create_manual_background,
                                   create_bilingual_subtitle_image,
                                   edge_tts_generate, get_audio_duration)
            import cv2
            import numpy as np
            from moviepy.editor import VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip

            print('创建项目背景...')
            # 1. 创建背景图
            background_path = create_manual_background(
                title_text='AI知识科普预览',
                output_dir=os.path.dirname(preview_path),
                topic=task.content[:20]
                + '...' if len(task.content) > 20 else task.content)

            print('生成音频...')
            # 2. 生成音频
            audio_path = os.path.join(
                os.path.dirname(preview_path),
                f'preview_audio_{task.task_id}.mp3')
            edge_tts_generate(task.content, audio_path, 'female')

            print('创建字幕...')
            # 3. 创建字幕 - 支持长文本分段
            subtitle_segments = self._split_long_text_for_subtitles(
                task.content, max_chars_per_subtitle=60)
            subtitle_paths = []

            print(f'[字幕] 将文本分成 {len(subtitle_segments)} 段')

            for i, segment in enumerate(subtitle_segments):
                segment_subtitle_path, _ = create_bilingual_subtitle_image(
                    segment, '', 1720, 120)
                subtitle_paths.append(segment_subtitle_path)
                print(f'[字幕] 生成第 {i+1} 段字幕: {segment[:30]}...')

            print(f'字幕文件数量: {len(subtitle_paths)}')

            print('合成最终视频...')
            # 4. 获取音频时长和动画时长
            audio_duration = get_audio_duration(audio_path) if os.path.exists(
                audio_path) else task.audio_duration or 10.0

            # 获取动画时长作为基准
            animation_duration = None
            if animation_path and os.path.exists(animation_path):
                try:
                    # 优先尝试不使用透明通道获取时长
                    try:
                        temp_clip = VideoFileClip(animation_path)
                        animation_duration = temp_clip.duration
                        temp_clip.close()
                        print(f'动画原始时长: {animation_duration:.1f}秒')
                    except Exception:  # noqa
                        # 如果失败，尝试使用透明通道
                        try:
                            temp_clip = VideoFileClip(
                                animation_path, has_mask=True)
                            animation_duration = temp_clip.duration
                            temp_clip.close()
                            print(f'动画原始时长: {animation_duration:.1f}秒（带透明通道）')
                        except Exception as mask_error:
                            print(f'获取动画时长失败: {mask_error}')
                except Exception as e:
                    print(f'获取动画时长失败: {e}')

            # 确定最终视频时长：取动画时长和音频时长的最大值
            final_duration = max(animation_duration or 0, audio_duration)
            print(
                f'最终视频时长: {final_duration:.1f}秒 (动画: {animation_duration:.1f}秒, 音频: {audio_duration:.1f}秒)'
            )

            # 5. 准备视频剪辑
            video_clips = []

            # 背景层
            if background_path and os.path.exists(background_path):
                bg_clip = ImageClip(background_path, duration=final_duration)
                bg_clip = bg_clip.resize((1920, 1080))
                video_clips.append(bg_clip)
                print('添加背景层')

            # 动画层 - 使用主流程的透明处理逻辑（保持透明背景）
            if animation_path and os.path.exists(animation_path):
                try:
                    print(f'[DEBUG] 加载动画文件: {animation_path}')

                    # 方案1：主流程方式，使用 has_mask=True 来保持透明背景
                    try:
                        animation_clip = VideoFileClip(
                            animation_path, has_mask=True)
                        print('[DEBUG] 成功加载动画文件（带透明通道）')

                    except Exception as mask_error:
                        print(f'[DEBUG] 透明通道加载失败: {mask_error}')
                        # 方案2：不使用透明通道，但仍然保持动画效果
                        try:
                            animation_clip = VideoFileClip(animation_path)
                            print('[DEBUG] 成功加载动画文件（无透明通道）')
                        except Exception as no_mask_error:
                            print(f'[DEBUG] 普通加载也失败: {no_mask_error}')
                            # 方案3：跳过动画层
                            raise Exception('所有动画加载方式都失败')

                    # 获取动画原始尺寸并居中缩放
                    original_w, original_h = animation_clip.size
                    available_w, available_h = 1920, 800  # 留出字幕空间
                    scale_w = available_w / original_w
                    scale_h = available_h / original_h
                    scale = min(scale_w, scale_h, 1.0)

                    if scale < 1.0:
                        new_w = int(original_w * scale)
                        new_h = int(original_h * scale)
                        animation_clip = animation_clip.resize((new_w, new_h))

                    # 动画时长处理：动画短的话就让它播放完，不循环
                    if animation_clip.duration < final_duration:
                        print(
                            f'动画时长 {animation_clip.duration:.1f}秒 < 最终时长 {final_duration:.1f}秒，动画播放完后保持最后一帧'
                        )
                        # 不循环，只是设置duration让动画播放完后保持最后帧
                        animation_clip = animation_clip.set_duration(
                            final_duration)
                    else:
                        print(f'动画时长足够，裁剪到 {final_duration:.1f}秒')
                        animation_clip = animation_clip.set_duration(
                            final_duration)

                    animation_clip = animation_clip.set_position(
                        ('center', 'center'))
                    video_clips.append(animation_clip)
                    print('添加动画层（透明处理）')

                except Exception as animation_error:
                    print(f'[DEBUG] 动画层处理失败: {animation_error}')
                    print('[DEBUG] 跳过动画层，继续处理其他层')

            # 字幕层 - 支持多段字幕的时间分段显示
            try:
                if subtitle_paths and len(subtitle_paths) > 0:
                    n_segments = len(subtitle_paths)
                    segment_duration = final_duration / n_segments

                    print(
                        f'[字幕合成] 处理 {n_segments} 段字幕，每段时长: {segment_duration:.1f}秒'
                    )

                    for i, segment_subtitle_path in enumerate(subtitle_paths):
                        if segment_subtitle_path and os.path.exists(
                                segment_subtitle_path):
                            try:
                                from PIL import Image
                                subtitle_img = Image.open(
                                    segment_subtitle_path)
                                subtitle_w, subtitle_h = subtitle_img.size

                                # 每段字幕显示指定时长
                                subtitle_clip = ImageClip(
                                    segment_subtitle_path,
                                    duration=segment_duration)
                                subtitle_clip = subtitle_clip.resize(
                                    (subtitle_w, subtitle_h))

                                # 设置字幕位置和开始时间
                                subtitle_y = 850  # 主流程使用的字幕Y坐标
                                subtitle_clip = subtitle_clip.set_position(
                                    ('center', subtitle_y))
                                subtitle_clip = subtitle_clip.set_start(
                                    i * segment_duration)

                                video_clips.append(subtitle_clip)
                                print(
                                    f'[字幕合成] 添加第 {i+1}/{n_segments} 段字幕 '
                                    f'(时间: {i * segment_duration:.1f}s - {(i+1) * segment_duration:.1f}s)'
                                )

                            except Exception as e:
                                print(f'[字幕合成] 第 {i+1} 段字幕处理失败: {e}')
                        else:
                            print(
                                f'[字幕合成] 第 {i+1} 段字幕文件不存在: {segment_subtitle_path}'
                            )
                else:
                    print('[字幕合成] 没有字幕文件，跳过字幕层')

            except Exception as e:
                print(f'字幕层处理失败: {e}')
                import traceback
                traceback.print_exc()

            # 合成所有视频层
            if video_clips:
                final_clip = CompositeVideoClip(video_clips, size=(1920, 1080))
                print('视频层合成完成')
            else:
                print('没有有效的视频层')
                return False

            # 添加音频
            if os.path.exists(audio_path):
                audio_clip = AudioFileClip(audio_path)

                # 处理音频时长匹配
                if audio_clip.duration < final_duration:
                    # 如果音频太短，使用静音补全（不循环）
                    from moviepy.editor import AudioClip, concatenate_audioclips
                    silence_duration = final_duration - audio_clip.duration
                    silence = AudioClip(
                        lambda t: [0, 0],
                        duration=silence_duration).set_fps(44100)
                    audio_clip = concatenate_audioclips([audio_clip, silence])
                    print(f'音频补全静音以匹配视频时长: {final_duration:.1f}秒')
                elif audio_clip.duration > final_duration:
                    # 如果音频太长，裁剪
                    audio_clip = audio_clip.subclip(0, final_duration)
                    print(f'音频已裁剪以匹配视频时长: {final_duration:.1f}秒')

                final_clip = final_clip.set_audio(audio_clip)
                print('添加音频轨道')

            # 输出最终视频 - 对透明视频特殊处理
            try:
                final_clip.write_videofile(
                    preview_path,
                    codec='libx264',
                    audio_codec='aac',
                    fps=30,  # 提高帧率以获得更流畅的视频
                    verbose=False,
                    logger=None)
            except Exception as write_error:
                print(f'[DEBUG] 标准写入失败: {write_error}')
                # 尝试强制移除透明通道并重新合成
                try:
                    print('[DEBUG] 尝试重新加载动画（强制无透明通道）...')

                    # 重新构建视频层，不使用透明通道
                    new_video_clips = []

                    # 背景层
                    if background_path and os.path.exists(background_path):
                        bg_clip = ImageClip(
                            background_path, duration=final_duration)
                        bg_clip = bg_clip.resize((1920, 1080))
                        new_video_clips.append(bg_clip)

                    # 动画层（强制无透明通道）
                    if animation_path and os.path.exists(animation_path):
                        try:
                            animation_clip_no_mask = VideoFileClip(
                                animation_path)  # 不使用has_mask

                            # 调整尺寸
                            original_w, original_h = animation_clip_no_mask.size
                            available_w, available_h = 1920, 800  # 留出字幕空间
                            scale_w = available_w / original_w
                            scale_h = available_h / original_h
                            scale = min(scale_w, scale_h, 1.0)

                            if scale < 1.0:
                                new_w = int(original_w * scale)
                                new_h = int(original_h * scale)
                                animation_clip_no_mask = animation_clip_no_mask.resize(
                                    (new_w, new_h))

                            # 调整时长（不循环，保持最后帧）
                            animation_clip_no_mask = animation_clip_no_mask.set_duration(
                                final_duration)

                            animation_clip_no_mask = animation_clip_no_mask.set_position(
                                ('center', 'center'))
                            new_video_clips.append(animation_clip_no_mask)
                            print('[DEBUG] 重新添加动画层（无透明通道）')

                        except Exception as no_mask_error:
                            print(f'[DEBUG] 无透明通道加载也失败: {no_mask_error}')

                    # 重新添加字幕层
                    if subtitle_paths and len(subtitle_paths) > 0:
                        n_segments = len(subtitle_paths)
                        segment_duration = final_duration / n_segments

                        for i, segment_subtitle_path in enumerate(
                                subtitle_paths):
                            if segment_subtitle_path and os.path.exists(
                                    segment_subtitle_path):
                                try:
                                    from PIL import Image
                                    subtitle_img = Image.open(
                                        segment_subtitle_path)
                                    subtitle_w, subtitle_h = subtitle_img.size

                                    subtitle_clip = ImageClip(
                                        segment_subtitle_path,
                                        duration=segment_duration)
                                    subtitle_clip = subtitle_clip.resize(
                                        (subtitle_w, subtitle_h))
                                    subtitle_y = 850
                                    subtitle_clip = subtitle_clip.set_position(
                                        ('center', subtitle_y))
                                    subtitle_clip = subtitle_clip.set_start(
                                        i * segment_duration)

                                    new_video_clips.append(subtitle_clip)

                                except Exception as subtitle_error:
                                    print(
                                        f'[DEBUG] 字幕 {i+1} 重新添加失败: {subtitle_error}'
                                    )

                    # 重新合成并输出
                    fallback_clip = CompositeVideoClip(
                        new_video_clips, size=(1920, 1080))

                    # 添加音频
                    if os.path.exists(audio_path):
                        audio_clip = AudioFileClip(audio_path)
                        if audio_clip.duration > final_duration:
                            audio_clip = audio_clip.subclip(0, final_duration)
                        fallback_clip = fallback_clip.set_audio(audio_clip)

                    # 输出备用版本
                    fallback_clip.write_videofile(
                        preview_path,
                        codec='libx264',
                        audio_codec='aac',
                        fps=30,
                        verbose=False,
                        logger=None)
                    print('[DEBUG] 备用方案成功生成视频')

                except Exception as fallback_error:
                    print(f'[DEBUG] 备用方案也失败: {fallback_error}')
                    raise write_error  # 重新抛出原始错误

            print('完整预览视频生成成功')
            return True

        except Exception as e:
            print(f'合成预览视频失败: {e}')
            import traceback
            traceback.print_exc()

            # 降级处理：直接复制动画文件
            try:
                import shutil
                shutil.copy2(animation_path, preview_path)
                print('使用简化预览（仅动画）')
                return True
            except:  # noqa
                return False

    def _render_manim_animation(self, task, manim_code):
        """渲染Manim动画"""
        scene_name = f'Scene{task.segment_index}'
        scene_file = os.path.join(self.drafts_dir, f'{task.task_id}.py')

        # 写入代码文件
        cleaned_code = _clean_code_safely(manim_code)
        with open(scene_file, 'w', encoding='utf-8') as f:
            f.write(cleaned_code)

        # 渲染动画
        try:
            # Ensure a safe ASCII-only media dir to avoid Unicode path issues
            media_dir = os.path.join(self.studio_dir, 'manim_media')
            os.makedirs(media_dir, exist_ok=True)

            base_name = f'{task.task_id}'
            quality_flag = '-qm'
            quality_dir = '720p30'

            cmd = [
                'manim', 'render', scene_file, scene_name, '--format=mov',
                '--transparent', quality_flag, '--media_dir', media_dir,
                '--output_file', base_name
            ]

            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'

            print(
                f"[DEBUG] _render_manim_animation: 执行命令: {' '.join(str(x) for x in cmd)}"
            )
            print(
                f'[DEBUG] _render_manim_animation: 期望产物路径: {media_dir}/videos/[{base_name}]/720p30/{base_name}.mov'
            )

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=False,
                timeout=180,
                env=env,
                cwd=self.drafts_dir)

            try:
                stderr_txt = (result.stderr or b'').decode(
                    'utf-8', errors='ignore')
            except UnicodeDecodeError:
                stderr_txt = (result.stderr or b'').decode(
                    'gbk', errors='ignore')

            try:
                stdout_txt = (result.stdout or b'').decode(
                    'utf-8', errors='ignore')
            except UnicodeDecodeError:
                stdout_txt = (result.stdout or b'').decode(
                    'gbk', errors='ignore')

            module_name = os.path.splitext(os.path.basename(scene_file))[0]
            expected_dir = os.path.join(media_dir, 'videos', module_name,
                                        quality_dir)
            expected_path = os.path.join(expected_dir, f'{base_name}.mov')
            print(f'[DEBUG] _render_manim_animation: 实际产物路径: {expected_path}')

            if result.returncode == 0 and os.path.exists(expected_path):
                final_output = os.path.join(self.drafts_dir,
                                            f'{task.task_id}.mov')
                try:
                    import shutil
                    os.makedirs(self.drafts_dir, exist_ok=True)
                    shutil.copy2(expected_path, final_output)
                    print(
                        f'[DEBUG] _render_manim_animation: 复制到: {final_output}'
                    )
                    return final_output
                except Exception as e:
                    print(f'[DEBUG] _render_manim_animation: 复制失败: {e}')
                    return expected_path if os.path.exists(
                        expected_path) else None
            else:
                err_msg = stderr_txt or stdout_txt or f'Manim退出码: {result.returncode}'
                print(f'Manim渲染失败: {err_msg[:1000]}')
                return None

        except subprocess.TimeoutExpired:
            print('Manim渲染超时')
            return None
        except Exception as e:
            print(f'Manim渲染异常: {e}')
            return None

    def _get_project_background(self):
        """获取项目背景图"""
        # 优先使用主流程生成的背景（包括 title_*.png 或 unified_background*.png）
        try:
            candidates = []
            # 常规命名
            candidates.extend([
                os.path.join(self.project_dir, 'background.png'),
                os.path.join(self.project_dir, 'images', 'background.png'),
                os.path.join(self.project_dir, 'unified_background.png')
            ])
            # 主流程常见命名（title_*.png）
            for fname in os.listdir(self.project_dir):
                if fname.lower().startswith(
                        'title_') and fname.lower().endswith('.png'):
                    candidates.append(os.path.join(self.project_dir, fname))
            # 兼容可能的统一背景命名
            for fname in os.listdir(self.project_dir):
                if fname.lower().startswith(
                        'unified_background') and fname.lower().endswith(
                            '.png'):
                    candidates.append(os.path.join(self.project_dir, fname))

            # 选择最新的存在的背景图
            existing = [p for p in candidates if os.path.exists(p)]
            if existing:
                existing.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                return existing[0]
        except Exception:
            pass

        # 如果没找到，使用主流程样式自动生成一个与“旧逻辑一致”的背景
        try:
            topic = None
            # 优先从 meta.json 或 asset_info.json 读取主题
            meta_path = os.path.join(self.project_dir, 'meta.json')
            asset_info_path = os.path.join(self.project_dir, 'asset_info.json')
            if os.path.exists(meta_path):
                try:
                    import json as _json
                    meta = _json.load(open(meta_path, 'r', encoding='utf-8'))
                    topic = meta.get('topic')
                except Exception:
                    topic = None
            if not topic and os.path.exists(asset_info_path):
                try:
                    import json as _json
                    info = _json.load(
                        open(asset_info_path, 'r', encoding='utf-8'))
                    topic = info.get('topic')
                except Exception:
                    topic = None

            # 调用主流程的背景生成（左上角/右上角文字 + 中部横线 + 自定义字体）
            try:
                from .workflow import create_manual_background
                bg_path = create_manual_background(
                    title_text=topic or 'AI知识科普',
                    output_dir=self.project_dir,
                    topic=topic)
                if bg_path and os.path.exists(bg_path):
                    return bg_path
            except Exception:
                pass

            # 兜底：仍返回一个简单默认背景
            return self._create_default_background()
        except Exception:
            return self._create_default_background()

    def _create_default_background(self):
        """创建默认背景"""
        from PIL import Image, ImageDraw

        bg_path = os.path.join(self.studio_dir, 'default_background.png')

        img = Image.new('RGB', (1280, 720), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # 添加简单装饰
        draw.rectangle([50, 50, 1230, 670], outline=(200, 200, 200), width=2)

        img.save(bg_path)
        return bg_path

    def _compose_preview_video(self, animation_path, background_path,
                               output_path):
        """合成预览视频"""
        try:
            cmd = [
                'ffmpeg',
                '-y',
                '-i',
                background_path,
                '-i',
                animation_path,
                '-filter_complex',
                '[0:v][1:v]overlay=0:0[v]',
                '-map',
                '[v]',
                '-t',
                '10',  # 限制预览时长
                '-c:v',
                'libx264',
                '-pix_fmt',
                'yuv420p',
                output_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0 and os.path.exists(output_path)

        except Exception as e:
            print(f'合成预览视频失败: {e}')
            return False


class HumanAnimationSession:
    """人工动画制作会话"""

    def __init__(self, task, studio):
        self.task = task
        self.studio = studio
        self.conversation_history = []

    def chat_with_llm(self, user_message):
        """与LLM对话生成内容"""
        # 构建对话上下文
        context = f"""你是专业的Manim动画制作助手。用户正在制作以下动画：

任务信息:
- 内容: {self.task.content}
- 类型: {self.task.content_type}
- 时长: {self.task.audio_duration}秒

对话历史:
{chr(10).join(self.conversation_history[-5:])}  # 最近5轮对话

用户消息: {user_message}

请提供专业的建议或生成相应的内容。如果用户要求生成Manim代码，请确保代码完整、可执行，并符合布局最佳实践。"""

        try:
            # 直接导入并使用workflow模块的LLM接口
            try:
                from .workflow import modai_model_request
                print(f'[DEBUG] 发送给LLM的消息长度: {len(context)} 字符')
                print(f'[DEBUG] 用户消息: {user_message}')

                response = modai_model_request(
                    context,
                    max_tokens=8000,  # 增加token限制以支持复杂代码
                    temperature=0.7)

                print(
                    f'[DEBUG] LLM响应长度: {len(response) if response else 0} 字符')
                print(
                    f"[DEBUG] LLM响应内容预览: {response[:200] if response else 'None'}..."
                )

                # 检查响应是否被截断
                response_is_truncated = False
                if response and len(response) > 0:
                    if not response.strip().endswith(
                            '```') and '```python' in response:
                        print('[DEBUG] 警告：LLM响应可能被截断，未找到结束标记')
                        response_is_truncated = True
                    if response.count('```') % 2 != 0:
                        print('[DEBUG] 警告：代码块标记不匹配，可能截断')
                        response_is_truncated = True
                    print(
                        f'[DEBUG] 响应结尾: ...{response[-100:] if len(response) > 100 else response}'
                    )

                # 如果响应被截断，尝试重新请求完整代码
                if response_is_truncated and '```python' in response:
                    print('[DEBUG] 检测到代码截断，尝试重新生成完整代码...')
                    retry_context = f'{context}\n\n注意：上次响应被截断了，请重新生成完整的Manim代码，确保包含完整的类定义和所有必要的方法。'

                    retry_response = modai_model_request(
                        retry_context,
                        max_tokens=10000,  # 增加更多token
                        temperature=0.5  # 降低温度提高稳定性
                    )

                    if retry_response and len(retry_response) > len(response):
                        print(
                            f'[DEBUG] 重试成功，获得更长的响应: {len(retry_response)} vs {len(response)} 字符'
                        )
                        response = retry_response
                    else:
                        print('[DEBUG] 重试未能改善，继续使用原响应')

                return response

            except ImportError as e:
                print(f'[DEBUG] 导入workflow失败: {e}')
                # 如果无法导入workflow，使用模拟响应
                response = f"好的，我理解你的需求。针对'{self.task.content}'的{self.task.content_type}类型动画，我建议..."
            except Exception as e:
                print(f'[DEBUG] LLM调用失败: {e}')
                response = f'抱歉，LLM调用失败: {e}'

            # 记录对话
            self.conversation_history.append(f'用户: {user_message}')
            self.conversation_history.append(f'助手: {response}')

            return response

        except Exception as e:
            print(f'LLM对话失败: {e}')
            return '抱歉，暂时无法响应你的请求，请稍后再试。'

    def generate_script_with_llm(self, requirements=''):
        """让LLM生成文案"""
        prompt = f"""请为以下内容生成适合动画展示的文案：

原始内容: {self.task.content}
内容类型: {self.task.content_type}
动画时长: {self.task.audio_duration}秒
特殊要求: {requirements}

请生成简洁、生动、适合口播的文案，确保内容准确且有趣味性。"""

        script = self.chat_with_llm(prompt)
        self.task.script = script
        self.studio.task_manager.save_tasks()
        return script

    def generate_manim_code_with_llm(self, script=None, requirements=''):
        """让LLM生成Manim代码"""
        script = script or self.task.script or self.task.content

        prompt = f"""请为以下内容生成Manim动画代码：

文案内容: {script}
内容类型: {self.task.content_type}
动画时长: {self.task.audio_duration}秒
特殊要求: {requirements}

请生成完整的Manim代码，类名为Scene{self.task.segment_index}，确保：
1. 代码完整可执行
2. 布局合理，无重叠问题
3. 动画效果生动有趣
4. 符合时长要求
5. 使用透明背景"""

        code = self.chat_with_llm(prompt)
        self.task.manim_code = code
        self.studio.task_manager.save_tasks()
        return code

    def improve_code_with_feedback(self, feedback):
        """基于反馈改进Manim代码"""
        if not self.task.manim_code:
            print('没有现有代码可改进')
            return ''

        print(f'[DEBUG] 收到反馈: {feedback}')
        print(f'[DEBUG] 当前代码长度: {len(self.task.manim_code)} 字符')

        prompt = f"""请基于以下反馈改进Manim动画代码：

当前代码:
{self.task.manim_code}

用户反馈: {feedback}

请根据反馈修改代码，确保：
1. 解决用户提到的所有问题
2. 保持代码的完整性和可执行性
3. 不破坏原有的良好特性
4. 优化动画效果和布局
5. 类名仍为Scene{self.task.segment_index}"""

        print('[DEBUG] 发送改进请求给LLM...')
        print(f'[DEBUG] 发送给LLM的消息长度: {len(prompt)} 字符')
        improved_code = self.chat_with_llm(prompt)

        # 比较改进前后的代码变化
        original_length = len(self.task.manim_code)
        improved_length = len(improved_code)
        original_code = self.task.manim_code  # 保存原始代码用于比较

        print('[DEBUG] 代码变化分析:')
        print(f'   原始代码长度: {original_length} 字符')
        print(f'   改进后长度: {improved_length} 字符')
        print(f'   变化量: {improved_length - original_length:+d} 字符')

        # 检查是否有实质性改变
        if abs(improved_length - original_length) < 50:
            print('代码变化较小，但仍应用改进')
        else:
            print('代码有显著变化')

        # 始终应用改进后的代码，即使变化很小
        self.task.manim_code = improved_code
        self.task.revision_count += 1
        self.studio.task_manager.save_tasks()

        print(f'[DEBUG] 改进后代码长度: {improved_length} 字符')
        print(f'[DEBUG] 修订次数: {self.task.revision_count}')

        # 显示代码变化的关键信息 - 使用原始代码进行比较
        if 'scale' in improved_code.lower(
        ) and 'scale' not in original_code.lower():
            print('添加了缩放效果')
        if 'rotate' in improved_code.lower(
        ) and 'rotate' not in original_code.lower():
            print('添加了旋转效果')
        if 'gradient' in improved_code.lower(
        ) or 'color_gradient' in improved_code.lower():
            print('添加了颜色渐变效果')
        if improved_code.count('self.play') > original_code.count('self.play'):
            added_animations = improved_code.count(
                'self.play') - original_code.count('self.play')
            print(f'增加了 {added_animations} 个动画序列')

        return improved_code

    def create_preview(self, manim_code=None):
        """创建预览视频"""
        # 优先使用传入的代码，如果没有传入则使用任务中的代码
        if manim_code:
            code = manim_code
            print(f'[DEBUG] 使用传入的代码进行渲染 (长度: {len(manim_code)} 字符)')
        else:
            code = self.task.manim_code
            print(f'[DEBUG] 使用任务中的代码进行渲染 (长度: {len(code) if code else 0} 字符)')

        if not code:
            print('没有可用的Manim代码')
            return None

        print('正在生成预览视频...')
        preview_path = self.studio.generate_preview_with_background(
            self.task, code)

        if preview_path:
            print(f'预览视频已生成: {preview_path}')
            self.studio.task_manager.update_task_status(
                self.task.task_id, AnimationStatus.PREVIEW)
            return preview_path
        else:
            print('预览视频生成失败')
            return None

    def submit_feedback(self, feedback):
        """提交反馈意见"""
        print(f'[DEBUG] 提交反馈: {feedback}')
        print(f'[DEBUG] 任务ID: {self.task.task_id}')

        self.studio.task_manager.add_human_feedback(self.task.task_id,
                                                    feedback)
        print(f'反馈已记录: {feedback}')

        # 检查反馈是否真正保存了
        task = self.studio.task_manager.get_task(self.task.task_id)
        if hasattr(task, 'human_feedback') and task.human_feedback:
            print(f'[DEBUG] 当前任务的反馈记录数量: {len(task.human_feedback)}')
            print(
                f"[DEBUG] 最新反馈: {task.human_feedback[-1] if task.human_feedback else 'None'}"
            )
        else:
            print('[DEBUG] 警告：反馈可能未正确保存')

    def approve_animation(self):
        """批准动画"""
        if not self.task.preview_video_path or not os.path.exists(
                self.task.preview_video_path):
            print('没有可批准的预览视频')
            return False

        # 目标最终透明动画路径（只接受透明的前景动画 .mov）
        final_path = os.path.join(
            self.studio.finals_dir,
            f'scene_{self.task.segment_index}_final.mov')

        # 1) 优先复用草稿期已渲染的透明 MOV；找不到则在批准时重新渲染一份透明 MOV
        def _find_transparent_mov():
            import glob
            candidates = []

            # a. 专用渲染产物（_render_manim_animation 会复制到 drafts 根目录）
            cand1 = os.path.join(self.studio.drafts_dir,
                                 f'{self.task.task_id}.mov')
            if os.path.exists(cand1):
                candidates.append(cand1)

            # b. drafts/scene_{i}/videos/**/Scene{i}.mov（Manim标准产物）
            scene_dir = os.path.join(self.studio.drafts_dir,
                                     f'scene_{self.task.segment_index}')
            if os.path.isdir(scene_dir):
                pattern = os.path.join(scene_dir, 'videos', '**',
                                       f'Scene{self.task.segment_index}*.mov')
                for p in glob.glob(pattern, recursive=True):
                    candidates.append(p)

            # c. drafts/scene_{i}/**/Scene{i}.mov（兜底）
            if os.path.isdir(scene_dir):
                pattern2 = os.path.join(
                    scene_dir, '**', f'*Scene{self.task.segment_index}*.mov')
                for p in glob.glob(pattern2, recursive=True):
                    candidates.append(p)

            # d. drafts 下所有包含 Scene{i} 的 mov（全局兜底）
            pattern_any = os.path.join(
                self.studio.drafts_dir, '**',
                f'*Scene{self.task.segment_index}*.mov')
            for p in glob.glob(pattern_any, recursive=True):
                candidates.append(p)

            # 去重并按修改时间降序
            unique = {
                os.path.abspath(p)
                for p in candidates if os.path.exists(p)
            }
            sorted_by_mtime = sorted(
                unique, key=lambda p: os.path.getmtime(p), reverse=True)
            print(f'[DEBUG] approve_animation: 所有候选透明MOV: {sorted_by_mtime}')
            if sorted_by_mtime:
                print(
                    f'[DEBUG] approve_animation: 选用透明MOV: {sorted_by_mtime[0]}'
                )
            return sorted_by_mtime[0] if sorted_by_mtime else None

        src_mov = _find_transparent_mov()
        if not src_mov:
            # 没有找到透明前景，尝试用当前代码重新渲染一份透明 MOV
            if not self.task.manim_code:
                print('未找到透明动画文件，且任务缺少代码，无法重新渲染')
                return False
            print('未找到现有透明动画，正在重新渲染透明前景 MOV…')
            src_mov = self.studio._render_manim_animation(
                self.task, self.task.manim_code)

        if not src_mov or not os.path.exists(src_mov):
            print('生成或查找透明动画失败，无法批准为最终动画')
            return False

        try:
            import shutil
            os.makedirs(self.studio.finals_dir, exist_ok=True)
            shutil.copy2(src_mov, final_path)
            self.task.final_video_path = final_path
            # 标记完成：此处保存的是“透明前景”，最终成片仍由合成流程 compose_final_video 统一完成
            self.studio.task_manager.update_task_status(
                self.task.task_id, AnimationStatus.COMPLETED)
            self.studio.task_manager.save_tasks()
            print(f'动画已批准（保存透明前景）: {final_path}')
            return True
        except Exception as e:
            print(f'保存最终动画失败: {e}')
            return False

    def get_session_summary(self):
        """获取会话摘要"""
        return {
            'task_id': self.task.task_id,
            'content': self.task.content,
            'status': self.task.status.value,
            'revision_count': self.task.revision_count,
            'conversation_history': self.conversation_history,
            'has_script': bool(self.task.script),
            'has_code': bool(self.task.manim_code),
            'has_preview': bool(self.task.preview_video_path),
            'has_final': bool(self.task.final_video_path)
        }


class InteractiveAnimationStudio:
    """交互式动画制作工作室 - 命令行界面"""

    def __init__(self, project_dir, workflow_instance=None):
        self.studio = AnimationStudio(project_dir, workflow_instance)
        self.current_session: Optional[HumanAnimationSession] = None
        self.project_dir = project_dir
        self.workflow_instance = workflow_instance  # 存储workflow实例以获取内容信息
        # 如果没有任务，尝试从资产信息自动引导创建任务
        try:
            if not self.studio.task_manager.tasks:
                self._bootstrap_tasks_from_assets()
        except Exception as _e:
            print(f'[DEBUG] 启动时自动创建任务失败: {_e}')

    def start_interactive_mode(self):
        """启动交互模式"""
        print('\n[动画] 欢迎使用交互式动画制作工作室！')
        print('=' * 50)

        while True:
            self.show_main_menu()
            choice = input('请选择操作 (输入数字): ').strip()

            if choice == '1':
                self.list_pending_tasks()
            elif choice == '2':
                self.start_task_session()
            elif choice == '3':
                self.review_completed_tasks()
            elif choice == '4':
                self.show_project_status()
            elif choice == '5':
                self.continue_session()
            elif choice == '6':
                self.manual_merge_videos()
            elif choice == '0':
                print('正在退出工作室...')
                break
            else:
                print('无效选择，请重新输入')

        def _bootstrap_tasks_from_assets(self):
            """当没有任务时，从项目目录中的资产信息自动创建待制作任务"""
            import os

            asset_info_path = os.path.join(self.project_dir, 'asset_info.json')
            segments_path = os.path.join(self.project_dir, 'segments.json')

            segments = None
            audio_paths = None
            if os.path.exists(asset_info_path):
                try:
                    with open(asset_info_path, 'r', encoding='utf-8') as f:
                        info = json.load(f)
                    segments = info.get('segments')
                    ap = info.get('asset_paths') or {}
                    audio_paths = ap.get('audio_paths')
                except Exception as e:
                    print(f'[DEBUG] 读取 asset_info.json 失败: {e}')
            elif os.path.exists(segments_path):
                try:
                    with open(segments_path, 'r', encoding='utf-8') as f:
                        segments = json.load(f)
                except Exception as e:
                    print(f'[DEBUG] 读取 segments.json 失败: {e}')

            if not segments:
                print('当前没有待制作的动画任务')
                return

            created = 0
            for i, seg in enumerate(segments):
                seg_type = seg.get('type', 'text')
                if seg_type == 'text':
                    continue  # 文本段无需制作前景动画

                # 音频时长优先取 seg 字段，否则从文件推断
                duration = seg.get('audio_duration')
                if duration is None and audio_paths and i < len(audio_paths):
                    try:
                        path = audio_paths[i]
                        if path and os.path.exists(path):
                            from .workflow import get_audio_duration
                            duration = get_audio_duration(path)
                    except Exception:
                        duration = None
                if duration is None:
                    duration = 8.0

                try:
                    self.studio.task_manager.create_task(
                        segment_index=i + 1,
                        content=seg.get('content', ''),
                        content_type=seg_type,
                        mode=AnimationProductionMode.HUMAN_CONTROLLED,
                        audio_duration=duration)
                    created += 1
                except Exception as e:
                    print(f'[DEBUG] 创建任务失败(段 {i+1}): {e}')

            if created > 0:
                print(f'已从资产信息创建 {created} 个待制作任务')

    def show_main_menu(self):
        """显示主菜单"""
        print('\n' + '=' * 50)
        print('[动画] 动画制作工作室')
        print('=' * 50)
        print('1. 查看待制作任务')
        print('2. 开始制作动画')
        print('3. 查看已完成任务')
        print('4. 查看项目状态')
        print('5. 继续现有会话')
        print('6. 合并已完成视频')
        print('0. 退出')

    def list_pending_tasks(self):
        """列出待制作任务"""
        # 首先清理重复任务
        self._cleanup_duplicate_tasks()

        pending_tasks = self.studio.task_manager.get_tasks_by_status(
            AnimationStatus.PENDING)
        draft_tasks = self.studio.task_manager.get_tasks_by_status(
            AnimationStatus.DRAFT)
        preview_tasks = self.studio.task_manager.get_tasks_by_status(
            AnimationStatus.PREVIEW)

        all_active_tasks = pending_tasks + draft_tasks + preview_tasks

        if not all_active_tasks:
            print('\n 当前没有待制作的动画任务')
            return

        print(f'\n 待制作任务 ({len(all_active_tasks)} 个):')
        print('-' * 80)

        for i, task in enumerate(all_active_tasks, 1):
            status_emoji = {
                AnimationStatus.PENDING: '⏳',
                AnimationStatus.DRAFT: '📝',
                AnimationStatus.PREVIEW: '👁️',
                AnimationStatus.REVISION: '🔄'
            }.get(task.status, '❓')

            print(
                f'{i}. {status_emoji} [{task.task_id}] ({task.content_type})')
            print(
                f"   内容: {task.content[:80]}{'...' if len(task.content) > 80 else ''}"
            )
            print(
                f'   状态: {task.status.value} | 时长: {task.audio_duration}s | 修订: {task.revision_count}次'
            )
            print()

    def _cleanup_duplicate_tasks(self):
        """清理重复任务"""
        task_manager = self.studio.task_manager
        tasks_by_segment = {}

        # 按段落和类型分组
        for task_id, task in list(task_manager.tasks.items()):
            key = (task.segment_index, task.content_type)
            if key not in tasks_by_segment:
                tasks_by_segment[key] = []
            tasks_by_segment[key].append(task)

        # 移除重复任务，保留最新的或状态最高的
        removed_count = 0
        for key, task_list in tasks_by_segment.items():
            if len(task_list) > 1:
                # 按状态优先级和创建时间排序
                status_priority = {
                    AnimationStatus.COMPLETED: 5,
                    AnimationStatus.APPROVED: 4,
                    AnimationStatus.PREVIEW: 3,
                    AnimationStatus.DRAFT: 2,
                    AnimationStatus.PENDING: 1,
                    AnimationStatus.FAILED: 0
                }

                task_list.sort(
                    key=lambda t:
                    (status_priority.get(t.status, 0), t.creation_time or ''),
                    reverse=True)

                # 保留第一个任务，移除其他的
                for task in task_list[1:]:
                    del task_manager.tasks[task.task_id]
                    removed_count += 1

        if removed_count > 0:
            print(f'已清理 {removed_count} 个重复任务')
            task_manager.save_tasks()

    def start_task_session(self):
        """开始任务制作会话"""
        # 获取所有活跃任务
        pending_tasks = self.studio.task_manager.get_tasks_by_status(
            AnimationStatus.PENDING)
        draft_tasks = self.studio.task_manager.get_tasks_by_status(
            AnimationStatus.DRAFT)
        preview_tasks = self.studio.task_manager.get_tasks_by_status(
            AnimationStatus.PREVIEW)

        all_tasks = pending_tasks + draft_tasks + preview_tasks

        if not all_tasks:
            print('\n 没有可制作的任务')
            return

        # 显示任务列表
        print('\n选择要制作的任务:')
        for i, task in enumerate(all_tasks, 1):
            print(
                f'{i}. [{task.task_id}] {task.content[:50]}... ({task.status.value})'
            )

        try:
            choice = int(input('\n输入任务编号: ')) - 1
            if 0 <= choice < len(all_tasks):
                selected_task = all_tasks[choice]
                self.current_session = self.studio.start_human_session(
                    selected_task.task_id)
                if self.current_session:
                    self.run_animation_session()
            else:
                print('无效的任务编号')
        except ValueError:
            print('请输入有效数字')

    def run_animation_session(self):
        """运行动画制作会话"""
        if not self.current_session:
            return

        task = self.current_session.task
        print(f'\n[动画] 开始制作动画: {task.content[:50]}...')

        while True:
            # 检查会话是否仍然活跃
            if not self.current_session:
                print('会话已结束，返回主菜单')
                break

            try:
                self.show_session_menu()
                choice = input('\n选择操作: ').strip()

                if choice == '1':
                    self.generate_script_interactive()
                elif choice == '2':
                    self.generate_code_interactive()
                elif choice == '3':
                    self.create_preview_interactive()
                elif choice == '4':
                    self.chat_with_assistant()
                elif choice == '5':
                    self.submit_feedback_interactive()
                elif choice == '6':
                    self.approve_animation_interactive()
                elif choice == '7':
                    self.show_session_status()
                elif choice == '0':
                    print('退出当前会话')
                    break
                else:
                    print('无效选择')

            except KeyboardInterrupt:
                print('\n会话被中断')
                break

    def show_session_menu(self):
        """显示会话菜单"""
        if not self.current_session:
            print('当前没有活跃的会话')
            return

        task = self.current_session.task
        print('\n' + '=' * 60)
        print(f'[动画] 动画制作会话 - {task.task_id}')
        print(f'内容: {task.content}')
        print(f'状态: {task.status.value}')
        print('=' * 60)
        print('1. 生成/修改文案')
        print('2. 生成/修改动画代码')
        print('3. 创建预览视频')
        print('4. 与AI助手对话')
        print('5. 提交反馈意见')
        print('6. 批准动画')
        print('7. 查看会话状态')
        print('0. 退出会话')

    def generate_script_interactive(self):
        """交互式生成文案"""
        if not self.current_session:
            print('当前没有活跃的会话')
            return

        task = self.current_session.task

        print('\n 文案生成')
        print(f'当前内容: {task.content}')

        if task.script:
            print(f'当前文案: {task.script}')
            if input('是否重新生成? (y/n): ').lower() != 'y':
                return

        requirements = input('请输入特殊要求 (可选): ').strip()

        print('正在生成文案...')
        try:
            script = self.current_session.generate_script_with_llm(
                requirements)
            print('\n 文案生成完成:')
            print('-' * 40)
            print(script)
            print('-' * 40)

            if input('是否满意此文案? (y/n): ').lower() == 'y':
                print('文案已保存')
            else:
                feedback = input('请输入修改意见: ')
                print(f'反馈已记录: {feedback}')

        except Exception as e:
            print(f'文案生成失败: {e}')

    def generate_code_interactive(self):
        """交互式生成代码 - 集成自动错误处理和重试机制"""
        if not self.current_session:
            print('当前没有活跃的会话')
            return

        task = self.current_session.task

        print('\n 动画代码生成')

        if task.manim_code:
            print('当前已有动画代码')
            print('选择操作:')
            print('1. AI重新生成代码')
            print('2. 手动输入代码')
            print('3. 基于反馈改进当前代码')
            print('4. 取消')

            choice = input('请选择 (1-4): ').strip()
            if choice == '4':
                return
            elif choice == '2':
                self.manual_code_input()
                return
            elif choice == '3':
                self.improve_code_with_feedback()
                return
            elif choice != '1':
                print('无效选择，返回')
                return
        else:
            print('选择代码生成方式:')
            print('1. AI自动生成代码')
            print('2. 手动输入代码')

            choice = input('请选择 (1-2): ').strip()
            if choice == '2':
                self.manual_code_input()
                return
            elif choice != '1':
                print('无效选择，返回')
                return

        script = task.script or task.content
        requirements = input('请输入动画要求 (可选): ').strip()

        # 自动代码生成和修复循环，最多20次尝试
        max_attempts = 20
        attempt = 0

        print(f'\n 开始自动代码生成和渲染流程 (最多 {max_attempts} 次尝试)...')

        while attempt < max_attempts:
            attempt += 1
            print(f'\n 第 {attempt} 次尝试...')

            try:
                # 生成代码
                print('AI正在生成代码...')
                code = self.current_session.generate_manim_code_with_llm(
                    script, requirements)

                if not code or len(code.strip()) < 50:
                    print('生成的代码过短，重试...')
                    requirements += '\n\n请生成完整的Manim动画代码，确保包含所有必要的元素。'
                    continue

                # 清理代码中的markdown格式
                cleaned_code = clean_llm_code_output(code)
                print(f'代码生成完成 ({len(cleaned_code)} 字符)')

                # 询问是否查看代码（仅首次或用户主动要求）
                if attempt == 1 and input('是否查看代码? (y/n): ').lower() == 'y':
                    print('-' * 60)
                    print(cleaned_code)
                    print('-' * 60)

                # 自动渲染预览，内置重试机制
                print('\n 正在自动渲染预览视频...')
                preview_result = self.render_code_preview(cleaned_code)

                if preview_result['success']:
                    print(
                        f" 渲染成功! (尝试 {attempt} 次，渲染 {preview_result.get('attempt', 1)} 次)"
                    )
                    print(f"   预览视频: {preview_result['video_path']}")

                    # 询问是否在文件管理器中打开
                    if input('是否在文件管理器中打开预览视频? (y/n): ').lower() == 'y':
                        import os
                        os.startfile(
                            os.path.dirname(preview_result['video_path']))

                    print('\n请观看预览视频后选择:')
                    print('1. 满意，保存代码并完成')
                    print('2. 需要改进，提供反馈继续优化')
                    print('3. 手动修改代码')

                    choice = input('选择 (1-3): ').strip()

                    if choice == '1':
                        task.manim_code = cleaned_code
                        print(' 代码已保存，生成完成!')
                        return
                    elif choice == '2':
                        feedback = input('请详细描述需要改进的地方: ').strip()
                        if feedback:
                            self.current_session.submit_feedback(
                                f'第{attempt}轮反馈: {feedback}')
                            requirements += f'\n\n反馈改进({attempt}): {feedback}'
                            continue
                        else:
                            task.manim_code = cleaned_code
                            return
                    elif choice == '3':
                        task.manim_code = cleaned_code
                        return self.manual_code_input()
                    else:
                        task.manim_code = cleaned_code
                        return

                else:
                    # 渲染失败
                    error_msg = preview_result.get('error', '未知错误')
                    print(f' 渲染失败: {error_msg}')

                    if attempt < max_attempts:
                        print(' AI正在自动分析和修复错误...')
                        requirements += f'\n\n错误修复({attempt}): 上一版本代码渲染失败，错误信息:\n{error_msg}\n请修复这些问题并生成可正常运行的代码。'
                        continue
                    else:
                        print(f' 经过 {max_attempts} 次尝试，仍无法生成可渲染的代码')
                        if input('是否保存最后生成的代码? (y/n): ').lower() == 'y':
                            task.manim_code = cleaned_code
                            print(' 已保存最后版本的代码（可能有问题）')
                        return

            except Exception as e:
                print(f' 第 {attempt} 次生成出现异常: {e}')
                if attempt < max_attempts:
                    requirements += f'\n\n异常修复({attempt}): 代码生成过程出现异常: {str(e)}\n请确保生成完整、正确的Manim代码。'
                    continue
                else:
                    print(f' 经过 {max_attempts} 次尝试，仍无法生成代码')
                    return

    def render_code_preview(self, manim_code, max_attempts=20):
        """渲染代码预览 - 带自动错误处理和重试机制"""
        if not self.current_session:
            return {'success': False, 'error': '没有活动会话', 'attempt': 0}

        task = self.current_session.task
        attempt = 0
        original_code = manim_code

        while attempt < max_attempts:
            attempt += 1
            print(f' 预览渲染尝试 {attempt}/{max_attempts}...')

            try:
                preview_path = self.current_session.create_preview(manim_code)

                if preview_path and os.path.exists(preview_path):
                    return {
                        'success': True,
                        'video_path': preview_path,
                        'attempt': attempt
                    }
                else:
                    error_info = self._get_detailed_render_error(
                        task, manim_code)

                    if error_info.get('is_system_error', False):
                        print('检测到Manim系统级错误，无法继续。请检查环境。')
                        return {
                            'success': False,
                            'error': 'Manim系统错误',
                            'attempt': attempt,
                            **error_info
                        }

                    print(f'第{attempt}次渲染失败，尝试使用LLM修复代码...')
                    fixed_code = self._fix_code_with_error(
                        manim_code, error_info, attempt)

                    if fixed_code and fixed_code != manim_code:
                        print('代码已通过LLM修复，正在重新渲染...')
                        manim_code = fixed_code
                        # 继续下一次循环，使用修复后的代码
                        continue
                    else:
                        print('LLM未能修复代码或未返回有效代码，将使用原始代码重试。')
                        # 如果修复失败，则在下一次循环中使用原始代码，但错误信息会累积
                        manim_code = original_code
                        if attempt >= max_attempts:
                            return {
                                'success': False,
                                'error': f'预览创建失败 (尝试 {attempt} 次)',
                                'attempt': attempt,
                                **error_info
                            }

            except Exception as e:
                error_msg = f'渲染主流程异常: {str(e)}'
                print(error_msg)
                if attempt >= max_attempts:
                    return {
                        'success': False,
                        'error': error_msg,
                        'attempt': attempt,
                        'final_error': str(e)
                    }

        return {
            'success': False,
            'error': f'经过 {max_attempts} 次尝试仍然失败',
            'attempt': max_attempts
        }

    def _get_detailed_render_error(self, task, manim_code):
        """获取详细的渲染错误信息 - 使用自动模式的完整渲染逻辑"""

        # Clean code before attempting render to avoid markdown/UTF issues
        try:
            from .workflow import clean_llm_code_output as _cleaner
            manim_code = _cleaner(manim_code) if manim_code else manim_code
        except Exception:
            pass

        error_info = {
            'stderr': '',
            'stdout': '',
            'final_error': '未知错误',
            'is_system_error': False
        }

        try:
            # 使用简化的渲染测试，避免与workflow的渲染循环冲突
            scene_name = f'Scene{task.segment_index}'

            # 创建临时目录用于渲染测试
            with tempfile.TemporaryDirectory() as temp_dir:
                print('执行单次渲染测试...')

                # 直接调用manim渲染，不使用workflow的重试逻辑
                result = self._single_render_test(manim_code, scene_name,
                                                  temp_dir)

                if result['success']:
                    error_info['final_error'] = '代码渲染成功，问题可能在预览创建逻辑中'
                    print('单次渲染测试成功')
                    return error_info
                else:
                    error_info['final_error'] = result.get('error', '单次渲染测试失败')
                    error_info['stderr'] = result.get('stderr', '')
                    error_info['is_system_error'] = result.get(
                        'is_system_error', False)
                    print(f"单次渲染测试失败: {error_info['final_error']}")

        except Exception as e:
            error_info['final_error'] = f'渲染测试时发生异常: {str(e)}'
            print(f'自动渲染逻辑异常: {e}')

        return error_info

    def _fix_code_with_error(self, manim_code, error_info, attempt):
        """使用LLM修复代码错误 - 人工模式仅修复渲染错误"""
        if not self.current_session:
            print('当前没有活跃的会话')
            return None

        try:
            # 导入修复功能
            from .workflow import fix_manim_error_with_llm

            task = self.current_session.task
            scene_name = f'Scene{task.segment_index}'

            # 构造错误信息
            error_message = ''
            if error_info.get('stderr'):
                error_message += f"STDERR:\n{error_info['stderr']}\n\n"
            if error_info.get('stdout'):
                error_message += f"STDOUT:\n{error_info['stdout']}\n\n"
            if error_info.get('final_error'):
                error_message += f"ERROR:\n{error_info['final_error']}\n"

            print(f'AI正在分析和修复错误 (第{attempt}次)...')

            # 人工模式：禁用布局优化，只修复渲染错误
            fixed_code = fix_manim_error_with_llm(
                manim_code,
                error_message,
                task.content_type,
                scene_name,
                enable_layout_optimization=False  # 人工模式禁用布局优化
            )

            if fixed_code and len(fixed_code.strip()) > 50:
                # 清理修复后的代码
                cleaned_code = clean_llm_code_output(fixed_code)
                return cleaned_code

        except ImportError:
            print('LLM错误修复功能不可用')
        except Exception as e:
            print(f'LLM修复过程出错: {e}')

        return None

    def _single_render_test(self, manim_code, scene_name, output_dir):
        """单次渲染测试，不使用重试循环，避免与主渲染逻辑冲突"""
        import subprocess
        import os

        result = {
            'success': False,
            'error': '',
            'stderr': '',
            'is_system_error': False
        }

        try:
            # 创建临时文件
            with tempfile.NamedTemporaryFile(
                    mode='w', suffix='.py', delete=False,
                    encoding='utf-8') as f:
                f.write(manim_code)
                temp_file = f.name

            # 构建manim命令
            cmd = [
                'manim', temp_file, scene_name, '-qm', '--disable_caching',
                '--media_dir', output_dir, '--format', 'mp4'
            ]

            # 执行渲染
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,  # 60秒超时
                encoding='utf-8',
                errors='replace')

            if process.returncode == 0:
                # 查找生成的视频文件
                video_path = os.path.join(
                    output_dir, 'videos',
                    os.path.splitext(os.path.basename(temp_file))[0], '720p30',
                    f'{scene_name}.mp4')
                if os.path.exists(video_path):
                    result['success'] = True
                    result['video_path'] = video_path
            else:
                result['error'] = f'渲染返回错误码: {process.returncode}'
                result['stderr'] = process.stderr or '无详细错误信息'

                # 检查是否为系统级错误
                if 'ModuleNotFoundError' in result[
                        'stderr'] or 'ImportError' in result[
                            'stderr'] or 'object not found' in result['stderr']:
                    result['is_system_error'] = True

        except subprocess.TimeoutExpired:
            result['error'] = '渲染超时(60秒)'
            result['stderr'] = '渲染过程超时，可能存在死循环或性能问题'
        except Exception as e:
            result['error'] = f'渲染过程异常: {str(e)}'
            result['is_system_error'] = True
        finally:
            # 清理临时文件
            try:
                if 'temp_file' in locals() and os.path.exists(temp_file):
                    os.unlink(temp_file)
            except:  # noqa
                pass

        return result

    def manual_code_input(self):
        """手动输入代码"""
        print('\n 手动输入动画代码')
        print('请输入完整的Manim动画代码')
        print("输入完成后，在空行输入'EOF'结束输入")
        print('-' * 50)

        lines = []
        while True:
            try:
                line = input()
                if line.strip() == 'EOF':
                    break
                lines.append(line)
            except KeyboardInterrupt:
                print('\n手动输入被中断')
                return

        code = '\n'.join(lines)
        if not code.strip():
            print('未输入任何代码')
            return

        print(f'\n代码输入完成 ({len(code)} 字符)')

        # 验证代码基本格式
        if 'class Scene' not in code or 'def construct' not in code:
            print('警告: 代码格式可能不正确，缺少Scene类或construct方法')
            if input('是否继续保存? (y/n): ').lower() != 'y':
                return

        # 保存代码
        self.current_session.task.manim_code = code
        print(' 手动代码已保存')

    def improve_code_with_feedback(self):
        """基于反馈改进代码"""
        if not self.current_session:
            print('当前没有活跃的会话')
            return

        feedback = input('请详细描述需要改进的地方: ').strip()
        if not feedback:
            print('未提供反馈信息')
            return

        print('正在基于反馈改进代码...')
        try:
            improved_code = self.current_session.improve_code_with_feedback(
                feedback)
            print(f'\n 代码改进完成 ({len(improved_code)} 字符)')

            if input('是否查看改进后的代码? (y/n): ').lower() == 'y':
                print('-' * 60)
                print(improved_code)
                print('-' * 60)

        except Exception as e:
            print(f'代码改进失败: {e}')

    def create_preview_interactive(self):
        """交互式创建预览"""
        task = self.current_session.task

        if not task.manim_code:
            print('请先生成动画代码')
            return

        print('\n 创建预览视频')
        print('正在渲染动画并合成预览...')

        try:
            preview_path = self.current_session.create_preview()
            if preview_path:
                print(f' 预览视频已生成: {preview_path}')

                if input('是否在文件管理器中打开? (y/n): ').lower() == 'y':
                    os.startfile(os.path.dirname(preview_path))

                print('\n请观看预览视频，然后选择:')
                print('1. 满意，批准动画')
                print('2. 需要修改')
                print('3. 稍后决定')

                choice = input('选择 (1-3): ').strip()
                if choice == '1':
                    self.approve_animation_interactive()
                elif choice == '2':
                    feedback = input('请详细描述需要修改的地方: ')
                    self.current_session.submit_feedback(feedback)
            else:
                print(' 预览视频生成失败')

        except Exception as e:
            print(f'创建预览失败: {e}')

    def chat_with_assistant(self):
        """与AI助手对话"""
        print('\n AI助手对话')
        print("输入 'quit' 退出对话")

        while True:
            try:
                user_input = input('\n你: ').strip()
                if user_input.lower() in ['quit', 'exit', '退出']:
                    break

                if not user_input:
                    continue

                print(' AI助手正在思考...')
                response = self.current_session.chat_with_llm(user_input)
                print(f' AI助手: {response}')

            except KeyboardInterrupt:
                print('\n对话结束')
                break

    def submit_feedback_interactive(self):
        """交互式提交反馈"""

        print('\n 提交反馈')
        feedback = input('请输入你的反馈意见: ').strip()

        if feedback:
            self.current_session.submit_feedback(feedback)
            print('反馈已记录')
        else:
            print('未输入反馈内容')

    def approve_animation_interactive(self):
        """交互式批准动画"""
        if not self.current_session:
            print('当前没有活跃的会话')
            return

        task = self.current_session.task

        if task.status != AnimationStatus.PREVIEW:
            print(' 只能批准处于预览状态的动画')
            return

        print('\n 批准动画')
        print(f'任务: {task.content[:50]}...')

        if input('确认批准此动画? (y/n): ').lower() == 'y':
            if self.current_session.approve_animation():
                print(' 动画已批准并保存！')
                print('会话结束，返回主菜单')
                self.current_session = None

                # 检查是否所有任务都已完成，如果是则自动合并最终视频
                self._check_and_auto_merge_videos()
            else:
                print(' 动画批准失败')

    def show_session_status(self):
        """显示会话状态"""
        if not self.current_session:
            return

        summary = self.current_session.get_session_summary()

        print('\n 会话状态')
        print('-' * 40)
        print(f"任务ID: {summary['task_id']}")
        print(f"内容: {summary['content'][:60]}...")
        print(f"状态: {summary['status']}")
        print(f"修订次数: {summary['revision_count']}")
        print(f"有文案: {'✅' if summary['has_script'] else '❌'}")
        print(f"有代码: {'✅' if summary['has_code'] else '❌'}")
        print(f"有预览: {'✅' if summary['has_preview'] else '❌'}")
        print(f"已完成: {'✅' if summary['has_final'] else '❌'}")

        if summary['conversation_history']:
            print(f"对话记录: {len(summary['conversation_history'])} 条")

    def continue_session(self):
        """继续现有会话"""
        # 查找草稿和预览状态的任务
        active_tasks = (
            self.studio.task_manager.get_tasks_by_status(AnimationStatus.DRAFT)
            + self.studio.task_manager.get_tasks_by_status(
                AnimationStatus.PREVIEW)
            + self.studio.task_manager.get_tasks_by_status(
                AnimationStatus.REVISION))

        if not active_tasks:
            print(' 没有可继续的会话')
            return

        print('\n可继续的会话:')
        for i, task in enumerate(active_tasks, 1):
            print(
                f'{i}. [{task.task_id}] {task.content[:50]}... ({task.status.value})'
            )

        try:
            choice = int(input('选择会话编号: ')) - 1
            if 0 <= choice < len(active_tasks):
                selected_task = active_tasks[choice]
                self.current_session = self.studio.start_human_session(
                    selected_task.task_id)
                if self.current_session:
                    self.run_animation_session()
        except ValueError:
            print('请输入有效数字')

    def review_completed_tasks(self):
        """查看已完成任务"""
        completed_tasks = self.studio.task_manager.get_tasks_by_status(
            AnimationStatus.COMPLETED)

        if not completed_tasks:
            print('\n 还没有完成的动画任务')
            return

        print(f'\n 已完成任务 ({len(completed_tasks)} 个):')
        print('-' * 60)

        for i, task in enumerate(completed_tasks, 1):
            print(f'{i}. [{task.task_id}] ({task.content_type})')
            print(f'   内容: {task.content[:60]}...')
            print(f'   最终文件: {task.final_video_path}')
            print(f'   修订次数: {task.revision_count}')
            print()

    def show_project_status(self):
        """显示项目状态"""
        all_tasks = list(self.studio.task_manager.tasks.values())

        if not all_tasks:
            print('\n 项目中还没有动画任务')
            return

        # 统计各状态任务数量
        status_count = {}
        for task in all_tasks:
            status = task.status
            status_count[status] = status_count.get(status, 0) + 1

        print('\n 项目状态总览')
        print('-' * 40)
        print(f'总任务数: {len(all_tasks)}')

        for status in AnimationStatus:
            count = status_count.get(status, 0)
            if count > 0:
                emoji = {
                    AnimationStatus.PENDING: '⏳',
                    AnimationStatus.DRAFT: '📝',
                    AnimationStatus.PREVIEW: '👁️',
                    AnimationStatus.REVISION: '🔄',
                    AnimationStatus.APPROVED: '✅',
                    AnimationStatus.COMPLETED: '🎉',
                    AnimationStatus.FAILED: '❌'
                }.get(status, '❓')
                print(f'{emoji} {status.value}: {count} 个')

        # 计算完成率
        completed = status_count.get(AnimationStatus.COMPLETED, 0)
        progress = (completed / len(all_tasks)) * 100 if all_tasks else 0
        print(f'\n完成进度: {progress:.1f}% ({completed}/{len(all_tasks)})')

    def _check_and_auto_merge_videos(self):
        """检查是否所有任务都已完成，如果是则自动合并最终视频"""
        all_tasks = list(self.studio.task_manager.tasks.values())
        if not all_tasks:
            return

        # 检查是否有未完成的任务
        incomplete_tasks = [
            task for task in all_tasks if task.status not in
            [AnimationStatus.COMPLETED, AnimationStatus.APPROVED]
        ]

        if not incomplete_tasks:
            print('\n🎉 所有动画任务已完成！正在自动合成最终视频...')
            self._auto_merge_completed_videos()
        else:
            completed_count = len([
                t for t in all_tasks if t.status in
                [AnimationStatus.COMPLETED, AnimationStatus.APPROVED]
            ])

            total_count = len(all_tasks)
            print(
                f'\n还有 {len(incomplete_tasks)} 个任务未完成 ({completed_count}/{total_count})'
            )

    def _auto_merge_completed_videos(self):
        """自动合并所有已完成的动画视频"""
        try:
            import os
            import datetime
            from moviepy.editor import VideoFileClip, concatenate_videoclips

            # 获取所有已完成的动画文件
            finals_dir = self.studio.finals_dir
            completed_videos = []

            if os.path.exists(finals_dir):
                for file in os.listdir(finals_dir):
                    if file.endswith('.mov') or file.endswith('.mp4'):
                        video_path = os.path.join(finals_dir, file)
                        completed_videos.append(video_path)

            if not completed_videos:
                print('未找到已完成的动画视频文件')
                return

            # 按场景序号排序
            def extract_scene_num(filename):
                import re
                match = re.search(r'scene_(\d+)', filename)
                return int(match.group(1)) if match else 999

            completed_videos.sort(
                key=lambda x: extract_scene_num(os.path.basename(x)))

            print(f'找到 {len(completed_videos)} 个已完成的动画视频:')
            for video in completed_videos:
                print(f'  - {os.path.basename(video)}')

            # 合并视频
            print('正在合并动画视频...')
            video_clips = []
            for video_path in completed_videos:
                try:
                    clip = VideoFileClip(video_path)
                    video_clips.append(clip)
                except Exception as e:
                    print(f'加载视频失败 {video_path}: {e}')

            if not video_clips:
                print('没有有效的视频片段可以合并')
                return

            # 合并所有视频片段
            final_clip = concatenate_videoclips(video_clips, method='compose')

            # 生成输出路径
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(self.project_dir,
                                       f'final_animation_{timestamp}.mp4')

            # 导出最终视频
            print(f'正在导出最终动画视频: {output_path}')
            final_clip.write_videofile(
                output_path,
                fps=30,
                codec='libx264',
                audio_codec='aac',
                temp_audiofile=os.path.join(self.project_dir,
                                            'temp_audio.m4a'),
                remove_temp=True)

            # 清理临时文件
            final_clip.close()
            for clip in video_clips:
                clip.close()

            print('\n✅ 动画视频合并完成！')
            print(f'📁 输出文件: {output_path}')
            print(f'🎬 总时长: {final_clip.duration:.1f}秒')
            print(f'🎞️ 包含 {len(completed_videos)} 个动画片段')

            # 如果有 workflow 实例，尝试合成完整视频（带背景、字幕、音频）
            if self.workflow_instance:
                print('\n🔄 检测到主工作流，正在合成完整视频（背景+字幕+音频）...')
                try:
                    self._compose_full_final_video(output_path)
                except Exception as e:
                    print(f'完整视频合成失败: {e}')
                    print('但动画视频已成功合并')

        except ImportError as e:
            print(f'缺少必要的库: {e}')
            print('请安装 moviepy: pip install moviepy')
        except Exception as e:
            print(f'自动合并视频失败: {e}')
            import traceback
            traceback.print_exc()

    def _compose_full_final_video(self, animation_video_path):
        """合成完整的最终视频（类似主流程：背景+动画+字幕+音频）"""
        try:
            import json
            import os

            # 读取结构化内容：优先 segments.json；若不存在则回退 asset_info.json
            segments = None
            segments_path = os.path.join(self.project_dir, 'segments.json')
            asset_info_path = os.path.join(self.project_dir, 'asset_info.json')

            if os.path.exists(segments_path):
                try:
                    with open(segments_path, 'r', encoding='utf-8') as f:
                        segments = json.load(f)
                except Exception as e:
                    print(f'读取 segments.json 失败: {e}')

            if not segments and os.path.exists(asset_info_path):
                try:
                    with open(asset_info_path, 'r', encoding='utf-8') as f:
                        info = json.load(f)
                        segments = info.get('segments')
                        if not segments:
                            print('asset_info.json 中缺少 segments 字段')
                except Exception as e:
                    print(f'读取 asset_info.json 失败: {e}')

            if not segments:
                print('未找到 segments.json 或 asset_info.json，跳过完整视频合成')
                return

            # 获取项目资源（使用底层 studio 自带的背景检索器）
            unified_background_path = self.studio._get_project_background()
            # 兼容两处资产目录：优先 core/asset，其次项目根下的 asset
            base_dir = os.path.dirname(os.path.dirname(
                self.project_dir))  # .../projects/video_generate
            music_candidates = [
                os.path.join(base_dir, 'core', 'asset', 'bg_audio.mp3'),
                os.path.join(base_dir, 'asset', 'bg_audio.mp3'),
            ]
            bg_music_path = next(
                (p for p in music_candidates if os.path.exists(p)), None)

            # 逐段收集主流程所需素材（严格按 segments 顺序）
            audio_paths = []  # segment_i.mp3
            subtitle_paths = []  # 文本段用单张字幕PNG，其余为 None
            subtitle_segments_list = []  # 非文本段用多张字幕PNG列表，文本段为空列表或单张作为冗余
            illustration_paths = []  # 文本段插画，非文本段 None
            foreground_paths = []  # 非文本段对应的 MOV，文本段 None

            import glob as _glob

            audio_dir = os.path.join(self.project_dir, 'audio')
            subtitle_dir = os.path.join(self.project_dir, 'subtitles')
            images_dir = os.path.join(self.project_dir, 'images')
            finals_dir = self.studio.finals_dir

            # 插画路径来源：优先读取主流程生成的 image_paths.json，并按文本段序号依次分配
            image_paths_indexed = []
            image_paths_json = os.path.join(images_dir, 'image_paths.json')
            if os.path.exists(image_paths_json):
                try:
                    with open(image_paths_json, 'r', encoding='utf-8') as f:
                        image_paths_indexed = [
                            p for p in (json.load(f) or [])
                            if isinstance(p, str)
                        ]
                except Exception:
                    image_paths_indexed = []

            fg_out_dir = os.path.join(images_dir, 'output_black_only')
            text_img_idx = 0

            for i, seg in enumerate(segments):
                seg_idx = i + 1
                seg_type = seg.get('type', 'text')

                # 1) 音频：segment_{i}.mp3
                audio_path = os.path.join(audio_dir, f'segment_{seg_idx}.mp3')
                if not os.path.exists(audio_path):
                    wav_path = os.path.join(audio_dir,
                                            f'segment_{seg_idx}.wav')
                    audio_path = wav_path if os.path.exists(wav_path) else None
                audio_paths.append(audio_path)

                # 2) 字幕（按主流程约定）
                # 文本段：单张 PNG
                # 非文本段：多张 PNG 序列
                seg_subs_list = []
                if os.path.isdir(subtitle_dir):
                    # 多张分段字幕
                    try:
                        multi = sorted([
                            os.path.join(subtitle_dir, f)
                            for f in os.listdir(subtitle_dir)
                            if f.startswith(f'bilingual_subtitle_{seg_idx}_')
                            and f.endswith('.png')
                        ])
                        seg_subs_list = multi
                    except Exception:
                        seg_subs_list = []

                if seg_type == 'text':
                    # 单张字幕
                    single_png = os.path.join(
                        subtitle_dir, f'bilingual_subtitle_{seg_idx}.png')
                    subtitle_paths.append(
                        single_png if os.path.exists(single_png) else None)
                    subtitle_segments_list.append([])
                else:
                    subtitle_paths.append(None)
                    subtitle_segments_list.append(seg_subs_list)

                # 3) 插画（仅文本段）
                if seg_type == 'text':
                    illus = None
                    # 根据主流程的顺序匹配 image_paths.json
                    if text_img_idx < len(image_paths_indexed):
                        base_img = image_paths_indexed[text_img_idx]
                        text_img_idx += 1
                        # 优先透明版本
                        try:
                            base_name = os.path.splitext(
                                os.path.basename(base_img))[0]
                            transparent_png = os.path.join(
                                fg_out_dir, base_name + '.png')
                            illus = transparent_png if os.path.exists(
                                transparent_png) else base_img
                        except Exception:
                            illus = base_img
                    illustration_paths.append(
                        illus if illus and os.path.exists(illus) else None)
                else:
                    illustration_paths.append(None)

                # 4) 前景动画（仅非文本段）
                if seg_type != 'text':
                    # 优先：工作室终稿
                    finals_mov = os.path.join(finals_dir,
                                              f'scene_{seg_idx}_final.mov')
                    # 次选：主流程渲染目录（Scene{i}.mov）
                    scene_mov = os.path.join(self.project_dir,
                                             f'scene_{seg_idx}',
                                             f'Scene{seg_idx}.mov')
                    # 兜底：仅匹配最终成品，不使用占位或预览
                    root_final = os.path.join(self.project_dir,
                                              f'scene_{seg_idx}_final.mov')
                    cand = None
                    if os.path.exists(finals_mov):
                        cand = finals_mov
                    elif os.path.exists(scene_mov):
                        cand = scene_mov
                    elif os.path.exists(root_final):
                        cand = root_final
                    foreground_paths.append(
                        cand if cand and os.path.exists(cand) else None)
                else:
                    foreground_paths.append(None)

            # 解析工作流函数（实例优先，退化到模块导入）
            compose_fn = None
            add_music_fn = None
            if self.workflow_instance and hasattr(self.workflow_instance,
                                                  'compose_final_video'):
                compose_fn = self.workflow_instance.compose_final_video
            else:
                try:
                    from .workflow import compose_final_video as _compose_final_video
                    compose_fn = _compose_final_video
                except Exception:
                    compose_fn = None

            if self.workflow_instance and hasattr(self.workflow_instance,
                                                  'add_background_music'):
                add_music_fn = self.workflow_instance.add_background_music
            else:
                try:
                    from .workflow import add_background_music as _add_background_music
                    add_music_fn = _add_background_music
                except Exception:
                    add_music_fn = None

            # 调用主流程的视频合成函数（使用主流程完整素材，而不是仅合并动画）
            if compose_fn:
                final_video_path = os.path.join(self.project_dir,
                                                'final_complete.mp4')

                enhanced_video_path = compose_fn(unified_background_path,
                                                 foreground_paths, audio_paths,
                                                 subtitle_paths,
                                                 illustration_paths, segments,
                                                 final_video_path,
                                                 subtitle_segments_list)

                if enhanced_video_path and os.path.exists(enhanced_video_path):
                    # 添加背景音乐
                    if os.path.exists(bg_music_path) and add_music_fn:
                        final_with_music = os.path.join(
                            self.project_dir, 'final_complete_with_music.mp4')
                        add_music_fn(
                            enhanced_video_path,
                            final_with_music,
                            music_volume=0.15)
                        print(f'完整视频合成完成（含背景音乐）: {final_with_music}')
                    else:
                        print(f'完整视频合成完成: {enhanced_video_path}')
                        if not os.path.exists(bg_music_path):
                            print('未找到背景音乐文件')
                else:
                    print('完整视频合成失败')
            else:
                print('主工作流实例不包含视频合成函数')

        except Exception as e:
            print(f'完整视频合成过程出错: {e}')
            import traceback
            traceback.print_exc()

    def manual_merge_videos(self):
        """手动合并已完成的视频"""
        print('\n 合并已完成视频')

        # 检查是否有已完成的视频
        finals_dir = self.studio.finals_dir
        if not os.path.exists(finals_dir):
            print('未找到已完成的动画视频目录')
            return

        completed_videos = []
        for file in os.listdir(finals_dir):
            if file.endswith('.mov') or file.endswith('.mp4'):
                completed_videos.append(os.path.join(finals_dir, file))

        if not completed_videos:
            print('未找到已完成的动画视频文件')
            return

        print(f'找到 {len(completed_videos)} 个已完成的动画视频:')
        for video in completed_videos:
            print(f'  - {os.path.basename(video)}')

        if input(f'\n确认合并这 {len(completed_videos)} 个视频? (y/n): ').lower(
        ) == 'y':
            self._auto_merge_completed_videos()
        else:
            print('已取消合并操作')


if __name__ == '__main__':
    # 直接运行时启动交互式工作室
    import argparse
    parser = argparse.ArgumentParser(description='交互式动画制作工作室')
    parser.add_argument('project_dir', help='项目目录路径，例如: output\\什么是token')
    args = parser.parse_args()

    project_dir = args.project_dir
    if not os.path.isabs(project_dir):
        # 允许相对路径
        project_dir = os.path.abspath(project_dir)

    if not os.path.exists(project_dir):
        print(f'错误: 项目目录不存在: {project_dir}')
        sys.exit(1)

    # 可选：传入工作流实例，便于最终合并时使用主流程
    try:
        from .workflow import generate_ai_science_knowledge_video as workflow_instance
    except Exception as e:
        print(f'[DEBUG] 无法导入工作流实例: {e}')
        workflow_instance = None

    studio = InteractiveAnimationStudio(project_dir, workflow_instance)
    print('[DEBUG] 启动交互式工作室...', flush=True)
    studio.start_interactive_mode()
