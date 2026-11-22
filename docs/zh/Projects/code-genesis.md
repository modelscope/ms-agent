---
slug: code-genesis
title: 代码创世纪
description: Ms-Agent 代码创世纪项目:从自然语言需求生成软件项目的多智能体工作流
---

# 代码创世纪

Code Genesis 是一个开源的多智能体框架,面向从自然语言需求生成软件项目的场景。它通过编排专业化的 AI 智能体,自主完成端到端的项目生成,包括前端、后端和数据库集成。

## 原理介绍

### 特性

- **端到端项目生成**:从自然语言描述自动生成完整项目,包含前端、后端和数据库集成
- **高质量代码**:通过 LSP 诊断和依赖解析辅助检查生成代码
- **拓扑感知生成**:按依赖顺序生成代码，减少跨文件引用错误
- **自动化部署**:通过 MCP 集成自动部署到 EdgeOne Pages
- **灵活的工作流**:根据项目复杂度选择标准(7阶段)或简化(4阶段)流程

### 架构

Code Genesis 提供两种可配置的工作流模式:

#### 标准工作流

![标准工作流](../../../projects/code_genesis/asset/workflow.jpg)

标准流程包含7个阶段，适用于需要显式设计与分步验证的复杂项目:

```
用户故事 → 架构设计 → 文件设计 → 文件排序 → 环境安装 → 编码 → 优化
```

**流程阶段**:
1. **用户故事智能体**:将用户需求解析为结构化的用户故事
2. **架构智能体**:选择技术栈并定义系统架构
3. **文件设计智能体**:从架构蓝图生成物理文件结构
4. **文件排序智能体**:构建依赖 DAG 并进行拓扑排序,支持并行代码生成
5. **安装智能体**:引导环境配置并解决依赖关系
6. **编码智能体**:基于 LSP 验证合成代码,遵循依赖顺序
7. **优化智能体**:执行运行时验证、错误修复和自动化部署

每个智能体都会产生结构化的中间输出,便于检查设计、代码与验证结果。

#### 简化工作流(快速原型)

![简化工作流](../../../projects/code_genesis/asset/simple_workflow.jpg)

对于轻量级项目或快速迭代,简化工作流将流程压缩为4个核心阶段:

```
编排器 → 环境安装 → 编码 → 优化
```

**精简流程**:
1. **编排智能体**:统一的需求分析、架构设计和文件规划
2. **安装智能体**:依赖解析和环境配置
3. **编码智能体**:直接代码生成,集成文件排序
4. **优化智能体**:验证和部署

#### 工作流对比

| 方面 | 标准工作流 | 简化工作流 |
|------|-----------|-----------|
| **智能体阶段** | 7个专业化智能体 | 4个整合智能体 |
| **架构质量** | 显式、可审计的设计 | 隐式、整体式设计 |
| **生成时间** | 中等(全面规划) | 快速(直接执行) |
| **适用场景** | 生产系统、复杂应用 | 原型、演示、简单工具 |

## 使用方式

### 安装

克隆仓库并准备环境:

```bash
git clone https://github.com/modelscope/ms-agent
cd ms-agent
pip install -r requirements/code.txt
pip install -e .
```

准备 npm 环境,参考 https://nodejs.org/en/download。如果你使用 Mac,推荐使用 Homebrew: https://formulae.brew.sh/formula/node

确保安装成功:
```bash
npm --version
```

确保 npm 安装成功,否则 npm install/build/dev 可能失败。

### 快速启动

运行标准工作流:

```bash
PYTHONPATH=. openai_api_key=your-api-key openai_base_url=your-api-url \
python ms_agent/cli/cli.py run \
  --config projects/code_genesis \
  --query 'make a demo website' \
  --trust_remote_code true
```

代码默认输出到当前目录的 `output` 文件夹。

### 高级配置

#### 文件编辑与旧配置兼容

当前 SDK 的 `file_system.edit_file` 使用 `old_string` / `new_string` 精确替换，不需要单独的编辑模型。CodeGenesis 的部分旧配置处理器仍读取 `tools.file_system.edit_file_config.api_key` 来决定是否向模型开放编辑工具；这属于过渡期兼容逻辑，不能据此认为配置 `diff_model` 就会启用 Morph 等服务。调整已有工作流时，请同时检查 `coding.yaml`、`refine.yaml` 及其配置处理器。

#### 启用自动化部署

在 `refine.yaml` 的 `tools` 下添加 `edgeone-pages-mcp`（作为 MCP 工具）:

```yaml
tools:
  edgeone-pages-mcp:
    mcp: true
    command: "npx"
    args: ["edgeone-pages-mcp"]
    env:
      EDGEONE_PAGES_API_TOKEN: your-edgeone-token
```

从 https://pages.edgeone.ai/zh/document/pages-mcp 获取 `EDGEONE_PAGES_API_TOKEN`
