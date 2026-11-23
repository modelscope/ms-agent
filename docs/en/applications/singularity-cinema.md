# Singularity Cinema

Singularity Cinema turns topics or text material into scripts, segments, narration, images/animation, and finished video. It suits explanatory content. Review facts, visuals, subtitles, audio, and asset licenses before publication.

## From material to video

```{mermaid}
flowchart TD
 A[Script and source material] --> B[Segments and narration]
 B --> C[Images and animation]
 C --> D[Optional video clips]
 D --> E[Subtitles, background and composition]
```

The thirteen nodes in current `workflow.yaml` form five ordered stages:

| Stage | Nodes |
| --- | --- |
| Script and material | Generate script → Parse document images |
| Narration | Segment → Generate audio |
| Visuals | Illustration prompts → Generate images → Generate animation → Render animation |
| Video clips | Video prompts → Generate video clips |
| Composition | Generate subtitles → Create background → Compose video |

Some nodes skip work depending on flags; thirteen nodes do not mean thirteen paid generation requests on every run.

## Environment and services

Install `pip install -e '.[cinema]'` from the source root and prepare FFmpeg. Remotion requires Node.js/rendering dependencies; Manim has its own system requirements. Check the chosen engine rather than treating WebUI requirements as the complete video environment.

Configure the main LLM, multimodal quality-check model, image service, and video service if enabled. Example models in `projects/singularity_cinema/agent.yaml` may not be available at the default endpoint. Replace each with a combination your account can access.

## Key options

| Field | Current project default | Purpose |
| --- | --- | --- |
| animation_engine | remotion | Animation engine |
| use_doc_image | true | Use document images |
| use_subtitle | false | Subtitles |
| use_text2video | false | Text-to-video clips |
| use_video_soundtrack | false | Video soundtrack |
| t2i_num_parallel | 5 | Image-generation concurrency |
| t2v_num_parallel | 1 | Video-generation concurrency |
| video.fps | 24 | Frame rate |

These are project defaults, not global tool defaults. Consider rate limits, cost, and memory before increasing concurrency.

## First run

Configure credentials/models in the project YAML, then run from the repository root:

```bash
ms-agent run --config projects/singularity_cinema/workflow.yaml \
  --query 'Create a short educational video about the water cycle' \
  --output_dir ./cinema-output --trust_remote_code true
```

Custom nodes require code trust. Start small without enabling every generation branch. Document input, image extraction, and model vision are separate paths; arbitrary multimodal documents are not universally supported.

## Inspect and retry

Keep script, segmented audio, images, intermediate renders, and final video. Follow paths printed by the run. When rate-limited, identify the failed node and existing artifacts/cache before retrying to avoid duplicate cost.

Fonts, music, and images can carry separate licenses. Review before publishing. Existing [examples and video showcases](https://github.com/modelscope/ms-agent/tree/main/projects/singularity_cinema) remain available; historical model combinations are not guarantees of current optimal settings.
