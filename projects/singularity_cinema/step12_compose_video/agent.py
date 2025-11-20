# Copyright (c) Alibaba, Inc. and its affiliates.
import os

import json
import moviepy as mp
from moviepy import AudioClip
from ms_agent.agent import CodeAgent
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
        self.transition = getattr(self.config.text2image, 't2i_transition',
                                  None)
        self.bg_path = os.path.join(self.work_dir, 'background.jpg')
        self.render_dir = os.path.join(self.work_dir, 'manim_render')
        self.tts_dir = os.path.join(self.work_dir, 'audio')
        self.images_dir = os.path.join(self.work_dir, 'images')
        self.subtitle_dir = os.path.join(self.work_dir, 'subtitles')
        self.bitrate = getattr(self.config.video, 'bitrate', '5000k')
        self.preset = getattr(self.config.video, 'preset', 'ultrafast')
        self.fps = getattr(self.config.video, 'fps', 24)

    def compose_final_video(self, background_path, foreground_paths,
                            audio_paths, subtitle_paths, illustration_paths,
                            segments, output_path):
        segment_durations = []
        total_duration = 0
        logger.info('Composing the final video.')

        for i, audio_path in enumerate(audio_paths):
            actual_duration = 2.0  # Reduced minimum duration from 3.0 to 2.0 seconds

            if audio_path and os.path.exists(audio_path):
                try:
                    audio_clip = mp.AudioFileClip(audio_path)
                    # Use actual audio duration + small pause, no minimum enforcement
                    actual_duration = audio_clip.duration + 0.3  # Add 0.3s natural pause between sentences
                    audio_clip.close()
                except:  # noqa
                    actual_duration = 2.0

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
            total_duration += actual_duration

        logger.info(
            f'Total duration: {total_duration:.1f}s，{len(segment_durations)} segments.'
        )
        logger.info('Step1: Compose video for each segment.')
        segment_videos = []

        for i, (duration,
                segment) in enumerate(zip(segment_durations, segments)):
            logger.info(
                f'Processing {i + 1} segment - {duration:.1f} seconds.')

            current_video_clips = []

            if background_path and os.path.exists(background_path):
                bg_clip = mp.ImageClip(background_path, duration=duration)
                bg_clip = bg_clip.resized((1920, 1080))
                current_video_clips.append(bg_clip)

            if i < len(illustration_paths
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

                if self.transition == 'ken-burns-effect':
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

                elif self.transition == 'slide':
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

            if i < len(foreground_paths
                       ) and foreground_paths[i] and os.path.exists(
                           foreground_paths[i]):
                fg_clip = mp.VideoFileClip(foreground_paths[i], has_mask=True)
                original_w, original_h = fg_clip.size
                available_w, available_h = 1250, 700
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

            if i < len(
                    subtitle_paths) and subtitle_paths[i] and os.path.exists(
                        subtitle_paths[i]):
                subtitle_img = Image.open(subtitle_paths[i])
                subtitle_w, subtitle_h = subtitle_img.size

                # Validate subtitle dimensions
                if subtitle_w <= 0 or subtitle_h <= 0:
                    logger.error(
                        f'Invalid subtitle dimensions: {subtitle_w}x{subtitle_h} for {subtitle_paths[i]}'
                    )
                else:
                    subtitle_clip = mp.ImageClip(
                        subtitle_paths[i], duration=duration)
                    subtitle_clip = subtitle_clip.resized(
                        (subtitle_w, subtitle_h))
                    subtitle_y = 900
                    subtitle_clip = subtitle_clip.with_position(
                        ('center', subtitle_y))
                    current_video_clips.append(subtitle_clip)

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
            for i, (audio_path, duration) in enumerate(
                    zip(audio_paths, segment_durations)):
                if audio_path and os.path.exists(audio_path):
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
                    valid_audio_clips.append(audio_clip)

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

            bg_music_path = os.path.join(
                os.path.dirname(__file__), 'bg_audio.mp3')
            if os.path.exists(bg_music_path):
                bg_music = mp.AudioFileClip(bg_music_path)
                if bg_music.duration < final_video.duration:
                    repeat_times = int(
                        final_video.duration / bg_music.duration) + 1
                    bg_music = mp.concatenate_audioclips([bg_music]
                                                         * repeat_times)
                    bg_music = bg_music.subclipped(0, final_video.duration)
                elif bg_music.duration > final_video.duration:
                    bg_music = bg_music.subclipped(0, final_video.duration)
                bg_music = bg_music.with_volume_scaled(0.4)
                if final_video.audio:
                    tts_audio = final_video.audio.with_duration(
                        final_video.duration).with_volume_scaled(1.0)
                    bg_audio = bg_music.with_duration(
                        final_video.duration).with_volume_scaled(0.15)
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

        if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            test_clip = mp.VideoFileClip(output_path)
            actual_duration = test_clip.duration
            test_clip.close()
            if abs(actual_duration - final_video.duration) >= 1.0:
                raise RuntimeError('Duration not match')

    async def execute_code(self, messages, **kwargs):
        final_name = 'final_video.mp4'
        final_video_path = os.path.join(self.work_dir, final_name)
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)

        foreground_paths = []
        audio_paths = []
        subtitle_paths = []
        illustration_paths = []
        for i, segment in enumerate(segments):
            illustration_paths.append(
                os.path.join(self.images_dir, f'illustration_{i + 1}.png'))
            foreground_paths.append(
                os.path.join(self.render_dir, f'scene_{i + 1}',
                             f'Scene{i+1}.mov'))
            audio_paths.append(
                os.path.join(self.tts_dir, f'segment_{i + 1}.mp3'))
            subtitle_paths.append(
                os.path.join(self.subtitle_dir,
                             f'bilingual_subtitle_{i + 1}.png'))

        self.compose_final_video(
            background_path=self.bg_path,
            foreground_paths=foreground_paths,
            audio_paths=audio_paths,
            subtitle_paths=subtitle_paths,
            illustration_paths=illustration_paths,
            segments=segments,
            output_path=final_video_path)
        return messages
