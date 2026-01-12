# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional, Union

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


@dataclass
class Pattern:

    name: str
    pattern: str
    tags: List[str] = field(default_factory=list)


class GenerateIllustrationPrompts(CodeAgent):

    # Background prompt generator (t2i)
    system = """You are a prompt engineer for generating a SINGLE background image for a short-form video.

Requirements:
- Output ONLY one concise English prompt. No markdown, no JSON, no explanations.
- The background should be cinematic and cohesive.
- IMPORTANT: Leave the CENTER area visually clean/empty (safe area) for overlay animation (Remotion).
- Avoid clutter and tiny unreadable details.
"""

    # Foreground prompt generator (t2i)
    system_foreground = """You are a prompt engineer for generating a SINGLE foreground asset.

Rules:
- Output ONLY one concise English prompt. No markdown, no JSON, no explanations.
- ISOLATED OBJECT: single object on WHITE background (or solid color).
- Sticker / high-quality 3D icon style.
- NO SCENES, no environment, no text.
"""

    # Visual Director plan generator (JSON plan per segment)
    system_visual_director = """You are a Visual Director and Storyboard Artist for a high-end motion graphics video.

Analyze the given narration segment and its animation requirement.
Return ONE JSON object ONLY (no markdown fences, no extra text) with the following keys:
- background_concept: string (describe an abstract/cinematic background concept;
    keep the CENTER area empty for overlays)
- foreground_assets: array of 0-1 strings (specific physical objects/props; if none, [])
- layout_composition: one of [
    "Center Focus",
    "Split Screen (Left Text/Right Image)",
    "Split Screen (Right Text/Left Image)",
    "Grid Layout",
    "Asymmetrical Balance"
]
- text_placement: string (where short keyword labels should go)
- visual_metaphor: string (1 sentence mapping meaning -> visuals)
- beats: array of 3 strings (0-25%, 25-80%, 80-100% story beats)
- motion_guide: string (simple deterministic motion guidance)

Constraints:
- Prefer simple, clean composition; no chaos.
- Beats must be time-ordered.
- Foregrounds strictly limited to 0 (none) or 1 (focus object).
"""

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.num_parallel = getattr(self.config, 'llm_num_parallel', 10)
        self.illustration_prompts_dir = os.path.join(self.work_dir,
                                                     'illustration_prompts')
        self.visual_plans_dir = os.path.join(self.work_dir, 'visual_plans')
        os.makedirs(self.illustration_prompts_dir, exist_ok=True)
        os.makedirs(self.visual_plans_dir, exist_ok=True)

    async def execute_code(self, messages: Union[str, List[Message]],
                           **kwargs) -> List[Message]:
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)
        logger.info('Generating illustration prompts.')

        tasks = [(i, segment) for i, segment in enumerate(segments)]

        with ThreadPoolExecutor(max_workers=self.num_parallel) as executor:
            futures = {
                executor.submit(self._generate_illustration_prompts_static, i,
                                segment, self.config,
                                self.illustration_prompts_dir,
                                self.visual_plans_dir): i
                for i, segment in tasks
            }
            for future in as_completed(futures):
                future.result()
        return messages

    @staticmethod
    def _generate_illustration_prompts_static(i, segment, config,
                                              illustration_prompts_dir,
                                              visual_plans_dir):
        """Static method for multiprocessing"""
        llm = LLM.from_config(config)

        # 1. Read Visual Plan from Step 5.
        # The new Visual Director (Step 5) has already generated the plan.
        # We just need to load it. If it doesn't exist, we fallback.
        plan_path = os.path.join(visual_plans_dir, f'plan_{i+1}.json')
        visual_plan = {}
        if os.path.exists(plan_path):
            try:
                with open(plan_path, 'r', encoding='utf-8') as f:
                    visual_plan = json.load(f)
            except Exception as e:
                logger.warning(
                    f'Failed to load visual plan for segment {i+1}: {e}')

        # If plan is missing or empty, use fallback/legacy generation
        # But ideally, Step 5 guaranteed this file exists.

        max_retries = 10
        if config.background == 'image':
            for attempt in range(max_retries):
                try:
                    GenerateIllustrationPrompts._generate_illustration_impl(
                        llm, i, segment, visual_plan, illustration_prompts_dir)
                    break
                except Exception:
                    time.sleep(2)

        if config.foreground == 'image':
            for attempt in range(max_retries):
                try:
                    GenerateIllustrationPrompts._generate_foreground_impl(
                        llm, i, segment, visual_plan, illustration_prompts_dir)
                    break
                except Exception:
                    time.sleep(2)

    @staticmethod
    def _generate_illustration_impl(llm, i, segment, visual_plan,
                                    illustration_prompts_dir):
        if os.path.exists(
                os.path.join(illustration_prompts_dir, f'segment_{i+1}.txt')):
            return

        # NEW: Prefer Visual Director's concept
        background_concept = visual_plan.get('background_concept')
        if not background_concept:
            background_concept = segment.get('background',
                                             'Abstract cinematic background')

        logger.info(
            f'Generating background prompt from plan: {background_concept}')

        query = f'Generate a background prompt based on concept: {background_concept}.'
        inputs = [
            Message(role='system', content=GenerateIllustrationPrompts.system),
            Message(role='user', content=query),
        ]

        response = llm.generate(inputs).content.strip()

        # Strip thinking tags
        response = re.sub(
            r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()

        with open(
                os.path.join(illustration_prompts_dir, f'segment_{i + 1}.txt'),
                'w') as f:
            f.write(response)

    @staticmethod
    def _generate_foreground_impl(llm, i, segment, visual_plan,
                                  illustration_prompts_dir):
        # NEW: Prefer Visual Director's assets
        foreground_assets = []

        # 1. Check for new 'visual_assets' list (Multi-asset support)
        if 'visual_assets' in visual_plan and isinstance(
                visual_plan['visual_assets'], list):
            foreground_assets = [
                a.get('description') for a in visual_plan['visual_assets']
                if a.get('description')
            ]

        # 2. Fallback to old 'main_visual_asset' (Single asset)
        elif 'main_visual_asset' in visual_plan:
            main_asset = visual_plan.get('main_visual_asset', {})
            if main_asset and isinstance(
                    main_asset, dict) and main_asset.get('description'):
                foreground_assets.append(main_asset.get('description'))

        # 3. Fallback to segment config
        if not foreground_assets and segment.get('foreground'):
            foreground_assets = segment.get('foreground')

        # Limit to 1 foreground asset based on user preference for clean visuals
        if len(foreground_assets) > 1:
            foreground_assets = foreground_assets[:1]

        for idx, asset_desc in enumerate(foreground_assets):
            file_path = os.path.join(illustration_prompts_dir,
                                     f'segment_{i+1}_foreground_{idx+1}.txt')
            if os.path.exists(file_path):
                continue

            logger.info(
                f'Generating foreground_{idx} prompt from plan: {asset_desc}')

            query = (
                f'Design a single foreground asset: {asset_desc}. '
                f'Rules: ISOLATED OBJECT on white background, 8k, high quality 3D icon style.'
            )

            inputs = [
                Message(
                    role='system',
                    content=GenerateIllustrationPrompts.system_foreground),
                Message(role='user', content=query),
            ]

            response = llm.generate(inputs).content.strip()

            # Strip thinking tags
            response = re.sub(
                r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()

            with open(file_path, 'w') as f:
                f.write(response)
