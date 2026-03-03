# Copyright (c) ModelScope Contributors. All rights reserved.
import base64
import math
import os
import shutil
from copy import deepcopy

import json
import moviepy as mp
from moviepy import AudioClip
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig
from PIL import Image

logger = get_logger()


class ComposeVideo(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.background_effect = getattr(self.config, 'background_effect',
                                         None)
        self.bg_path = os.path.join(self.work_dir, 'background.png')

        # Determine render directory based on engine
        engine = getattr(self.config, 'animation_engine', 'remotion')
        if engine == 'remotion':
            self.render_dir = os.path.join(self.work_dir, 'remotion_render')
        else:
            self.render_dir = os.path.join(self.work_dir, 'manim_render')

        self.tts_dir = os.path.join(self.work_dir, 'audio')
        self.images_dir = os.path.join(self.work_dir, 'images')
        self.videos_dir = os.path.join(self.work_dir, 'videos')
        self.subtitle_dir = os.path.join(self.work_dir, 'subtitles')
        self.bitrate = getattr(self.config.video, 'bitrate', '5000k')
        self.preset = getattr(self.config.video, 'preset', 'ultrafast')
        self.fps = getattr(self.config.video, 'fps', 24)

    def compose_final_video(self, background_path, foreground_paths,
                            audio_paths, subtitle_paths, illustration_paths,
                            video_paths, segments, output_path):
        segment_durations = []
        logger.info('Composing the final video.')

        # Track which segments use generated video audio
        segment_video_audios = []

        for i, audio_path in enumerate(audio_paths):
            actual_duration = 2.0
            segment = segments[i]
            is_video_frame = 'video' in segment
            use_video_soundtrack = self.config.use_video_soundtrack and is_video_frame
            if audio_path and os.path.exists(
                    audio_path) and not use_video_soundtrack:
                try:
                    audio_clip = mp.AudioFileClip(audio_path)
                    # Use actual audio duration + small pause, no minimum enforcement
                    actual_duration = audio_clip.duration + 0.3  # Add 0.3s natural pause between sentences
                    audio_clip.close()
                except:  # noqa
                    actual_duration = 2.0
            else:
                actual_duration = None
                if not use_video_soundtrack:
                    raise ValueError(
                        f'File {audio_path} does not exist, run again to generate it.'
                    )

            if i < len(foreground_paths
                       ) and foreground_paths[i] and os.path.exists(
                           foreground_paths[i]):
                animation_clip = mp.VideoFileClip(
                    foreground_paths[i], has_mask=True)
                animation_duration = animation_clip.duration
                animation_clip.close()

                if animation_duration > actual_duration:
                    actual_duration = animation_duration

            segment_durations.append(actual_duration)

        logger.info('Step1: Compose video for each segment.')
        segment_videos = []

        for i, (duration,
                segment) in enumerate(zip(segment_durations, segments)):
            if duration is not None:
                logger.info(
                    f'Processing {i + 1} segment - {duration:.1f} seconds.')
            else:
                logger.info(
                    f'Processing {i + 1} segment - use video soundtrack.')

            current_video_clips = []

            # Check if this segment uses generated video instead of illustration
            use_generated_video = 'video' in segment and video_paths[
                i] and os.path.exists(video_paths[i])

            if use_generated_video:
                # Use generated video as base layer
                logger.info(f'Using generated video for segment {i + 1}')
                try:
                    video_clip = mp.VideoFileClip(video_paths[i])
                    video_original_w, video_original_h = video_clip.size

                    # Validate video dimensions
                    if video_original_w <= 0 or video_original_h <= 0:
                        logger.error(
                            f'Invalid video dimensions: {video_original_w}x{video_original_h} for {video_paths[i]}'
                        )
                        video_clip.close()
                        use_generated_video = False
                    else:
                        # Resize video to fill 1920x1080 screen
                        video_available_w, video_available_h = 1920, 1080
                        video_scale_w = video_available_w / video_original_w
                        video_scale_h = video_available_h / video_original_h
                        video_scale = max(video_scale_w,
                                          video_scale_h)  # Cover mode

                        video_new_w = int(video_original_w * video_scale)
                        video_new_h = int(video_original_h * video_scale)
                        if video_new_w % 2 != 0:
                            video_new_w += 1
                        if video_new_h % 2 != 0:
                            video_new_h += 1

                        if video_new_w > 0 and video_new_h > 0:
                            video_clip = video_clip.resized(
                                (video_new_w, video_new_h))
                            video_clip = video_clip.with_position('center')

                            # Extract and preserve video audio before adjusting duration
                            video_audio = None
                            if video_clip.audio is not None:
                                logger.info(
                                    f'Extracting audio from generated video {i + 1}'
                                )
                                video_audio = video_clip.audio
                            segment_video_audios.append(video_audio)

                            if self.config.use_video_soundtrack:
                                duration = video_clip.duration
                            else:
                                assert duration is not None and duration > 0
                                # Adjust video duration to match segment duration
                                if video_clip.duration < duration:
                                    logger.info(
                                        f'Video {i + 1} is shorter than segment, extending to {duration:.1f}s'
                                    )
                                    video_clip = video_clip.with_duration(
                                        duration)
                                elif video_clip.duration > duration:
                                    logger.info(
                                        f'Video {i + 1} is longer than segment, trimming to {duration:.1f}s'
                                    )
                                    video_clip = video_clip.subclipped(
                                        0, duration)

                            current_video_clips.append(video_clip)
                        else:
                            logger.error(
                                f'Invalid scaled video dimensions: {video_new_w}x{video_new_h}'
                            )
                            video_clip.close()
                            use_generated_video = False
                except Exception as e:
                    logger.error(
                        f'Failed to process video for segment {i + 1}: {e}')
                    use_generated_video = False
                    segment_video_audios.append(None)
            else:
                segment_video_audios.append(None)

            # Add illustration as base layer (if not using generated video)
            if not use_generated_video and i < len(
                    illustration_paths
            ) and illustration_paths[i] and os.path.exists(
                    illustration_paths[i]):
                illustration_clip = mp.ImageClip(
                    illustration_paths[i], duration=duration)
                bg_original_w, bg_original_h = illustration_clip.size

                # Validate image dimensions
                if bg_original_w <= 0 or bg_original_h <= 0:
                    logger.error(
                        f'Invalid illustration dimensions: {bg_original_w}x{bg_original_h} for {illustration_paths[i]}'
                    )
                    continue

                bg_available_w, bg_available_h = 1920, 1080
                bg_scale_w = bg_available_w / bg_original_w
                bg_scale_h = bg_available_h / bg_original_h
                # Use max instead of min to fill the entire screen (cover mode)
                bg_scale = max(bg_scale_w, bg_scale_h)

                # Always resize to fill the screen
                bg_new_w = int(bg_original_w * bg_scale)
                bg_new_h = int(bg_original_h * bg_scale)
                if bg_new_w % 2 != 0:
                    bg_new_w += 1
                if bg_new_h % 2 != 0:
                    bg_new_h += 1

                # Ensure dimensions are positive
                if bg_new_w <= 0 or bg_new_h <= 0:
                    logger.error(
                        f'Invalid scaled dimensions: {bg_new_w}x{bg_new_h}')
                    continue

                illustration_clip = illustration_clip.resized(
                    (bg_new_w, bg_new_h))

                exit_duration = 1.0
                start_animation_time = max(duration - exit_duration, 0)

                if self.background_effect == 'ken-burns-effect':
                    # Ken Burns effect: smooth zoom-in with stable center position
                    zoom_start = 1.0  # Initial scale
                    zoom_end = 1.15  # Final scale (15% zoom)

                    # Capture variables in closure to prevent external modification
                    kb_base_w = bg_new_w
                    kb_base_h = bg_new_h
                    kb_duration = duration

                    def make_ken_burns(t):
                        """Create smooth zoom-in effect with easing"""
                        # Smooth easing function (ease-in-out)
                        progress = t / kb_duration if kb_duration > 0 else 0
                        progress = min(1.0, progress)
                        # Cubic easing for smooth acceleration/deceleration
                        eased_progress = progress * progress * (
                            3.0 - 2.0 * progress)
                        if eased_progress > 1.0:
                            eased_progress = 1.0
                        # Calculate current zoom level
                        current_zoom = zoom_start + (
                            zoom_end - zoom_start) * eased_progress
                        # Calculate new dimensions with validation
                        zoom_w = int(kb_base_w * current_zoom)
                        zoom_h = int(kb_base_h * current_zoom)
                        # Ensure dimensions are always positive and at least 1
                        zoom_w = max(kb_base_w, zoom_w)
                        zoom_h = max(kb_base_h, zoom_h)
                        # Return the new size at time t as a tuple (width, height)
                        return zoom_w, zoom_h

                    # Apply the zoom effect with resizing over time
                    illustration_clip = illustration_clip.resized(
                        make_ken_burns)
                    # Keep image centered and stable throughout the animation
                    illustration_clip = illustration_clip.with_position(
                        'center')

                elif self.background_effect == 'slide':
                    # TODO legacy code, untested
                    # Default slide left animation
                    def illustration_pos_factory(idx, start_x, end_x, bg_h,
                                                 start_animation_time,
                                                 exit_duration):

                        def illustration_pos(t):
                            y = (1080 - bg_h) // 2
                            if t < start_animation_time:
                                x = start_x
                            elif t < start_animation_time + exit_duration:
                                progress = (
                                    t - start_animation_time) / exit_duration
                                progress = min(max(progress, 0), 1)
                                x = start_x + (end_x - start_x) * progress
                            else:
                                x = end_x
                            return x, y

                        return illustration_pos

                    illustration_clip = illustration_clip.with_position(
                        illustration_pos_factory(i, (1920 - bg_new_w) // 2,
                                                 -bg_new_w, bg_new_h,
                                                 start_animation_time,
                                                 exit_duration))

                current_video_clips.append(illustration_clip)

            # Add foreground animation layer

            if i < len(foreground_paths
                       ) and foreground_paths[i] and os.path.exists(
                           foreground_paths[i]):
                fg_clip = mp.VideoFileClip(foreground_paths[i], has_mask=True)
                original_w, original_h = fg_clip.size
                available_w, available_h = (
                    1250, 700) if self.config.use_subtitle else (1450, 800)
                scale_w = available_w / original_w
                scale_h = available_h / original_h
                scale = min(scale_w, scale_h, 1.0)

                if scale < 1.0:
                    new_w = int(original_w * scale)
                    new_h = int(original_h * scale)
                    # Ensure dimensions are positive
                    if new_w > 0 and new_h > 0:
                        fg_clip = fg_clip.resized((new_w, new_h))
                    else:
                        logger.error(
                            f'Invalid scaled foreground dimensions: {new_w}x{new_h}'
                        )
                        fg_clip.close()
                        continue

                # Position in the center of the top 3/4 area
                # Center horizontally, vertically centered in top 810px region
                # Y coordinate: (810 / 2) - (clip_height / 2) = center of top 3/4
                # top_area_center_y = 800 // 2 - 250  # 405px from top # not work
                fg_clip = fg_clip.with_position(('center', 'center'))
                fg_clip = fg_clip.with_duration(duration)
                current_video_clips.append(fg_clip)
            if self.config.use_subtitle:
                if duration is not None and i < len(
                        subtitle_paths) and subtitle_paths[i]:
                    segment_subs = subtitle_paths[i]
                    num_subs = len(segment_subs)
                    sub_duration = duration / num_subs

                    for k, sub_path in enumerate(segment_subs):
                        if os.path.exists(sub_path):
                            try:
                                subtitle_img = Image.open(sub_path)
                                subtitle_w, subtitle_h = subtitle_img.size

                                if subtitle_w <= 0 or subtitle_h <= 0:
                                    logger.error(
                                        f'Invalid subtitle dimensions: {subtitle_w}x{subtitle_h} for {sub_path}'
                                    )
                                    continue

                                subtitle_clip = mp.ImageClip(
                                    sub_path, duration=sub_duration)
                                subtitle_y = 900
                                subtitle_clip = subtitle_clip.with_position(
                                    ('center', subtitle_y))
                                subtitle_clip = subtitle_clip.with_start(
                                    k * sub_duration)
                                current_video_clips.append(subtitle_clip)
                            except Exception as e:
                                logger.error(
                                    f'Failed to load subtitle {sub_path}: {e}')

            # Add background as top layer (transparent PNG with decorative elements)
            if background_path and os.path.exists(background_path):
                bg_clip = mp.ImageClip(background_path, duration=duration)
                bg_clip = bg_clip.resized((1920, 1080))
                current_video_clips.append(bg_clip)

            if current_video_clips:
                segment_video = mp.CompositeVideoClip(
                    current_video_clips, size=(1920, 1080))
                segment_videos.append(segment_video)

        logger.info('Step2: Combine all video segments.')
        final_video = mp.concatenate_videoclips(
            segment_videos, method='compose')
        logger.info('Step3: Compose audios.')
        if audio_paths:
            valid_audio_clips = []
            for i, (audio_path, duration, segment) in enumerate(
                    zip(audio_paths, segment_durations, segments)):
                segment_audio = None

                # Check if this segment has generated video audio
                if i < len(segment_video_audios) and segment_video_audios[
                        i] is not None and self.config.use_video_soundtrack:
                    logger.info(
                        f'Using audio from generated video for segment {i + 1}'
                    )
                    segment_audio = segment_video_audios[i]
                elif audio_path and os.path.exists(audio_path):
                    # Use TTS audio if no video audio available
                    audio_clip = mp.AudioFileClip(audio_path)
                    audio_clip = audio_clip.with_fps(44100)
                    # audio_clip = audio_clip.set_channels(2)
                    if audio_clip.duration > duration:
                        audio_clip = audio_clip.subclipped(0, duration)
                    elif audio_clip.duration < duration:

                        silence = AudioClip(
                            lambda t: [0, 0],
                            duration=duration
                            - audio_clip.duration).with_fps(44100)
                        # silence = silence.set_channels(2)
                        audio_clip = mp.concatenate_audioclips(
                            [audio_clip, silence])
                    segment_audio = audio_clip

                if segment_audio is not None:
                    valid_audio_clips.append(segment_audio)

            if valid_audio_clips:
                final_audio = mp.concatenate_audioclips(valid_audio_clips)
                logger.info(
                    f'Audio composing done: {final_audio.duration:.1f} seconds.'
                )
                if final_audio.duration > final_video.duration:
                    final_audio = final_audio.subclipped(
                        0, final_video.duration)
                elif final_audio.duration < final_video.duration:
                    silence = AudioClip(
                        lambda t: [0, 0],
                        duration=final_video.duration - final_audio.duration)
                    final_audio = mp.concatenate_audioclips(
                        [final_audio, silence])

                final_video = final_video.with_audio(final_audio)

            if self.config.bg_audio_path:
                if os.path.exists(self.config.bg_audio_path):
                    bg_music_path = self.config.bg_audio_path
                else:
                    bg_music_path = os.path.join(self.config.local_dir,
                                                 self.config.bg_audio_path)
            else:
                bg_music_path = ''
            if os.path.exists(
                    bg_music_path) and not self.config.use_video_soundtrack:
                bg_music = mp.AudioFileClip(bg_music_path)
                if bg_music.duration < final_video.duration:
                    repeat_times = int(
                        final_video.duration / bg_music.duration) + 1
                    bg_music = mp.concatenate_audioclips([bg_music]
                                                         * repeat_times)
                    bg_music = bg_music.subclipped(0, final_video.duration)
                elif bg_music.duration > final_video.duration:
                    bg_music = bg_music.subclipped(0, final_video.duration)
                bg_music = bg_music.with_volume_scaled(
                    self.config.bg_audio_volume)
                if final_video.audio:
                    tts_audio = final_video.audio.with_duration(
                        final_video.duration).with_volume_scaled(1.0)
                    bg_audio = bg_music.with_duration(final_video.duration)
                    mixed_audio = mp.CompositeAudioClip(
                        [tts_audio,
                         bg_audio]).with_duration(final_video.duration)
                else:
                    mixed_audio = bg_music.with_duration(
                        final_video.duration).with_volume_scaled(0.3)
                final_video = final_video.with_audio(mixed_audio)

        assert final_video is not None
        logger.info('Rendering final video...')
        logger.info(
            f'Total video duration: {final_video.duration:.1f} seconds')
        logger.info(f'Video resolution: {final_video.size}')
        logger.info(
            f"Audio status: {'Has audio' if final_video.audio else 'No audio'}"
        )
        logger.info(f'final_video type: {type(final_video)}')
        logger.info(f'final_video attributes: {dir(final_video)}')

        final_video.write_videofile(
            output_path,
            fps=self.fps,
            codec='libx264',
            audio_codec='aac',
            temp_audiofile='temp-audio.m4a',
            remove_temp=True,
            logger=None,
            threads=16,
            bitrate=self.bitrate,
            audio_bitrate='192k',
            audio_fps=44100,
            preset=self.preset,
            write_logfile=False)

        logger.info(f'file saved: {output_path}')

        if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            test_clip = mp.VideoFileClip(output_path)
            actual_duration = test_clip.duration
            test_clip.close()
            if abs(actual_duration - final_video.duration) >= 1.0:
                raise RuntimeError('Duration not match')

    async def execute_code(self, messages, **kwargs):
        final_name = 'final_video.mp4'
        final_video_path = os.path.join(self.work_dir, final_name)
        if os.path.exists(final_video_path):
            logger.info(f'output: {final_video_path}')
            return messages
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)

        foreground_paths = []
        audio_paths = []
        subtitle_paths = []
        illustration_paths = []
        video_paths = []
        for i, segment in enumerate(segments):
            illustration_paths.append(
                os.path.join(self.images_dir, f'illustration_{i + 1}.png'))
            foreground_paths.append(
                os.path.join(self.render_dir, f'scene_{i + 1}',
                             f'Scene{i+1}.mov'))
            audio_paths.append(
                os.path.join(self.tts_dir, f'segment_{i + 1}.mp3'))

            segment_subtitles = []
            j = 0
            while True:
                sub_path = os.path.join(self.subtitle_dir,
                                        f'bilingual_subtitle_{i + 1}_{j}.png')
                if os.path.exists(sub_path):
                    segment_subtitles.append(sub_path)
                    j += 1
                else:
                    break
            subtitle_paths.append(segment_subtitles)

            video_paths.append(
                os.path.join(self.videos_dir, f'video_{i + 1}.mp4'))

        self.compose_final_video(
            background_path=self.bg_path,
            foreground_paths=foreground_paths,
            audio_paths=audio_paths,
            subtitle_paths=subtitle_paths,
            illustration_paths=illustration_paths,
            video_paths=video_paths,
            segments=segments,
            output_path=final_video_path)
        return messages
