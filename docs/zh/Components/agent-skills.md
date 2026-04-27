---
slug: agent-skills
title: 智能体技能
description: Ms-Agent 智能体技能模块：基于 Anthropic Agent Skills 协议的技能发现、分析与执行框架。
---

# 智能体技能 (Agent Skills)

MS-Agent 技能模块是一个强大的、可扩展的技能执行框架，支持 LLM Agent 自动发现、分析并执行特定领域的技能，以完成复杂任务。该模块是 [Anthropic Agent Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) 协议的实现。

通过技能模块，Agent 可以处理如下复杂任务：
- "生成 Q4 销售数据的 PDF 报告"
- "创建关于 AI 趋势的演示文稿并附带图表"
- "将文档转换为 PPTX 格式并应用自定义主题"

## 核心特性

- **智能技能检索**：结合 FAISS 密集检索与 BM25 稀疏检索的混合搜索，并通过 LLM 进行相关性过滤
- **DAG 执行引擎**：基于依赖关系构建执行 DAG，支持独立技能并行执行，自动在技能之间传递输入/输出
- **渐进式技能分析**：两阶段分析（先规划、再加载资源），按需增量加载脚本/引用/资源，优化上下文窗口使用
- **安全执行环境**：支持通过 [ms-enclave](https://github.com/modelscope/ms-enclave) Docker 沙箱隔离执行，或在受控的本地环境中执行
- **自反思与重试**：基于 LLM 的错误分析，自动修复代码并可配置重试次数
- **标准协议兼容**：完全兼容 [Anthropic Skills](https://github.com/anthropics/skills) 协议

## 架构

### 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                       LLMAgent                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │                   AutoSkills                      │  │
│  │  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │  │
│  │  │  Loader  │  │ Retriever│  │ SkillAnalyzer  │  │  │
│  │  │          │  │ (Hybrid) │  │ (Progressive)  │  │  │
│  │  └────┬─────┘  └────┬─────┘  └───────┬────────┘  │  │
│  │       │              │                │           │  │
│  │       ▼              ▼                ▼           │  │
│  │  ┌───────────────────────────────────────────────┐│  │
│  │  │                DAGExecutor                    ││  │
│  │  │  ┌────────┐  ┌────────┐  ┌────────┐          ││  │
│  │  │  │Skill 1 │→ │Skill 2 │→ │Skill N │          ││  │
│  │  │  └───┬────┘  └───┬────┘  └───┬────┘          ││  │
│  │  │      └────────────┴──────────┘                ││  │
│  │  │                   ↓                           ││  │
│  │  │         SkillContainer (执行)                 ││  │
│  │  └───────────────────────────────────────────────┘│  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 执行流程

```
用户请求
    │
    ▼
┌────────────────┐
│  查询分析      │ ─── 是否为技能相关请求？
└───────┬────────┘
        │ 是
        ▼
┌────────────────┐
│  技能检索      │ ─── 混合搜索 (FAISS + BM25)
└───────┬────────┘
        │
        ▼
┌────────────────┐
│  技能过滤      │ ─── 基于 LLM 的相关性过滤
└───────┬────────┘
        │
        ▼
┌────────────────┐
│  DAG 构建      │ ─── 构建依赖图
└───────┬────────┘
        │
        ▼
┌────────────────┐
│  渐进式执行    │ ─── 规划 → 加载 → 执行
└───────┬────────┘
        │
        ▼
┌────────────────┐
│  结果聚合      │ ─── 合并输出，格式化响应
└────────────────┘
```

技能模块实现了多层次渐进式上下文加载机制：

1. **Level 1 (Metadata)**：仅加载技能元数据（名称、描述）以进行语义搜索
2. **Level 2 (Retrieval)**：检索相关技能并加载 SKILL.md 全文
3. **Level 3 (Resources)**：进一步加载技能所需的参考资料和资源文件
4. **Level 4 (Analysis|Planning|Execution)**：分析技能上下文，自主制定计划，加载所需资源并运行相关脚本

## 技能目录结构

每个技能是一个自包含的目录：

```
skill-name/
├── SKILL.md           # 必须: 主文档和指令
├── META.yaml          # 可选: 元数据（名称、描述、版本、标签）
├── scripts/           # 可选: 可执行脚本
│   ├── main.py
│   ├── utils.py
│   └── run.sh
├── references/        # 可选: 参考文档
│   ├── api_docs.md
│   └── examples.json
├── resources/         # 可选: 静态资源
│   ├── template.html
│   ├── fonts/
│   └── images/
└── requirements.txt   # 可选: Python 依赖
```

### SKILL.md 格式

```markdown
# 技能名称

技能功能简述。

## Capabilities

- 功能 1
- 功能 2

## Usage

使用说明...

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| input     | str  | 输入数据     |
| format    | str  | 输出格式     |

## Examples

使用示例...
```

### META.yaml 格式

```yaml
name: "PDF Generator"
description: "Generates professional PDF documents from markdown or data"
version: "1.0.0"
author: "Your Name"
tags:
  - document
  - pdf
  - report
```

## 快速开始

### 前提条件

- Python 3.9+
- Docker（用于沙箱执行，可选）
- FAISS（用于技能检索）

### 安装

```bash
pip install 'ms-agent>=1.4.0'

# 或从源码安装
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
```

### 方式一：通过 LLMAgent 配置使用

```python
import asyncio
from omegaconf import DictConfig
from ms_agent.agent import LLMAgent

config = DictConfig({
    'llm': {
        'service': 'openai',
        'model': 'gpt-4',
        'openai_api_key': 'your-api-key',
        'openai_base_url': 'https://api.openai.com/v1'
    },
    'skills': {
        'path': '/path/to/skills',
        'auto_execute': True,
        'work_dir': '/path/to/workspace',
        'use_sandbox': False,
    }
})

agent = LLMAgent(config, tag='skill-agent')

async def main():
    result = await agent.run('Generate a mock PDF report about AI trends')
    print(result)

asyncio.run(main())
```

### 方式二：直接使用 AutoSkills

```python
import asyncio
from ms_agent.skill import AutoSkills
from ms_agent.llm import LLM
from omegaconf import DictConfig

llm_config = DictConfig({
    'llm': {
        'service': 'openai',
        'model': 'gpt-4',
        'openai_api_key': 'your-api-key',
        'openai_base_url': 'https://api.openai.com/v1'
    }
})
llm = LLM.from_config(llm_config)

auto_skills = AutoSkills(
    skills='/path/to/skills',
    llm=llm,
    work_dir='/path/to/workspace',
    use_sandbox=False,
)

async def main():
    result = await auto_skills.run(
        query='Generate a mock PDF report about AI trends'
    )
    print(f"Result: {result.execution_result}")

asyncio.run(main())
```

**参数说明：**

- `skills`：技能来源，支持以下格式：
  - 单个或多个本地技能目录路径
  - 单个或多个 ModelScope 技能仓库 ID，例如 `ms-agent/claude_skills`（参考 [ModelScope Hub](https://modelscope.cn/models/ms-agent/claude_skills)）
  - 格式 `owner/skill_name` 或 `owner/skill_name/subfolder`
  - 单个或多个 `SkillSchema` 对象
- `work_dir`：技能执行输出的工作目录
- `use_sandbox`：是否使用 Docker 沙箱执行（默认 `True`），设为 `False` 则在本地执行并启用安全检查
- `auto_execute`：是否自动执行技能（默认 `True`）

## 配置

在 `agent.yaml` 中配置技能模块：

```yaml
skills:
  # 必须: 技能目录路径或 ModelScope 仓库 ID
  path: /path/to/skills

  # 可选: 是否启用检索器（默认根据技能数量自动判断）
  enable_retrieve:

  # 可选: 检索器参数
  retrieve_args:
    top_k: 3
    min_score: 0.8

  # 可选: 最大候选技能数量（默认 10）
  max_candidate_skills: 10

  # 可选: 最大重试次数（默认 3）
  max_retries: 3

  # 可选: 工作目录
  work_dir: /path/to/workspace

  # 可选: 是否使用 Docker 沙箱执行（默认 True）
  use_sandbox: false

  # 可选: 是否自动执行技能（默认 True）
  auto_execute: true
```

更多 YAML 配置的一般性说明，请参考 [配置与参数](./config)。

## 核心组件

| 组件 | 描述 |
|------|------|
| `AutoSkills` | 技能执行主入口，协调检索、分析和执行 |
| `SkillContainer` | 安全的技能执行环境（沙箱或本地） |
| `SkillAnalyzer` | 渐进式技能分析器，支持增量资源加载 |
| `DAGExecutor` | 基于依赖管理的 DAG 执行器 |
| `SkillLoader` | 技能加载与管理 |
| `Retriever` | 使用语义搜索查找相关技能 |
| `SkillSchema` | 技能 Schema 定义 |

### AutoSkills

```python
class AutoSkills:
    def __init__(
        self,
        skills: Union[str, List[str], List[SkillSchema]],
        llm: LLM,
        enable_retrieve: Optional[bool] = None,
        retrieve_args: Dict[str, Any] = None,
        max_candidate_skills: int = 10,
        max_retries: int = 3,
        work_dir: Optional[str] = None,
        use_sandbox: bool = True,
    ): ...

    async def run(self, query: str, ...) -> SkillDAGResult:
        """执行技能。"""

    async def get_skill_dag(self, query: str) -> SkillDAGResult:
        """获取技能 DAG（不执行）。"""
```

### SkillContainer

```python
class SkillContainer:
    def __init__(
        self,
        workspace_dir: Optional[Path] = None,
        use_sandbox: bool = True,
        timeout: int = 300,
        memory_limit: str = "2g",
        enable_security_check: bool = True,
    ): ...

    async def execute_python_code(self, code: str, ...) -> ExecutionOutput:
        """执行 Python 代码。"""

    async def execute_shell(self, command: str, ...) -> ExecutionOutput:
        """执行 Shell 命令。"""
```

### SkillAnalyzer

```python
class SkillAnalyzer:
    def __init__(self, llm: LLM): ...

    def analyze_skill_plan(self, skill: SkillSchema, query: str) -> SkillContext:
        """阶段 1: 分析技能并创建执行计划。"""

    def load_skill_resources(self, context: SkillContext) -> SkillContext:
        """阶段 2: 根据计划加载资源。"""

    def generate_execution_commands(self, context: SkillContext) -> List[Dict]:
        """阶段 3: 生成执行命令。"""
```

### DAGExecutor

```python
class DAGExecutor:
    def __init__(
        self,
        container: SkillContainer,
        skills: Dict[str, SkillSchema],
        llm: LLM = None,
        enable_progressive_analysis: bool = True,
        enable_self_reflection: bool = True,
        max_retries: int = 3,
    ): ...

    async def execute(
        self,
        dag: Dict[str, List[str]],
        execution_order: List[Union[str, List[str]]],
        stop_on_failure: bool = True,
        query: str = '',
    ) -> DAGExecutionResult:
        """执行技能 DAG。"""
```

## 使用示例

### 示例一：PDF 报告生成

```python
import asyncio
from ms_agent.skill import AutoSkills
from ms_agent.llm import LLM

async def generate_pdf_report():
    llm = LLM.from_config(config)
    auto_skills = AutoSkills(
        skills='/path/to/skills',
        llm=llm,
        work_dir='/tmp/reports'
    )

    result = await auto_skills.run(
        query='Generate a PDF report analyzing Q4 2024 sales data with charts'
    )

    if result.execution_result and result.execution_result.success:
        for skill_id, skill_result in result.execution_result.results.items():
            if skill_result.output.output_files:
                print(f"Generated files: {skill_result.output.output_files}")

asyncio.run(generate_pdf_report())
```

### 示例二：多技能流水线

```python
async def create_presentation():
    auto_skills = AutoSkills(
        skills='/path/to/skills',
        llm=llm,
        work_dir='/tmp/presentation'
    )

    # 此请求可能触发多个技能协同执行：
    # 1. data-analysis 技能处理数据
    # 2. chart-generator 技能创建可视化图表
    # 3. pptx 技能生成演示文稿
    result = await auto_skills.run(
        query='Create a presentation about AI market trends with data visualizations'
    )

    print(f"Execution order: {result.execution_order}")

    for skill_id in result.execution_order:
        if isinstance(skill_id, str):
            context = auto_skills.get_skill_context(skill_id)
            if context and context.plan:
                print(f"{skill_id}: {context.plan.plan_summary}")

asyncio.run(create_presentation())
```

### 示例三：自定义输入执行

```python
from ms_agent.skill.container import ExecutionInput

async def execute_with_custom_input():
    auto_skills = AutoSkills(
        skills='/path/to/skills',
        llm=llm,
        work_dir='/tmp/custom'
    )

    dag_result = await auto_skills.get_skill_dag(
        query='Convert my document to PDF'
    )

    custom_input = ExecutionInput(
        input_files={'document.md': '/path/to/my/document.md'},
        env_vars={'OUTPUT_FORMAT': 'A4', 'MARGINS': '1in'}
    )

    exec_result = await auto_skills.execute_dag(
        dag_result=dag_result,
        execution_input=custom_input,
        query='Convert my document to PDF'
    )

    print(f"Success: {exec_result.success}")

asyncio.run(execute_with_custom_input())
```

## 安全机制

### 沙箱执行（推荐）

当 `use_sandbox=True` 时，技能在隔离的 Docker 容器中运行：
- 网络隔离（可配置）
- 文件系统隔离（仅挂载工作目录）
- 资源限制（内存、CPU）
- 无法访问宿主系统
- 自动安装技能声明的依赖

### 本地执行

当 `use_sandbox=False` 时，通过以下方式保障安全：
- 基于模式匹配的危险代码扫描
- 受限的文件系统访问
- 环境变量清洗

> 请确保您信任待执行的技能脚本，以避免潜在的安全风险。本地执行需确保 Python 环境中已安装脚本所需的全部依赖。

## 创建自定义技能

1. 在技能目录下创建新的子目录
2. 添加 `SKILL.md` 文件，包含文档和指令
3. 添加 `META.yaml` 文件，包含元数据
4. 按需添加 scripts、references 和 resources
5. 使用 `AutoSkills.get_skill_dag()` 验证技能能否被正确检索

### 最佳实践

- 编写清晰完整的 `SKILL.md`，充分描述技能的功能、使用方式和参数
- 在 `requirements.txt` 中显式声明所有依赖
- 保持技能自包含，将所有必要资源打包在目录内
- 在脚本中妥善处理错误
- 使用 `SKILL_OUTPUT_DIR` 环境变量指定输出目录

## 参考

- [Anthropic Agent Skills 官方文档](https://docs.claude.com/en/docs/agents-and-tools/agent-skills)
- [Anthropic Skills GitHub 仓库](https://github.com/anthropics/skills)
- [MS-Agent Skill 示例](https://modelscope.cn/models/ms-agent/skill_examples)
