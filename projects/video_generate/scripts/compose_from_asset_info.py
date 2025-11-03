import os
import sys

import json
# Import core workflow from the current package root (projects/video_generate)
from core import workflow as video_workflow

# Allow running as a standalone helper
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main(asset_info_path: str):
    if not os.path.exists(asset_info_path):
        print(f'asset_info.json not found: {asset_info_path}')
        sys.exit(1)
    with open(asset_info_path, 'r', encoding='utf-8') as f:
        asset_info = json.load(f)

    topic = asset_info['topic']
    full_output_dir = asset_info['output_dir']
    segments = asset_info['segments']
    asset_paths = asset_info['asset_paths']

    # Generate background with correct font
    background_path = video_workflow.create_manual_background(
        title_text=topic, output_dir=full_output_dir, topic=topic)

    final_video_path = os.path.join(full_output_dir, 'final_video.mp4')
    print(f'Composing to: {final_video_path}')

    composed_path = video_workflow.compose_final_video(
        background_path=background_path,
        foreground_paths=asset_paths['foreground_paths'],
        audio_paths=asset_paths['audio_paths'],
        subtitle_paths=asset_paths['subtitle_paths'],
        illustration_paths=asset_paths['illustration_paths'],
        segments=segments,
        output_path=final_video_path,
        subtitle_segments_list=asset_paths['subtitle_segments_list'],
    )

    print(f'Result: {composed_path}')


if __name__ == '__main__':
    # Default to last test topic path
    default_asset = os.path.join(ROOT, 'output', 'llm是什么', 'asset_info.json')
    asset_path = sys.argv[1] if len(sys.argv) > 1 else default_asset
    main(asset_path)
