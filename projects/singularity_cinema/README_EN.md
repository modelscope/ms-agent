# SingularityCinema

A lightweight and excellent short video generator

## Installation

This project requires Python and Node.js environments.

1. **Prerequisites**
   - **Python**: Version >= 3.10 is required. Using [Conda](https://docs.conda.io/projects/conda/en/stable/user-guide/install/index.html) is recommended.
   - **Node.js**: Required if you use the default Remotion engine. Install [Node.js](https://nodejs.org/) (Version >= 16 recommended).
   - **FFmpeg**: Install [ffmpeg](https://www.ffmpeg.org/download.html#build-windows) and add it to your PATH.

2. **Clone Code**
   ```shell
   git clone https://github.com/modelscope/ms-agent.git
   cd ms-agent
   ```

3. **Install Python Dependencies**
   ```shell
   pip install .
   cd projects/singularity_cinema
   pip install -r requirements.txt
   ```

## Compatibility and Limitations

SingularityCinema generates scripts and storyboards based on large language models and produces short videos.

### Compatibility

- Short video types: Educational, economic videos, especially those containing charts, formulas, and principle explanations
- Language: No restrictions, subtitles and voice follow your original query and document materials
- Reading external materials: Supports plain text, does not support multimodal
- Secondary development: Complete code is in stepN/agent.py with no license restrictions, free for secondary development and commercial use
  - Please note and comply with the commercial licenses of background music and fonts you use

### Limitations

- LLM test range: Claude, effects with other models untested
- AIGC model test range: Qwen-Image, effects with other models untested

## Running

1. Prepare API Key

### Prepare LLM Key

Taking Claude as an example, you need to first apply for or purchase Claude model access. The Claude Key can be set in environment variables:

```shell
OPENAI_API_KEY=xxx-xxx
```

### Prepare ModelScope Text-to-Image Key

The default model is currently Qwen-Image. The ModelScope API Key can be applied for [here](https://www.modelscope.cn/my/myaccesstoken). Then set it in environment variables:

```shell
T2I_API_KEY=ms-xxx-xxx
```

### Prepare an MLLM to check animation layouts

```shell
MANIM_TEST_API_KEY=xxx-xxx
```

2. Prepare your short video materials

You can choose to generate a video with a single sentence, for example:

```text
Generate a short video describing GDP economic knowledge, approximately 3 minutes long.
```

Or use your previously collected text materials:

```text
Generate a short video describing large language model technology, read /home/user/llm.txt for detailed content
```

3. Run command

```shell
ms-agent run --config "projects/singularity_cinema" --query "Your custom theme, see description above" --load_cache true --trust_remote_code true
```

4. The run takes approximately 20 minutes. The video is generated at output/final_video.mp4. After generation, you can review this file, compile the parts that don't meet requirements, input them into the command line input, and the workflow will continue improving. If requirements are met, input quit or exit and the program will automatically terminate.

5. If the execution fails, such as URL call timeout or file generation failure, you can re-run the command above. ms-agent saves execution information in the output/memory folder, and after re-running the command, it will continue from where it failed.
    * If you want to regenerate from scratch, please rename or move the output folder elsewhere, or delete the corresponding memory and input files.
    * You can delete input files for only specific scenes/shots, so that re-execution will only process those corresponding scenes/shots. This is also the principle behind the manual feedback correction in the final step.

## Technical Principles

1. Generate basic script based on user requirements
    * Input: User requirements, may read user-specified files
    * Output: Script file script.txt, original requirement file topic.txt, short video name file title.txt
2. Split storyboard design based on script
    * Input: topic.txt, script.txt
    * Output: segments.txt, storyboard list describing narration, background image generation requirements, foreground manim animation requirements
3. Generate audio narration for storyboards
    * Input: segments.txt
    * Output: audio/audio_N.mp3 list, N is segment number starting from 1, and root directory audio_info.txt containing audio duration
4. Generate manim animation code based on voice duration
    * Input: segments.txt, audio_info.txt
    * Output: Manim code file list manim_code/segment_N.py, N is segment number starting from 1
5. Fix manim code
    * Input: manim_code/segment_N.py N is segment number starting from 1, code_fix/code_fix_N.txt error prediction file
    * Output: Updated manim_code/segment_N.py files
6. Render manim code
    * Input: manim_code/segment_N.py
    * Output: manim_render/scene_N folder list, if segments.txt contains manim requirements for a step, the corresponding folder will have a manim.mov file
7. Generate text-to-image prompts
    * Input: segments.txt
    * Output: illustration_prompts/segment_N.txt, N is segment number starting from 1
8. Text-to-image
    * Input: illustration_prompts/segment_N.txt list
    * Output: images/illustration_N.png list, N is segment number starting from 1
9. Generate subtitles
    * Input: segments.txt
    * Output: subtitles/bilingual_subtitle_N.png list, N is segment number starting from 1
10. Generate background, a solid color image with short video title and slogans
    * Input: title.txt
    * Output: background.jpg
11. Composite complete video
    * Input: All previous file information
    * Output: final_video.mp4
12. Human feedback

## Adjustable Parameters

Most adjustable parameters are in agent.yaml. Before running, you can modify this file for customization.

Some important parameters are listed below:

- llm: This group of parameters controls the LLM's url, apikey, etc.
- generation_config: This group of parameters controls LLM generation parameters
- prompt.system: Controls the system for script generation stage
  - If you want to modify the system for storyboard generation, you can modify the system in step2_segment/agent.py
- text2image: Text-to-image model parameters, including url, model id, etc.
  - t2i_transition: Background image effect, default is ken-burns effect
  - t2i_style: Image style, you can set your desired text-to-image style
- t2i_num_parallel: Text-to-image call parallelism. Default is 1 to prevent rate limiting
- llm_num_parallel: LLM call parallelism, default is 10
- video: Video generation bitrate and other parameters
- voice/voices: edge_tts voice settings, if you have other voice options, you can add them here
- subtitle_translate: Multilingual subtitle language, if not set, no translation is performed
- slogan: Displayed on the right side of the screen, generally shows producer name and short video collection
- fonts: The recommended fonts list
