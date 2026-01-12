# Copyright (c) Alibaba, Inc. and its affiliates.
import glob
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Union

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig
from PIL import Image

logger = get_logger()


class GenerateRemotionCode(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.num_parallel = getattr(self.config, 'llm_num_parallel', 10)
        self.images_dir = os.path.join(self.work_dir, 'images')
        self.remotion_code_dir = os.path.join(self.work_dir, 'remotion_code')
        os.makedirs(self.remotion_code_dir, exist_ok=True)

    async def execute_code(self, messages: Union[str, List[Message]],
                           **kwargs) -> List[Message]:
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)
        with open(os.path.join(self.work_dir, 'audio_info.txt'), 'r') as f:
            audio_infos = json.load(f)
        logger.info('Generating remotion code.')

        tasks = []
        for i, (segment, audio_info) in enumerate(zip(segments, audio_infos)):
            # "remotion" field takes precedence, fall back to "manim"
            animation_requirement = segment.get('remotion',
                                                segment.get('manim'))

            # Load visual plan if available
            visual_plan_path = os.path.join(self.work_dir, 'visual_plans',
                                            f'plan_{i+1}.json')
            visual_plan = {}
            if os.path.exists(visual_plan_path):
                try:
                    with open(visual_plan_path, 'r', encoding='utf-8') as f:
                        visual_plan = json.load(f)
                except Exception as e:
                    logger.warning(
                        f'Failed to load visual plan for segment {i+1}: {e}')
            else:
                # Robustness: if step5 failed to persist the plan, synthesize a minimal one
                # from the existing storyboard/manim requirement so downstream guidance exists.
                try:
                    os.makedirs(
                        os.path.dirname(visual_plan_path), exist_ok=True)

                    visual_plan = GenerateRemotionCode._synthesize_visual_plan_from_segment(
                        segment)
                    with open(visual_plan_path, 'w', encoding='utf-8') as f:
                        json.dump(visual_plan, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    logger.warning(
                        f'Failed to synthesize visual plan for segment {i+1}: {e}'
                    )

            if animation_requirement is not None:
                tasks.append(
                    (segment, audio_info['audio_duration'], i, visual_plan))

        remotion_code = [''] * len(segments)

        with ThreadPoolExecutor(max_workers=self.num_parallel) as executor:
            futures = {
                executor.submit(self._generate_remotion_code_static, seg, dur,
                                idx, self.config, self.images_dir, v_plan): idx
                for seg, dur, idx, v_plan in tasks
            }
            for future in as_completed(futures):
                idx = futures[future]
                remotion_code[idx] = future.result()

        for i, code in enumerate(remotion_code):
            remotion_file = os.path.join(self.remotion_code_dir,
                                         f'Segment{i + 1}.tsx')
            with open(remotion_file, 'w', encoding='utf-8') as f:
                f.write(code)
        return messages

    @staticmethod
    def _generate_remotion_code_static(segment, audio_duration, i, config,
                                       image_dir, visual_plan):
        """Static method for multiprocessing"""
        llm = LLM.from_config(config)
        return GenerateRemotionCode._generate_remotion_impl(
            llm, segment, audio_duration, i, image_dir, config, visual_plan)

    @staticmethod
    def get_image_size(filename):
        with Image.open(filename) as img:
            return f'{img.width}x{img.height}'

    @staticmethod
    def get_all_images_info(segment, i, image_dir):
        all_images_info = []

        foreground = segment.get('foreground', [])

        # Fallback: Check for existing foreground images even if not in segment info
        if not foreground:
            pattern = os.path.join(image_dir,
                                   f'illustration_{i + 1}_foreground_*.png')
            found_files = sorted(glob.glob(pattern))
            for fpath in found_files:
                # Extract index from filename to match expected structure if needed,
                # or just treat as a foreground image.
                # Filename format: illustration_{i+1}_foreground_{idx+1}.png
                try:
                    # Try to find a description file
                    base_name = os.path.basename(fpath)
                    desc_name = base_name.replace('.png', '.txt')
                    desc_path = os.path.join(
                        os.path.dirname(image_dir), 'illustration_prompts',
                        desc_name)
                    description = 'Foreground element'
                    if os.path.exists(desc_path):
                        with open(desc_path, 'r', encoding='utf-8') as df:
                            description = df.read().strip()

                    size = GenerateRemotionCode.get_image_size(fpath)
                    image_info = {
                        'filename': base_name,
                        'size': size,
                        'description': description,
                    }
                    all_images_info.append(image_info)
                except Exception as e:
                    logger.warning(
                        f'Error processing fallback image {fpath}: {e}')

        for idx, _req in enumerate(foreground):
            foreground_image = os.path.join(
                image_dir, f'illustration_{i + 1}_foreground_{idx + 1}.png')
            if os.path.exists(foreground_image):
                size = GenerateRemotionCode.get_image_size(foreground_image)
                image_info = {
                    'filename': os.path.basename(
                        foreground_image),  # Use basename for Remotion
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
    def _synthesize_visual_plan_from_segment(segment: dict) -> dict:
        """Best-effort plan synthesis when Visual Director plan files are missing.

        This keeps the pipeline deterministic and ensures the Remotion generator receives
        explicit beats/layout guidance even if step5 output is unavailable.
        """
        # "remotion" field takes precedence, fall back to "manim"
        animation_req = (segment.get('remotion') or segment.get('manim')
                         or '').strip()

        # Heuristic layout detection
        req_lower = animation_req.lower()
        if 'three-object' in req_lower or 'three object' in req_lower or 'left-middle-right' in req_lower:
            layout = 'Grid Layout'
        elif 'two-object' in req_lower or 'two object' in req_lower or 'left-right' in req_lower:
            layout = 'Asymmetrical Balance'
        else:
            layout = 'Center Focus'

        # Required short labels are often quoted in the animation requirement.
        # Keep them short to avoid subtitle-like paragraphs.
        quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", animation_req)
        required_labels: List[str] = []
        for a, b in quoted:
            s = (a or b or '').strip()
            if 1 <= len(s) <= 10 and re.search(r'[\u4e00-\u9fff]', s):
                required_labels.append(s)
        required_labels = list(dict.fromkeys(required_labels))[:2]

        label_hint = (f"Required label(s): {', '.join(required_labels)}"
                      if required_labels else '(No required label detected)')

        return {
            'background_concept':
            'Clean cinematic backdrop with empty center safe-area',
            'foreground_assets': [],
            'layout_composition':
            layout,
            'text_placement':
            'Centered keyword card within SAFE container',
            'visual_metaphor':
            f'{label_hint}. Map narration to 1-3 simple visual elements, no random effects.',
            'beats': [
                '0-25%: Establish the main visual(s) according to the requirement.',
                '25-80%: Add 1 supporting change/connection that matches the narration.',
                '80-100%: Resolve with the keyword/required label on a high-contrast card.',
            ],
            'motion_guide':
            'Use spring-based entrances + subtle camera drift; sequence elements by beats; avoid chaos.',
        }

    @staticmethod
    def _generate_remotion_impl(llm, segment, audio_duration, i, image_dir,
                                config, visual_plan):
        component_name = f'Segment{i + 1}'
        content = segment['content']
        # "remotion" field takes precedence, fall back to "manim"
        animation_requirement = segment.get('remotion',
                                            segment.get('manim', ''))
        images_info = GenerateRemotionCode.get_all_images_info(
            segment, i, image_dir)

        # Inject image info with code snippets.
        images_info_str = ''
        if images_info:
            images_info_str += 'Available Images (You MUST use these exact import/usage codes):\n'
            for img in images_info:
                fname = img['filename']
                w, h = img['size'].split('x')
                is_portrait = int(h) > int(w)
                style_hint = "maxHeight: '80%'" if is_portrait else "maxWidth: '80%'"

                images_info_str += f"- Name: {fname} ({img['size']}, {img['description']})\n"
                images_info_str += (
                    f"  USAGE CODE: <Img src={{staticFile(\"images/{fname}\")}} "
                    f"style={{{{ {style_hint}, objectFit: 'contain' }}}} />\n")
        else:
            images_info_str = 'No images offered. Use CSS shapes/Text only.'

        beats = visual_plan.get('beats', []) if visual_plan else []

        motion_guide_section = ''
        # Updated Visual Director logic
        # We now look for the new format from Step 5 (Visual Director).
        timeline_events = visual_plan.get('timeline_events', [])
        layout_mode = visual_plan.get(
            'layout_mode', visual_plan.get('layout_composition',
                                           'Center Focus'))

        timeline_text = ''
        if timeline_events:
            timeline_text = '**TIMELINE EXECUTION (Exact Timings)**:\n'
            for ev in timeline_events:
                t_str = f"{int(ev.get('time_percent', 0)*100)}%"
                timeline_text += f"- At {t_str} of video: {ev.get('action')}\n"

        metaphor_expl = visual_plan.get('visual_metaphor_explanation', '')
        asset_desc = visual_plan.get('main_visual_asset',
                                     {}).get('description', '')

        motion_guide_section = f"""
**VISUAL DIRECTOR'S BLUEPRINT (MANDATORY)**:
You are the animator. You MUST follow the Director's blueprint below.

0.  **SCENE CONTEXT**:
    *   Metaphor: {metaphor_expl}
    *   Main Asset Focus: {asset_desc}

1.  **LAYOUT MODE**: {layout_mode}
    *   Setup your CSS layout immediately based on this mode.
    *   **STABILITY FIRST**: Use standard Flexbox layouts (Row/Column).
        Avoid absolute positioning unless necessary.

2.  **TIMELINE & ACTION**:
{timeline_text or beats}
    *   **TIMING**: Use the exact times provided.

3.  **ENGINEERING RULES (VIOLATION = FAIL)**:
    *   **LAYOUT SYSTEM (ANTI-OVERLAP)**:
        *   **MANDATORY**: Use `display: 'flex'` and `flexDirection: 'column'`
            (or row) for the main container layout.
        *   **FORBIDDEN**: Do NOT place text and images both at
            `position: 'absolute', top: '50%', left: '50%'`. They WILL collide.
        *   **STRATEGY**:
            - Create a `FlexContainer` with `justifyContent: 'center', alignItems: 'center', gap: 50`.
            - Put Text in one logic block, Images in another.
        *   **SAFE AREA**: Wrap everything in a `<div style={{ width: '85%', height: '85%' }}>`.
            Never touch edges.

    *   **ASSET & TEXT VISIBILITY**:
        *   **Text on Images**: If text MUST overlap an image, the text container MUST have
            `backgroundColor: 'rgba(255,255,255,0.9)'` (if black text)
            or `rgba(0,0,0,0.7)` (if white text).
        *   **Z-Index**: Always set `zIndex: 10` for Text and `zIndex: 1` for Images.
        *   **Font Size**: Minimum `40px` for titles, `24px` for labels.

    *   **ASSET OVERLOAD PROTECTION**:
        *   If you have **3 or more images**:
            *   **MANDATORY**: Use a Grid layout (`display: 'grid', gridTemplateColumns: '1fr 1fr'`)
                or Flex Wrap.
            *   **SCALE DOWN**: Force image heights to max `250px`.
            *   If too many images for one row, wrap to a second row.

    *   **NO FULLSCREEN BACKGROUNDS**:
        *   The root container **MUST** be transparent. No `backgroundColor: 'white'`.
        *   We will composite a background later.
"""

        if config.foreground == 'image':
            image_usage = f"""**Image usage (CRITICAL: THESE ARE ASSETS, NOT BACKGROUNDS)**
- You'll receive an actual image list with three fields per image: filename, size, and description.
- Images will be placed in the `public/images` folder. You can reference them using
  `staticFile("images/filename")` or just string path if using `Img` tag with `src`.
- **THESE IMAGES ARE ISOLATED ELEMENTS** (e.g., a single icon, a character, a prop).
- **DO NOT** stretch them to fill the screen like a background wallpaper.
- **DO** position them creatively:
    *   Float them in 3D space.
    *   Slide them in from the side.
    *   Scale them up/down with `spring`.
    *   Use them as icons next to text.
- Pay attention to the size field, write Remotion code that respects the image's aspect ratio.
- IMPORTANT: If images files are not empty, **you MUST use them all**.
  These are custom-generated assets for this specific scene.
    *   If the image is a character or object, place it in the foreground.
    *   If you are unsure where to put it, center it and fade it in.
    *   **FAILURE TO USE PROVIDED IMAGES IS A CRITICAL ERROR.**
    *   Here is the image files list:

{images_info_str}

**CRITICAL WARNING**:
- **DO NOT HALLUCINATE IMAGES**. You MUST ONLY use the filenames listed above.
- If the list above is "No images offered.", you **MUST NOT** use any `Img` tags or `staticFile` calls.
  Use CSS shapes, colors, and text only.
- Do not invent filenames like "book.png", "city.png", etc. if they are not in the list.
- **FORBIDDEN BACKGROUND FILES**: Do NOT use any filename matching `illustration_*_background.png` even if it exists.
- **FORBIDDEN FULL-SCREEN BACKGROUND**: Never render a full-screen `Img` background.
  This pipeline composites background later.
- DO NOT let the image and the text/elements overlap. Reorganize them in your animation.
"""
        else:
            image_usage = ''

        prompt = f"""You are a **Senior Motion Graphics Designer** and **Instructional Designer**,
    creating high-end, cinematic, and beautiful educational animations using React (Remotion).
Your goal is to create a visual experience that complements the narration, NOT just subtitles on a screen.

**Task**: Create a Remotion component
- Component name: {component_name}
- Content (Narration): {content}
- Requirement: {animation_requirement}
- Duration: {audio_duration} seconds
- Code language: **TypeScript (React)**

{motion_guide_section}

{image_usage}

**Design & Animation Guidelines (CRITICAL for High-Quality Output):**
1.  **TRANSPARENT BACKGROUND (CRITICAL)**:
    *   The root container MUST be transparent. `style={{ backgroundColor: undefined }}`.
    *   **NEVER** use a solid background color (white/black) for the full screen.
    *   **NEVER** use a full-screen image as a background. (Background will be composed later.)
    *   **NEVER** use `staticFile("images/illustration_X_background.png")`.
    *   **DO NOT** set a solid background color (like white or black)
        on the main `AbsoluteFill` or container.
    *   **DO NOT** use `backgroundColor: 'black'` anywhere unless it's a small card.
    *   The animation will be overlaid on top of a background video/image in post-production.
    *   Only set background colors for specific UI cards or elements, not the whole screen.

2.  **NO VERBATIM TEXT (ABSOLUTELY FORBIDDEN)**:
    *   **STOP**: Do NOT put the narration text on the screen. I repeat: NO SUBTITLES.
    *   The audience listens to the audio. Reading the same text is boring.
    *   **ACTION**: Extract 1-3 keywords only.
        If the text is "The sky is blue", just show "BLUE".
    *   **ONLY** display **Keywords**, **Titles**, **Statistics**, or **Short Phrases** (3-5 words max)
        that reinforce the message.
    *   If the content is "100 people joined", DO NOT write that whole sentence. Write "100 People".
    *   **Visual Metaphors**: Translate the content into visuals.
        If the text mentions "history", show an old scroll or timeline element.
    *   **MEANINGFUL ANIMATION**: The animation must *tell the story*.
        If the script is about "growth", show a bar chart rising or a tree growing.
        If it's about "connection", show lines connecting dots.
        Don't just fly text in randomly.
    *   **EXCEPTION (REQUIRED SHORT LABELS)**:
                - If the **Requirement** or the **Visual Director plan/beats** explicitly demands an on-screen phrase,
                    you MUST show it.
        - Treat it as a **Keyword Label**, not a subtitle: keep it short, centered, and stable.
        - **High contrast only**: black text on an opaque white card. NO gradients for text.

3.  **High-End Motion Logic (Modern UI Style)**:
    *   **"Alive" Check**: Nothing should be completely static, BUT prevent chaos.
    *   **Sophisticated In-Place Motion**:
                - Instead of only flying across the screen, use **subtle 3D rotations** (`rotateY(15deg)`)
                    or **gentle breathing scales** (1.0 -> 1.02) to emphasize elements.
                - **Mask Reveals**: Text shouldn't just fade in; it should slide up from an invisible container
                    (`overflow: hidden`).
        - **Perspective Tilts**: `transform: perspective(1000px) rotateX(10deg)` adds depth without clutter.
    *   **Logical Staging**:
        - Enter elements in hierarchy order: Background -> Container -> Title -> Detail.
        - Use `sequence` heavily. Don't show everything at frame 0.
    *   **Camera Feel**: Use `interpolate` for very slow, elegant drifts
        (e.g., slight pan or zoom over 5 seconds). Not jerky.
    *   **Physics**: Use `spring` with higher mass/damping for a "weighted", expensive feel.
    *   **Staggered Animation**: Don't show 3 items at once. Show Item 1, wait 10 frames, Item 2, wait 10 frames...

        *   **EFFECT BUDGET (ANTI-CHAOS RULE)**:
                - Choose at most **3 motion motifs** for the whole segment and reuse them:
                    1) reveal (mask/slide), 2) emphasis (scale/pulse), 3) camera drift (subtle scale/position)
                - Avoid random spins/glitches unless the Visual Director explicitly asked.
                - Motions must follow the **beats** above (0-25%, 25-80%, 80-100%).

4.  **CODING RULES (STRICT)**:
    *   **NO TEMPLATE LITERALS FOR TRANSFORMS**: Do NOT use backticks for `transform` properties
        containing `interpolate`.
        *   BAD: `transform: \\`translateX(${{interpolate(...)}})px\\``
        *   GOOD: `transform: 'translateX(' + interpolate(...) + 'px)'`
        *   This is to prevent build errors with nested braces.
    *   **Use `interpolate` correctly**:
        `interpolate(frame, [0, 30], [0, 1], {{extrapolateRight: 'clamp'}})`.
    *   **Use `spring` correctly**:
        `const anim = spring({{ frame, fps, config: {{ damping: 200 }} }})`.

    *   **DETERMINISM (CRITICAL)**:
        - DO NOT use `Math.random()`, `Date.now()`, or any non-deterministic APIs inside render.
        - If you need pseudo-randomness, precompute it once (e.g., `useMemo`) with a fixed seed.


4.  **Clean Layout & Composition (STRICT)**:
    *   **NO OVERLAPPING (ZERO TOLERANCE)**:
        - Use `flex` containers or absolute positioning with explicit non-overlapping coordinates.
                - If using `AbsoluteFill`, define `left: 0, width: '50%'` for one element and
                    `left: '50%', width: '50%'` for the other.
                - **NEVER** place text directly on top of a complex image without a semi-transparent backing card
                    (`backgroundColor: 'rgba(0,0,0,0.7)'`).
    *   **Visual Hierarchy**: Make the most important element (keyword or main image) the largest.
    *   **Safe Zones**: Keep important text/images away from the very edges (50px padding).
    *   **Director's Layout**: Follow the `layout_composition` instruction above.

4.5 **SAFE AREA (CENTRAL 60% RULE, MLLM-CHECKED)**:
    *   All primary elements (keywords, icons, main shapes) MUST stay inside the central 60% of the frame.
    *   Implement this deterministically:
        - Define `const SAFE_PADDING_X = width * 0.2;` and `const SAFE_PADDING_Y = height * 0.2;`
        - Use a container: `const SAFE = {{ left: SAFE_PADDING_X, top: SAFE_PADDING_Y,
          width: width - 2*SAFE_PADDING_X, height: height - 2*SAFE_PADDING_Y }};`
        - Place your main layout inside a div with `position: 'absolute'` and these SAFE bounds.
    *   Do NOT put any text near edges/corners; do not use vertical text.

5.  **Visual Polish (Light Theme)**:
    *   **Color Palette**: Use a harmonious, light color scheme (whites, pastels, soft greys)
        with strong accent colors for text.
    *   **Shadows**: Add `boxShadow` or `textShadow` to create depth.
    *   **Gradients**: Use `linear-gradient` for text fills or element backgrounds to look rich.
    *   **Rounded Corners**: `borderRadius` makes UI elements look modern.
    *   **Typography**: Use large, bold fonts for titles. Ensure high contrast.

6.  **Code Requirements**:
    *   Canvas size: 1280x720 (16:9)
    *   Use `remotion` package components: `AbsoluteFill`, `Sequence`, `Img`, `Audio`, `Video`, `IFrame`.
    *   Use `remotion` hooks: `useCurrentFrame`, `useVideoConfig`, `spring`, `interpolate`, `measureSpring`.
    *   Export the component as default.
    *   The component should take no props or optional props.
    *   **IMPORTANT**: The output must be a valid React Functional Component.
    *   **IMPORTANT**: Do not include `Composition` or `registerRoot` in this file. Just the component.
    *   **IMPORTANT**: Assume images are in `public/images/`.
        Use `staticFile` from `remotion` to reference them if needed, e.g. `src={{staticFile("images/filename")}}`.
    *   **CRITICAL CODING RULE**: When using `interpolate`, the `inputRange` array MUST be strictly increasing
        (e.g., `[0, 10, 20]`). NEVER use unsorted arrays like `[0, 20, 10]`.
    *   **CRITICAL CODING RULE**: `inputRange` and `outputRange` in `interpolate` MUST have the same length.
    *   **CRITICAL CODING RULE**: In `interpolate`, `outputRange` values MUST be of the same type and unit.
        Do NOT mix numbers and strings (e.g., `[0, "10px"]` is INVALID).
        Do NOT mix units (e.g., `["0px", "10%"]` is INVALID).
    *   **CRITICAL REACT RULE**: NEVER render an object directly as a child
        (e.g., `<div>{{myObject}}</div>` will crash).
        Always render string/number properties (e.g., `<div>{{myObject.text}}</div>`).
    *   **VISIBILITY RULE**: Ensure all main elements are visible on screen.
        Avoid `opacity: 0` unless animating.
        Check `zIndex` to ensure foreground elements are not hidden behind backgrounds.
    *   **NO FLICKERING**: Do NOT use modulus-based flashing (e.g., `frame % 15`).
        For pulsing, use `Math.sin(frame / 10)` to create a smooth, high-quality breathing effect.

7.  **OFFLINE / WINDOWS FONT RULES (CRITICAL)**:
    *   This project runs in an offline Windows environment. **DO NOT** access the public Internet.
    *   **FORBIDDEN**:
        - Importing `@remotion/fonts`
                - Calling `loadFont()`
                - Any external URLs such as `https://fonts.googleapis.com/...`, `https://fonts.gstatic.com/...`,
                    or any remote `.woff/.ttf` downloads
    *   **REQUIRED**: Use system fonts only.
        - Default Chinese-friendly Windows font stack:
          `fontFamily: 'Microsoft YaHei, SimHei, SimSun, KaiTi, FangSong, Arial, sans-serif'`
        - For calligraphy feel, prefer `KaiTi` / `FangSong`.
    *   You may still use `fontWeight`, `letterSpacing`, `textShadow`, and gradients for visual polish.

8.  **TYPOGRAPHY CONSISTENCY (RECOMMENDED)**:
    *   For a consistent visual identity across segments, define ONE reusable constant near the top of the file
        and use it everywhere:
        - `const CN_FONT_STACK =
          'Microsoft YaHei, SimHei, SimSun, KaiTi, FangSong, Arial, sans-serif';`
    *   Then use `fontFamily: CN_FONT_STACK` for all text unless there is a strong reason not to.

**SELF-CORRECTION CHECKLIST (Before you output code)**:
1.  Did I put the full text on screen? -> If YES, delete it and keep only keywords.
2.  Did I add a white background? -> If YES, remove it.
3.  Are elements overlapping? -> If YES, move them apart. **ZERO TOLERANCE**.
4.  Did I use `display: flex` instead of absolute positioning? -> If NO, rewrite using Flexbox.
5.  Did I use the foreground images as a background wallpaper? -> If YES, change it to a floating element.
6.  Did I follow the Visual Director's Layout & Motion Guide? -> If NO, rewrite the animation to match the guide.
7.  Is the animation meaningful? -> If NO, add visual metaphors related to the script.
8.  Is it flickering? -> If YES, replace `frame %` with `Math.sin` for a smooth pulse.

**UNIVERSAL COMPONENT TEMPLATE**:
You SHOULD structure your component like this to prevent layout issues:

```tsx
import React from 'react';
import {{
    AbsoluteFill,
    useCurrentFrame,
    useVideoConfig,
    Img,
    staticFile,
    interpolate,
    spring,
}} from 'remotion';

export const SegmentX = () => {{
  const frame = useCurrentFrame();
  const {{ fps }} = useVideoConfig();

  // 1. Safe Area Container (85% size, Centered)
  // 2. Flexbox Layout (Column or Row) for Separation
  return (
        <AbsoluteFill
            style={{{{
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                backgroundColor: undefined,
            }}}}
        >
       <div style={{{{
          display: 'flex',
          flexDirection: 'column', // or 'row'
          width: '85%',
          height: '85%',
          justifyContent: 'space-around', // Distribute space
          alignItems: 'center',
          gap: 40
       }}}}>
        <div className="text-zone"
            style={{{{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center' }}}}>
              {{/* TEXT GOES HERE */}}
          </div>
        <div className="visual-zone"
            style={{{{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center' }}}}>
              {{/* IMAGES GO HERE */}}
          </div>
       </div>
    </AbsoluteFill>
  );
}};
```

**CRITICAL IMAGE RULE**:
All `<Img />` tags MUST have this style to prevent overflow:
`style={{{{ maxWidth: '80%', maxHeight: '50%', objectFit: 'contain' }}}}`

Please create Remotion code that meets the above requirements and creates a visually stunning animation.
"""

        logger.info(f'Generating remotion code for: {content}')
        _response_message = llm.generate(
            [Message(role='user', content=prompt)], temperature=0.3)
        response = _response_message.content

        # Robust code extraction using regex
        code_match = re.search(
            r'```(?:typescript|tsx|js|javascript)?\s*(.*?)```', response,
            re.DOTALL)
        if code_match:
            code = code_match.group(1)
        else:
            # Fallback: if no code blocks, assume the whole response is code
            # but try to strip leading/trailing text if it looks like markdown
            code = response
            if 'import React' in code:

                # Try to find the start of the code
                idx = code.find('import React')
                code = code[idx:]

        code = code.strip()

        # Post-process for offline Windows compatibility (deterministic safety net)
        code = GenerateRemotionCode._strip_external_font_loading(code)
        return code

    @staticmethod
    def _strip_external_font_loading(code: str) -> str:
        """Remove external font loading patterns that break offline environments.

        If the LLM imports `@remotion/fonts` and calls `loadFont()` with a Google Fonts CSS URL,
        Remotion will crash at runtime while evaluating compositions.
        We remove the import and top-level loadFont() calls. Keeping `fontFamily` styles is safe.
        """
        try:
            if 'fonts.googleapis.com' not in code and 'fonts.gstatic.com' not in code and '@remotion/fonts' not in code:
                return code

            # Remove import of loadFont
            code = re.sub(
                r"^\s*import\s*\{\s*loadFont\s*\}\s*from\s*['\"]@remotion/fonts['\"];\s*\n",
                '',
                code,
                flags=re.MULTILINE,
            )

            # Remove any top-level loadFont({...}); blocks (best-effort)
            code = re.sub(
                r'^\s*loadFont\(\{[\s\S]*?\}\);\s*\n\s*\n',
                '',
                code,
                flags=re.MULTILINE,
            )
            code = re.sub(
                r'^\s*//\s*Load.*\n\s*loadFont\(\{[\s\S]*?\}\);\s*\n\s*\n',
                '',
                code,
                flags=re.MULTILINE,
            )

            # As an extra guard, replace any remaining google font URLs with empty string
            code = code.replace('https://fonts.googleapis.com/', '')
            code = code.replace('https://fonts.gstatic.com/', '')
            return code
        except Exception:
            return code
