# 模板定义：Research 报告标准格式
# 用于指导 Research Agent 生成结构化报告
RESEARCH_REPORT_TEMPLATE = """# Research Report: {query}

## 1. Executive Summary
[Brief summary of the findings, 2-3 paragraphs]

## 2. Key Concepts & Technologies
*   **Concept A**: [Definition and relevance]
*   **Technology B**: [Definition and relevance]

## 3. Implementation Details (Crucial for Coding)
*   **API Endpoints / Data Structures**: [Detailed description]
*   **Libraries/Dependencies**: [List of recommended libraries with versions]
*   **Algorithms**: [Step-by-step explanation or pseudocode]

## 4. Reference Material
*   [Source Title](URL) - [Key insight]
*   [Local File](path) - [Key insight]

## 5. Constraints & Risks
*   [Performance/Security constraints]
*   [Potential implementation pitfalls]
"""

# 模板定义：技术规格书标准格式
# 用于指导 Spec Agent 将 Report 转化为可执行的蓝图
TECH_SPEC_TEMPLATE = """# Technical Specification: {project_name}

## 1. System Overview
[High-level architecture description]

## 2. File Structure
```text
src/
├── main.py
├── utils.py
└── ...
tests/
├── test_main.py
└── ...
requirements.txt
```

## 3. API Definitions & Data Structures
### 3.1 Class/Function: `ClassName`
*   **Description**: ...
*   **Methods**:
    *   `method_name(arg1: type) -> type`: [Description]

### 3.2 Data Models
*   `ModelName`: {field: type, ...}

## 4. Core Logic & Algorithms
[Detailed logic flow, state management, etc.]

## 5. Dependencies
*   package_name>=version

## 6. Testing Strategy
*   **Unit Tests**: [Key scenarios to cover]
*   **Integration Tests**: [Inter-module interactions]
"""

# 提示词模板：Spec 生成器
# 指导 LLM 从 Report 生成 Spec
SPEC_GENERATION_PROMPT = """
You are a Senior System Architect.
Your task is to convert the following "Research Report"
into a rigorous "Technical Specification" (tech_spec.md).
The specification will be used by a developer to write code and a QA engineer to write tests.

**Input Report**:
{report_content}

**Requirements**:
1. Strict adherence to the input report. Do not hallucinate features NOT mentioned
    unless necessary for a working system.
2. Define clear API signatures (Python type hints).
3. List specific library versions.
4. Output MUST be in Markdown format following this structure:

""" + TECH_SPEC_TEMPLATE
