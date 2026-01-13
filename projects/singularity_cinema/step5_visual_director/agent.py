# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import os
import re
from typing import List, Union

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class VisualDirector(CodeAgent):
    """
    Step 5: Visual Director
    Responsible for creating a detailed Scene Action Plan (JSON) for each segment.
    It bridges the gap between Script/Audio and Visual Assets/Animation.
    """

    system_prompt = """You are the **Lead Visual Director** creating a premium, logic-driven animation sequence.
Your job is to translate a narration script into a concrete **Scene Action Plan**.

**Core Philosophy: "Structural & Expressive Logic"**:
- **Logic-First**: Animation reveals relationships. (e.g., "A causes B" -> A pulses, B slides out from A).
- **In-Place Sophistication**: Don't just fly things in/out. Use **stationary dynamics** to hold attention:
    - *Perspective*: Slight 3D rotations (Y-axis)
      to show depth or change focus.
    - *Breathing*: Gentle scaling to show "aliveness" or importance.
    - *Focus*: Blur unrelated elements when a new keyword appears.
- **Refined Transitions**: Avoid chaotic swooshes. Use crisp, spring-based reveals (Mask reveals, Staggered lists).
- **The "Premium" Feel**: Minimalist, confident, and smooth. No bouncing cartoon physics.

**Output format**:
You must output a SINGLE JSON object. No markdown fences. Keys:
{
  "layout_mode": "Split_LeftText_RightImage" | "Split_RightText_LeftImage" | "Center_Focus",
  "background_concept": "Description of the abstract background. CLEAN, DARK, MINIMAL.",
  "visual_assets": [
    {
      "type": "illustration" | "prop" | "icon",
      "description": "Precise description of ONE foreground object. "
                     "ISOLATED on white/transparent background. Keywords: 'Iconic', '3D Render', 'Minimalist'. "
                     "DO NOT REQUEST TEXT.",
      "placement": "Center"
    }
  ],
  "visual_metaphor_explanation": "One sentence explaining why this visual fits the script.",
  "keywords_to_highlight": ["ShortKeyword1"],
  "transition_from_prev": "Standard Fade In",
  "timeline_events": [
    { "time_percent": 0.1, "action": "Timeline bar expands from center" },
    { "time_percent": 0.3, "action": "Map icon rotates 15deg Y-axis to face camera" },
    { "time_percent": 0.8, "action": "Text slides up from mask, icon drifts back" }
  ]
}

**Design Rules**:
1.  **Simplicity**: Prioritize 1 strong visual idea over many weaker ones.
2.  **Asset Limit**: Request 0 or 1 foreground asset only.
3.  **Clarity**: Ensure text and visuals never compete for attention. Use standard layouts (Left/Right or Center).
4.  **No Text in Images**: Request PURE visual assets only.
"""

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.num_parallel = getattr(self.config, 'llm_num_parallel', 10)
        self.visual_plans_dir = os.path.join(self.work_dir, 'visual_plans')
        os.makedirs(self.visual_plans_dir, exist_ok=True)
        self.llm = LLM.from_config(self.config)

    async def execute_code(self, messages: Union[str, List[Message]],
                           **kwargs) -> List[Message]:
        # Load segments and audio info
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)
        with open(os.path.join(self.work_dir, 'audio_info.txt'), 'r') as f:
            audio_infos = json.load(f)

        logger.info(
            'Visual Director is planning the scenes (Sequential for Continuity)...'
        )

        previous_plan_summary = 'Start of video. Screen is blank.'
        for i, (segment, audio_info) in enumerate(zip(segments, audio_infos)):
            try:
                # Generate plan for this segment
                plan_content = await self._generate_visual_plan(
                    segment, audio_info['audio_duration'], i,
                    previous_plan_summary)

                # Parse and save
                try:
                    plan = json.loads(plan_content)

                    # Update context for next iteration
                    assets = plan.get('visual_assets', [])
                    if isinstance(assets, list) and assets:
                        descriptions = [
                            a.get('description', 'asset') for a in assets
                        ]
                        asset_desc = ', '.join(descriptions)
                    else:
                        asset_desc = plan.get('main_visual_asset',
                                              {}).get('description',
                                                      'Unknown asset')

                    layout = plan.get('layout_mode', 'Center')
                    previous_plan_summary = f'Previous Layout: {layout}. Previous Assets used: {asset_desc}.'

                except json.JSONDecodeError:
                    logger.warning(
                        f'Segment {i} produced invalid JSON. Using fallback context.'
                    )
                    previous_plan_summary = 'Previous segment had a glitch.'

                if isinstance(plan_content, str):
                    visual_plan_path = os.path.join(self.visual_plans_dir,
                                                    f'plan_{i+1}.json')
                    with open(visual_plan_path, 'w', encoding='utf-8') as f:
                        f.write(plan_content)
                else:
                    logger.error(
                        f'Generate visual plan returned non-string for segment {i}.'
                    )

            except Exception as e:
                logger.error(f'Error planning segment {i}: {e}')

        return messages

    async def _generate_visual_plan(self, segment, audio_duration, i,
                                    previous_context):
        """
        Generate a single visual plan.
        """
        prompt = f"""
Segment {i+1}:
Script: "{segment['content']}"
Duration: {audio_duration} seconds.

PREVIOUS SEGMENT CONTEXT:
{previous_context}

Task: Create the JSON Visual Plan for THIS segment. Ensure smooth transition from previous context.
"""
        messages = [
            Message(role='system', content=self.system_prompt),
            Message(role='user', content=prompt)
        ]

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: self.llm.generate(messages))

        # Robust JSON cleaning
        if hasattr(response, 'message') and hasattr(response.message,
                                                    'content'):
            content = response.message.content
        elif hasattr(response, 'content'):
            content = response.content
        else:
            content = str(response)

        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content,
                          re.DOTALL)
        if match:
            return match.group(1)

        start = content.find('{')
        end = content.rfind('}')
        if start != -1 and end != -1:
            return content[start:end + 1]

        return content
