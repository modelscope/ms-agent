---
slug: agent-skills
title: 智能体技能
description: MS-Agent 技能模块：知识驱动的技能系统，通过标准工具集成为 LLM 智能体提供可复用的操作知识。
---

# 智能体技能 (Agent Skills)

MS-Agent 技能模块采用知识驱动的设计理念来扩展 LLM 智能体能力。与构建独立执行管线不同，技能被视为**操作知识（procedural knowledge）**——描述"如何做某件事"，由模型自主使用已有工具（代码执行、文件读写、网络搜索等）来完成执行。

## 架构

```
  ┌─────────────┐     ┌──────────────┐     ┌───────────────────┐
  │  技能来源    │────▶│ SkillCatalog │────▶│PromptInjector     │
  │ 本地/MS/Git  │     │ 加载、过滤、 │     │ always 技能:       │
  │              │     │ 缓存         │     │   全文注入         │
  └─────────────┘     └──────┬───────┘     │ 所有技能:          │
                             │             │   名称+描述索引    │
                             │             └───────────────────┘
                             ▼
                      ┌─────────────┐     ┌──────────────────┐
                      │SkillToolSet │────▶│   ToolManager    │
                      │ skills_list │     │ 统一注册         │
                      │ skill_view  │     │ (MCP + 内置      │
                      │ skill_manage│     │  + 技能工具)     │
                      └─────────────┘     └────────┬─────────┘
                                                   │
                                                   ▼
                                          ┌────────────────┐
                                          │    LLM Agent   │
                                          │   step() 循环  │
                                          └────────────────┘
```

### 技能工作流程

1. **System prompt** 中包含所有已启用技能的轻量索引（名称 + 描述，每个约 30 token）。标记 `always: true` 的技能全文注入。
2. 当模型遇到相关任务时，调用 `skill_view(skill_id)` 加载完整指令。
3. 模型按照指令使用已有工具（`code_executor`、`web_search`、`file_system` 等）执行操作。
4. 所有结果通过标准 `role: tool` 消息流转——无特殊路由，无短路逻辑。

### 三级渐进式披露

| 级别 | 模型看到的内容 | Token 开销 | 来源 |
|------|-------------|-----------|------|
| L1 | 名称 + 一行描述 | ~30 token/技能 | System prompt（自动） |
| L2 | 完整 SKILL.md 正文 | 按需 | `skill_view` 工具调用 |
| L3 | 引用的脚本、模板、文档 | 按需 | `skill_view` 指定 `file_path` |

## 核心特性

- **技能即知识**：技能指导模型；执行使用已有工具。无独立管线，无需子进程隔离。
- **统一工具集成**：技能工具（`skills_list`、`skill_view`、`skill_manage`）通过标准 `ToolManager` 注册，与 MCP 和内置工具共享同一套调度。
- **多源加载**：通过 `SkillCatalog` 从本地目录、ModelScope 仓库或 Git URL 加载技能。
- **三层优先级**：内置技能 < 用户主目录技能 < 工作目录技能。高优先级同名技能覆盖低优先级。
- **常驻技能**：将关键技能标记为 `always: true`，其全文注入 system prompt。
- **热重载**：`SkillCatalog` 支持单个技能重载或全量刷新，变更通过工具调用即时可见。
- **运行时自进化**：启用 `enable_manage: true` 后，模型可在对话中创建、编辑、删除技能。
- **零开销关闭**：不配置 `skills:` → 不注册技能工具，不注入 prompt，无性能影响。

## 技能目录结构

```
my-skill/
├── SKILL.md              # 必需：入口文件
├── scripts/              # 可选：脚本文件
│   └── search.py
├── references/           # 可选：参考文档
│   └── api-docs.md
├── templates/            # 可选：模板文件
│   └── report.html
└── assets/               # 可选：静态资源
    └── config.yaml
```

### SKILL.md 格式

```yaml
---
name: paper-finder                  # 必需，hyphen-case，≤64 字符
description: "搜索并分析学术论文"      # 必需，≤1024 字符
version: "1.0.0"                    # 可选
author: "team-name"                 # 可选
tags: [research, papers]            # 可选，用于分类过滤
always: false                       # 可选，true → 全文注入 prompt
requires:                           # 可选，依赖声明
  tools: [web_search, terminal]
  env: [ARXIV_API_KEY]
---

# Paper Finder

## 使用场景
当用户要求查找或分析学术论文时使用此技能。

## 操作步骤
1. 使用 `web_search` 在 arXiv 上搜索论文
2. 使用 `code_executor` 解析搜索结果
3. 向用户总结分析结论
```

## 快速开始

### 通过 LLMAgent 使用

```python
import asyncio
from omegaconf import DictConfig
from ms_agent.agent import LLMAgent

config = DictConfig({
    'llm': {
        'model': 'qwen-max',
        'api_base': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    },
    'tools': {
        'code_executor': {'implementation': 'python_env'},
    },
    'skills': {
        'path': ['./skills'],
        'auto_discover': True,
    },
})

agent = LLMAgent(config, tag='skill-agent')

async def main():
    result = await agent.run('搜索关于多模态 RAG 的最新论文')
    print(result[-1].content)

asyncio.run(main())
```

### 编程式使用

```python
from ms_agent.skill import SkillCatalog, SkillPromptInjector, SkillToolSet

catalog = SkillCatalog()
catalog.load_from_config(skills_config)

injector = SkillPromptInjector(catalog)
prompt_section = injector.build_skill_prompt_section()

toolset = SkillToolSet(config, catalog, enable_manage=True)
```

## 配置

```yaml
# agent.yaml
skills:
  # 来源路径（本地目录、ModelScope 仓库或混合使用）
  path:
    - ./skills
    - ms-agent/research_skills

  # 或使用结构化来源
  sources:
    - type: local
      path: ./skills
    - type: modelscope
      repo_id: ms-agent/research_skills
      revision: v1.0

  auto_discover: true       # 自动扫描 CWD/skills/ 目录
  enable_manage: false       # 启用 skill_manage 工具

  # 过滤控制（三值语义）
  # whitelist: null          # null = 全部启用（默认）
  # whitelist: []            # [] = 全部禁用
  # whitelist: [paper-finder]  # 仅启用指定技能
  disabled: []               # 禁用指定技能
```

## 核心组件

| 组件 | 描述 |
|------|------|
| `SkillCatalog` | 多源技能管理器：优先级覆盖、缓存、白名单/禁用过滤、热重载 |
| `SkillPromptInjector` | 构建 system prompt 技能段落（always 技能全文 + 摘要索引） |
| `SkillToolSet` | `ToolBase` 子类，提供 `skills_list`、`skill_view`、`skill_manage` 注册为标准工具 |
| `SkillLoader` | 底层磁盘解析器，解析 SKILL.md 目录（从 v1 保留） |
| `SkillSchema` | 已解析技能的数据模型（从 v1 保留） |

## 与旧版本 (v1) 的对比

| 维度 | v1（AutoSkills 管线） | v2（知识 + 工具） |
|------|---------------------|------------------|
| 执行模型 | 独立管线：LLM 分析 → DAG → 子进程 | 标准 agent 循环——模型直接使用工具 |
| 调度方式 | `do_skill()` 短路 agent 循环 | 无特殊分支；技能即标准工具 |
| 上下文加载 | 4 级 LLM 驱动的渐进分析 | 3 级披露：prompt → `skill_view` → 文件 |
| 工具共存 | 技能与 MCP 工具互斥 | 所有工具共存于同一循环 |
| 流式输出 | 技能模式下不支持 | 天然支持 |
| 外部依赖 | FAISS, Docker, sentence-transformers | 无（纯 Python） |
| 已移除 | — | `AutoSkills`, `DAGExecutor`, `SkillAnalyzer`, `SkillContainer`, `Spec` |
| 新增 | — | `SkillCatalog`, `SkillPromptInjector`, `SkillToolSet` |

## 参考

- [设计文档](https://github.com/modelscope/ms-agent/tree/main/ms_agent/skill/README.md)
- [MS-Agent 技能示例](https://modelscope.cn/models/ms-agent/skill_examples)
