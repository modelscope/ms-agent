# flake8: noqa
# yapf: disable

DEFAULT_PLAN = """

"""

DEFAULT_TASKS = """

"""

DEFAULT_IMPLEMENTATION = """

"""


PROMPT_SKILL_PLAN = """
According to the user's request:\n {query}\n,
analyze the following skill content and breakdown the necessary steps to complete the task step by step, considering any dependencies or prerequisites that may be required.
According to following sections: `SKILL_MD_CONTEXT`, `REFERENCE_CONTEXT`, `SCRIPT_CONTEXT` and `RESOURCE_CONTEXT`, you **MUST** identify the most relevant **FILES** (if any) and outline a detailed plan to accomplish the user's request.
{skill_md_context} {reference_context} {script_context} {resource_context}
\n\nThe format of your response:\n
<QUERY>
... The user's original query ...
</QUERY>


<PLAN>
... The concise and clear step-by-step plan to accomplish the user's request ...
</PLAN>


<SCRIPTS>
... The most relevant SCRIPTS (if any) in JSON format ...
</SCRIPTS>


<REFERENCES>
... The most relevant REFERENCES (if any) in JSON format ...
</REFERENCES>


<RESOURCES>
... The most relevant RESOURCES (if any) in JSON format ...
</RESOURCES>

"""


PROMPT_SKILL_TASKS = """
According to `SKILL PLAN CONTEXT`:\n\n{skill_plan_context}\n\n
Provide a concise and precise TODO-LIST of implementations required to execute the plan, **MUST** be as concise as possible.
Each task should be specific, actionable, and clearly defined to ensure successful completion of the overall plan.
The format of your response: \n
<QUERY>
... The user's original query ...
</QUERY>


<TASKS>
... A concise and clear TODO-LIST of implementations required to execute the plan ...
</TASKS>

"""


SCRIPTS_IMPLEMENTATION_FORMAT = """[
    {
        "script": "<script_path_1>",
        "parameters": {
            "param1": "value1",
            "param2": "value2"
        }
    },
    {
        "script": "<script_path_2>",
        "parameters": {
            "param1": "value1",
            "param2": "value2"
        }
    }
]"""

PROMPT_TASKS_IMPLEMENTATION = """
According to relevant content of `SCRIPTS`, `REFERENCES` and `RESOURCES`:\n\n{script_contents}\n\n{reference_contents}\n\n{resource_contents}\n\n

You **MUST** strictly implement the todo-list in `SKILL_TASKS_CONTEXT` step by step:\n\n{skill_tasks_context}\n\n

There are 3 scenarios for response, your response **MUST** strictly follow one of the above scenarios, **MUST** be as concise as possible:

Scenario-1: Execute Script(s) with Parameters, especially for python scripts, in the format of:
<IMPLEMENTATION>
{scripts_implementation_format}
</IMPLEMENTATION>

Scenario-2: No Script Execution Needed, like JavaScript、HTML code generation, please output the final answer directly, in the format of:
<IMPLEMENTATION>
```html
```
...
or
```javascript
```
</IMPLEMENTATION>

Scenario-3: Unable to Execute Any Script, Provide Reason, in the format of:
<IMPLEMENTATION>
... The reason why unable to execute any script ...
</IMPLEMENTATION>

"""


PROMPT_SKILL_FINAL_SUMMARY = """
Given the comprehensive context:\n\n{comprehensive_context}\n\n
Provide a concise summary of the entire process, highlighting key actions taken, decisions made, and the final outcome achieved.
Ensure the summary is clear and informative.
"""


# ============================================================
# AutoSkills Prompts - for automatic skill retrieval and DAG
# ============================================================

PROMPT_ANALYZE_QUERY_FOR_SKILLS = """You are a skill analyzer. Given a user query, identify what types of skills/capabilities are needed, or just chatting is sufficient.

User Query: {query}

Available Skills Overview:
{skills_overview}

Analyze the query and determine:
1. Whether this query requires specific skills/capabilities to fulfill
2. If skills are needed, what capabilities/functions are directly required
3. What prerequisites or dependencies might be required

Output in JSON format:
{{
    "needs_skills": true/false,
    "intent_summary": "Brief description of user intent",
    "skill_queries": ["query1", "query2", ...],
    "chat_response": "Direct response if no skills needed, null otherwise",
    "reasoning": "Brief explanation"
}}

Notes:
- Set `needs_skills` to false if the query is casual chat, greeting, or can be answered directly without special skills.
- If `needs_skills` is false, provide the `chat_response` with a helpful direct answer.
- If `needs_skills` is true, `skill_queries` should contain search queries for finding relevant skills.
"""

PROMPT_FILTER_SKILLS_FAST = """Quickly filter candidate skills based on their name and description.

User Query: {query}

Candidate Skills:
{candidate_skills}

For each skill, determine if it's POTENTIALLY relevant to the user's query based on:
1. Does the skill name suggest it can help with the task?
2. Does the skill description indicate capabilities matching the user's needs?

Output in JSON format:
{{
    "filtered_skill_ids": ["skill_id_1", "skill_id_2", ...],
    "reasoning": "Brief explanation of filtering"
}}

Notes:
- Only include skills that are POTENTIALLY useful for the task.
- This is a quick filter - when in doubt, INCLUDE the skill for further analysis.
- Focus on the main task output format/type matching (e.g., PDF generation needs PDF skill).
"""

PROMPT_FILTER_SKILLS_DEEP = """Analyze and filter candidate skills based on their full capabilities.

User Query: {query}

Candidate Skills (with detailed content):
{candidate_skills}

For each skill, evaluate:
1. **Capability Match**: Can this skill actually PRODUCE the required output?
2. **Task Completeness**: Can this skill independently complete the task, or does it need other skills?
3. **Redundancy**: Are there overlapping skills that do the same thing?

Output in JSON format:
{{
    "filtered_skill_ids": ["skill_id_1", "skill_id_2", ...],
    "skill_analysis": {{
        "skill_id_1": {{
            "can_execute": true/false,
            "reason": "Why this skill can/cannot execute the task"
        }},
        ...
    }},
    "reasoning": "Overall filtering explanation"
}}

**CRITICAL**:
- Only include skills that can ACTUALLY execute and produce the required output.
- Remove redundant skills - keep only the most suitable one for each capability.
- The task specified by the user may require the collaboration of multiple skills to be successfully completed.
"""

PROMPT_BUILD_SKILLS_DAG = """Filter candidate skills and build execution DAG.

User Query: {query}

Candidate Skills (USE THESE EXACT IDs in your response):
{selected_skills}

**Tasks:**
1. **Filter**: Keep only skills that can ACTUALLY produce required output. Remove redundant/unnecessary skills.
2. **Build DAG**: Define dependencies and execution order using the EXACT skill IDs from above (e.g., `pdf@latest`, `pptx@latest`).

**Output JSON:**
{{
    "filtered_skill_ids": ["exact_skill_id_from_list", ...],
    "dag": {{
        "exact_skill_id_1": ["depends_on_skill_id"],
        "exact_skill_id_2": []
    }},
    "execution_order": ["first_skill_id", "second_skill_id", ...],
    "reasoning": "Brief explanation"
}}

**CRITICAL RULES:**
- **ONLY use exact skill IDs from the Candidate Skills list** (e.g., `pdf@latest`, `pptx@latest`, NOT invented names like `create_pdf` or `generate_report`)
- Minimal sufficiency: smallest skill set that fully satisfies the query
- Deduplicate: keep only the most effective skill when overlapping
- `execution_order` MUST contain ALL skills from `filtered_skill_ids`, ordered by dependencies (parallel execution as nested lists)
- In `dag`, each skill maps to its dependencies (skills it depends on), empty list `[]` means no dependencies
"""

PROMPT_DIRECT_SELECT_SKILLS = """You are a skill selector. Given a user query and all available skills, select the relevant skills and build an execution DAG.

User Query: {query}

All Available Skills (USE THESE EXACT IDs):
{all_skills}

Tasks:
1. Determine if this query needs skills or is just casual chat
2. If skills are needed, select relevant skills using their EXACT IDs from the list above
3. Build a dependency DAG for the selected skills

Output in JSON format:
{{
    "needs_skills": true/false,
    "chat_response": "Direct response if no skills needed, null otherwise",
    "selected_skill_ids": ["exact_skill_id_from_list", ...],
    "dag": {{
        "exact_skill_id_1": ["depends_on_skill_id"],
        "exact_skill_id_2": [],
        ...
    }},
    "execution_order": ["first_skill_id", "second_skill_id", ...],
    "reasoning": "Brief explanation of skill selection and dependencies"
}}

**CRITICAL:**
- **ONLY use exact skill IDs from the Available Skills list** (e.g., `pdf@latest`, `pptx@latest`, NOT invented names)
- Set `needs_skills` to false if the query is casual chat or can be answered directly
- `execution_order` MUST contain ALL skills from `selected_skill_ids`, ordered by dependencies
- In `dag`, each skill maps to its dependencies (skills it depends on), empty list `[]` means no dependencies
"""

# ============================================================
# Progressive Skill Analysis Prompts
# ============================================================

PROMPT_SKILL_ANALYSIS_PLAN = """You are analyzing a skill to create an execution plan.

**IMPORTANT CONTEXT**:
This skill may be ONE OF SEVERAL skills in a execution chain. It does NOT need to fulfill
the ENTIRE user query - it only needs to handle its specific sub-task/capability.

For example:
- If query is "Generate a PDF report with charts", a PDF skill only needs to create PDFs
- If query is "Analyze data and visualize results", a chart skill only needs visualization
- Each skill contributes its specialized capability to the overall task

User Query: {query}

Skill Information:
- Skill ID: {skill_id}
- Name: {skill_name}
- Description: {skill_description}

Skill Content (SKILL.md):
{skill_content}

Available Resources Overview:
- Scripts: {scripts_list}
- References: {references_list}
- Resources: {resources_list}

Tasks:
1. Understand what this specific skill can do based on its description and content
2. Determine if this skill can contribute to the user's query (even partially)
3. Create a step-by-step execution plan for this skill's specific capability
4. Identify which scripts, references, and resources are needed

Output in JSON format:
{{
    "can_handle": true/false,
    "contribution": "What specific part of the query this skill handles",
    "plan_summary": "Brief summary of the execution plan",
    "steps": [
        {{"step": 1, "action": "description", "type": "script|reference|resource|code"}},
        ...
    ],
    "required_scripts": ["script_name1", "script_name2", ...],
    "required_references": ["ref_name1", ...],
    "required_resources": ["resource_name1", ...],
    "required_packages": ["python_package1", "python_package2", ...],
    "parameters": {{"param1": "value or <user_input>", ...}},
    "reasoning": "Why this plan will work"
}}

**CRITICAL - When to set can_handle**:
- Set `can_handle: true` if this skill can CONTRIBUTE to the query, even if it only handles a sub-task
- Set `can_handle: true` if the skill's core capability is RELEVANT to any part of the query
- Set `can_handle: false` ONLY if the skill has ZERO relevance to the query
- DO NOT reject a skill just because it can't fulfill the ENTIRE query

Notes:
- Only include resources that are actually needed for execution.
- Steps should be actionable and specific.
- Parameters should include any values extracted from the query.
- Extract Python package dependencies from skill content (e.g., reportlab, pandas, numpy).
"""

PROMPT_SKILL_EXECUTION_COMMAND = """Based on the execution plan and loaded resources, generate the execution command(s).

User Query: {query}
Skill ID: {skill_id}

Execution Plan:
{execution_plan}

Loaded Scripts:
{scripts_content}

Loaded References:
{references_content}

Loaded Resources:
{resources_content}

**IMPORTANT Environment Variables:**
- `SKILL_OUTPUT_DIR`: Directory where ALL output files MUST be saved (e.g., PDFs, images, data files)
- `SKILL_DIR`: The skill's directory (for accessing resources like fonts, templates)
- `SKILL_LOGS_DIR`: Directory for logs and intermediate files

Generate the specific execution command(s) needed.

Output in JSON format:
{{
    "execution_type": "script|code|shell",
    "commands": [
        {{
            "type": "python_script|python_code|shell|javascript",
            "path": "script_path (if applicable)",
            "code": "inline code (if applicable)",
            "parameters": {{"param1": "value", ...}},
            "working_dir": "working directory (optional)",
            "requirements": ["package1", "package2", ...]
        }},
        ...
    ],
    "expected_output": "Description of expected output"
}}

**CRITICAL OUTPUT RULE:**
- ALL generated files (PDFs, images, reports, etc.) MUST be saved to `os.environ['SKILL_OUTPUT_DIR']`
- Use `os.path.join(os.environ['SKILL_OUTPUT_DIR'], 'filename.pdf')` for output paths
- NEVER save output files to the current working directory or skill directory
- The skill directory should be READ-ONLY for resources, not for output
"""

PROMPT_ANALYZE_EXECUTION_ERROR = """You are analyzing a failed code execution to diagnose and fix the error.

**User Query**: {query}

**Skill ID**: {skill_id}
**Skill Name**: {skill_name}

**Failed Code**:
```python
{failed_code}
```

**Error Message (stderr)**:
```
{stderr}
```

**stdout (if any)**:
```
{stdout}
```

**Attempt**: {attempt}/{max_attempts}

**Available Environment Variables**:
- SKILL_OUTPUT_DIR: Directory for output files
- SKILL_DIR: Skill's directory for resources (fonts, templates, etc.)
- SKILL_LOGS_DIR: Directory for logs

**Helper Functions Available**:
- get_output_path(filename): Returns full path for output file

Analyze the error and provide a fix:

1. Identify the root cause of the error
2. Determine if it's fixable through code modification
3. Generate corrected code that addresses the issue

Output in JSON format:
{{
    "error_analysis": {{
        "error_type": "ModuleNotFoundError|FileNotFoundError|SyntaxError|RuntimeError|etc",
        "root_cause": "Brief description of what caused the error",
        "is_fixable": true/false,
        "fix_strategy": "Description of how to fix"
    }},
    "fixed_code": "Complete fixed Python code (or null if unfixable)",
    "additional_requirements": ["package1", "package2"],
    "explanation": "What was changed and why"
}}

**IMPORTANT**:
- Provide COMPLETE fixed code, not just the changed parts
- Ensure output paths use get_output_path() or os.environ['SKILL_OUTPUT_DIR']
- If the error is about missing packages, add them to additional_requirements
- If the error cannot be fixed (e.g., requires user input), set is_fixable to false
"""
