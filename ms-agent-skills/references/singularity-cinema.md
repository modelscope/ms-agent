# Video Generation (SingularityCinema) Capability

## When to Use

Activate this capability when the user asks to:
- Generate a short video from a text description
- Create an explainer or educational video
- Convert a document or article into a video format
- Produce a video with AI-generated images, narration, and animation

## Async Tools (Recommended)

### Tool: `submit_video_generation_task`

Starts video generation in the background. Returns immediately with a `task_id`.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | -- | Description of the video to generate |
| `config_path` | string | no | bundled | Path to singularity_cinema config |
| `output_dir` | string | no | auto | Directory for video outputs |
| `llm_model` | string | no | -- | LLM model name for script generation |
| `llm_api_key` | string | no | -- | API key for the LLM provider |
| `llm_base_url` | string | no | -- | OpenAI-compatible base URL |
| `image_generator_type` | string | no | -- | Provider: `modelscope`, `dashscope`, `google` |
| `image_generator_model` | string | no | -- | Image generation model name |
| `image_generator_api_key` | string | no | -- | API key for image generator |

**Returns:**
```json
{
  "task_id": "a1b2c3d4",
  "status": "running",
  "output_dir": "/path/to/output/video_generation_20260407_143000",
  "message": "Video generation task a1b2c3d4 started..."
}
```

### Tool: `check_video_generation_progress`

Polls status and reports pipeline step completion.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `task_id` | string | yes | The task_id from submit_video_generation_task |

**Returns:**
```json
{
  "task_id": "a1b2c3d4",
  "status": "running",
  "completed_steps": ["generate_script", "segment", "generate_audio", "generate_prompts"],
  "total_steps": 9,
  "images_generated": 6,
  "audio_segments": 6,
  "final_video_ready": false
}
```

### Tool: `get_video_generation_result`

Retrieves the final video path and pipeline artifacts.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `task_id` | string | yes | The task_id from submit_video_generation_task |

**Returns (on completion):**
```json
{
  "task_id": "a1b2c3d4",
  "status": "completed",
  "video_path": "/path/to/output/final_video.mp4",
  "video_size_mb": 45.2,
  "completed_steps": ["generate_script", "segment", "...all 9..."],
  "images_generated": 8,
  "audio_segments": 8,
  "script": "Script content preview..."
}
```

## SOP Workflow

### Step 1: Clarify Video Requirements

Ask the user:
- What topic should the video cover?
- Any reference materials (local text files)?
- Preferred language (follows the query language)?
- Desired style or visual theme?
- Approximate length (e.g., ~3 minutes)?

### Step 2: Submit the Task

```
submit_video_generation_task(
    query="Create a short video about GDP economics, about 3 minutes",
    image_generator_type="google",
    image_generator_model="gemini-3-pro-image-preview"
)
```

Tell the user:
> "I've started generating the video (ID: a1b2c3d4). This typically takes
> ~20 minutes as it generates scripts, images, audio, animations, and
> composes the final video."

### Step 3: Monitor Progress

```
check_video_generation_progress(task_id="a1b2c3d4")
```

Report: "4/9 steps completed (script, segmentation, audio, image prompts).
6 images generated so far."

### Step 4: Retrieve Result

```
get_video_generation_result(task_id="a1b2c3d4")
```

The result includes the video path and script content.

## Pipeline Steps (9 total)

| Step | Input | Output | Description |
|------|-------|--------|-------------|
| 1. generate_script | User query | script.txt, title.txt | Generate narration script |
| 2. segment | script.txt | segments.txt | Split into segments with visual cues |
| 3. generate_audio | segments.txt | audio/segment_N.mp3 | TTS for each segment |
| 4. generate_prompts | segments.txt | illustration_prompts/ | Image generation prompts |
| 5. generate_images | prompts | images/ | AI-generated background/foreground images |
| 6. generate_animation | segments, audio_info | remotion_code/ | Remotion animation code |
| 7. render_animation | remotion_code | remotion_render/ | Render animations to video clips |
| 8. create_background | title.txt | background.jpg | Title/background image |
| 9. compose_video | all artifacts | final_video.mp4 | Final video assembly |

## Output Structure

```
output_dir/
├── script.txt               # Generated narration script
├── title.txt                 # Video title
├── topic.txt                 # Original query/topic
├── segments.txt              # Segment breakdown
├── audio/                    # Narration audio files
│   ├── segment_1.mp3
│   └── segment_N.mp3
├── images/                   # Generated images
├── illustration_prompts/     # Image generation prompts
├── remotion_code/            # Animation source code
├── remotion_render/          # Rendered animation clips
├── background.jpg            # Title background
└── final_video.mp4           # Final output video
```

## Prerequisites

- **Python** >= 3.10
- **Node.js** >= 16 (for Remotion animation rendering)
- **FFmpeg** installed and on PATH
- **API keys**: LLM provider + image generation provider

## Model Configuration

The video pipeline requires three model types:

| Model Type | Purpose | Example |
|---|---|---|
| LLM | Script & animation code | claude-sonnet-4-5, gemini-3-pro |
| MLLM (multimodal) | Quality checking | gemini-3-pro |
| Image Generator | Background/foreground images | gemini-3-pro-image-preview |

## Notes

- The pipeline supports **resume from failure**: re-run the same command
  and it picks up from where it left off.
- To regenerate specific segments, delete the corresponding output files
  and re-run.
- Different LLM/image models produce varying quality. The README lists
  verified combinations.
- The compose step may appear to hang (no logs) while FFmpeg renders --
  this is normal.
