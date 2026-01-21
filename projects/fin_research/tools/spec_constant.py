# Copyright (c) Alibaba, Inc. and its affiliates.
# flake8: noqa
# isort: skip_file
# yapf: disable

WRITING_SPEC_GUIDE = """
<Writing Style Spec Quick Guide & Usage Notes>

- **Structure & Layering — control section depth and hierarchy**
  - **Use for:** Deciding how many levels of headings/sections to use in a report.
  - **Best for:** Long-form financial/company/industry reports where the model might create 4+ nested levels.
  - **Key constraints:** Default to 2–3 heading levels; avoid creating sub-sub-subsections with only 1–2 short paragraphs.

- **Methodology Exposure — how much to talk about frameworks**
  - **Use for:** When you are tempted to write long “Research Methodology” sections or repeatedly mention MECE/SWOT/80-20 in the main text.
  - **Best for:** Analyst-style reports where frameworks should be *used* implicitly instead of being “lectured”.
  - **Key constraints:** Briefly mention the approach once if needed; do NOT devote full chapters to methods; avoid repeating framework names as slogans.

- **Bullets & Paragraph Rhythm — bullets vs narrative**
  - **Use for:** Deciding when to use bullet points vs continuous paragraphs.
  - **Best for:** Sections with many drivers/risks/factors where you may over-bullet every sentence.
  - **Key constraints:** Bullets for lists (drivers, risks, recommendations); keep explanatory reasoning in paragraphs; avoid “one sentence per bullet” patterns.

- **Task Focus & Relevance — stay anchored to the user's question**
  - **Use for:** Ensuring that each chapter directly serves the original question instead of drifting into generic industry essays.
  - **Best for:** Prompts that ask for specific company/period/comparison/forecast.
  - **Key constraints:** Minimize repeated background; tie each section back to the key metrics and drivers required by the task (e.g., profitability, cash-flow quality, competition, forecasts).

- **Tone & Analyst Voice — sound like a human analyst, not a textbook**
  - **Use for:** Choosing phrasing style and presentation voice.
  - **Best for:** Sell-side / buy-side style reports, IC memos, investment notes.
  - **Key constraints:** Conclusion-first; 2–4 key supporting points; professional but readable; avoid academic jargon and over-formal “methodology lectures”.

- **Density & Length Control — right amount of detail**
  - **Use for:** Controlling report length and pruning low-value content.
  - **Best for:** Long multi-chapter outputs where token budget and human attention are limited.
  - **Key constraints:** Prioritize conclusions, drivers, and critical numbers; compress or omit peripheral background; avoid repeating the same facts in multiple chapters.
</Writing Style Spec Quick Guide & Usage Notes>
"""
WRITING_ROUTING_GUIDE = """
<Writing Spec Composition & Routing (Model Selection Hints)>
Heuristics for selecting writing style specs:

- Report feels too much like an academic paper or you want a clear report skeleton?
  → Load **Structure & Layering** + **Tone & Analyst Voice**.

- You're about to write a long “Research Methodology” chapter or heavily talk about MECE/SWOT/etc.?
  → Load **Methodology Exposure** (and follow its constraints strictly).

- You're using many bullet points and the text starts looking like a checklist?
  → Load **Bullets & Paragraph Rhythm** to rebalance bullets vs narrative flow.

- The user's question is narrow (e.g., “past 4 quarters + next 2 quarters”), but you're expanding a lot on generic industry background?
  → Load **Task Focus & Relevance** to keep all chapters anchored to the core task.

- The answer tends to be very long and repetitive, and you need to compress while preserving value?
  → Load **Density & Length Control**; it tells you what to prune and what to keep.

You can combine multiple specs in one call, e.g.:
- For an analyst-style profitability & forecast report:
  → [ "structure", "tone", "methods", "bullets", "focus" ]
</Writing Spec Composition & Routing (Model Selection Hints)>
"""

PRINCIPLE_SPEC_GUIDE = """
<Principle Quick Guide & Usage Notes>
- **MECE (Mutually Exclusive, Collectively Exhaustive) — non-overlapping, no-omission framing**
  - **Use for:** Building problem & metric trees, defining scopes and boundaries, avoiding gaps/duplication.
  - **Best for:** Kick-off structuring of any report (industry/company/portfolio/risk).
  - **Deliverable:** 3-5 first-level dimensions; second-level factors with measurement definitions; a “Problem → Scope → Metrics” blueprint.

- **Value Chain (Porter) — sources of cost/value**
  - **Use for:** Explaining fundamentals and levers behind Gross Margin / ROIC (primary + support activities).
  - **Best for:** Company & supply-chain research; cost curve and pass-through analysis.
  - **Deliverable:** Stage → Drivers → Bottlenecks → Improvements → Financial impact (quantified to GM/Cash Flow/KPIs).

- **BCG Growth-Share Matrix (Boston Matrix) — growth x share portfolio positioning**
  - **Use for:** Placing multi-business/multi-track items into Star/Cash Cow/Question Mark/Dog to guide resource/weighting decisions.
  - **Best for:** Comparing industry sub-segments; managing company business portfolios.
  - **Deliverable:** Quadrant mapping; capital/attention flow plan (e.g., from Cows → Stars/Questions); target weights and migration triggers.

- **80/20 (Pareto) — focus on the vital few**
  - **Use for:** Selecting the top ~20% drivers that explain most outcomes across metrics/assets/factors; compressing workload.
  - **Best for:** Return/risk attribution; metric prioritization; evidence triage.
  - **Deliverable:** Top-K key drivers + quantified contributions + tracking KPIs; fold the remainder into “long-tail management.”

- **SWOT → TOWS — from inventory to action pairing**
  - **Use for:** Pairing internal (S/W) and external (O/T) to form SO/WO/ST/WT **actionable strategies** with KPIs.
  - **Best for:** Strategy setting, post-investment management, risk hedging and adjustment thresholds.
  - **Deliverable:** Action list with owners/KPIs/thresholds and financial mapping (revenue/GM/cash-flow impact).

- **Pyramid / Minto — conclusion-first presentation wrapper**
  - **Use for:** Packaging analysis as “Answer → 3 parallel supports → key evidence/risk hedges” for fast executive reading.
  - **Best for:** Executive summaries, IC materials, report front pages.
  - **Deliverable:** One-sentence conclusion (direction + range + time frame), three parallel key points, strongest evidence charts.
</Principle Quick Guide & Usage Notes>
"""
PRINCIPLE_ROUTING_GUIDE = """
<Composition & Routing (Model Selection Hints)>
Here are some Heuristic hints for selecting the appropriate principles for the task:
- Need to “frame & define scope”? → Start with **MECE**; if explaining costs/moats, add **Value Chain**.
- Multi-business/multi-track “allocation decisions”? → Use **BCG** for positioning & weights, then **80/20** to focus key drivers.
- Want to turn inventory into **executable actions**? → **SWOT→TOWS** for strategy+KPI and threshold design.
- Delivering to management? → Present the whole piece with **Pyramid**; other principles provide evidence and structural core.
</Composition & Routing (Model Selection Hints)>
"""
