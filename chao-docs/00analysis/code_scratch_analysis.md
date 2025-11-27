# Code Scratch 模块深度分析

## 1. 项目概览
**Code Scratch** 是一个基于多智能体协作 (Multi-Agent Collaboration) 的全自动代码生成框架。它模拟了一个软件开发团队，通过 **架构设计 -> 编码实现 -> 代码精修** 的流水线，将模糊的需求转化为可运行的代码仓库。

## 2. 核心架构与工作流

该模块采用 **DAG (有向无环图) 工作流**，由 YAML 配置文件定义 Agent 之间的流转。

### 阶段详解
1.  **架构设计 (Architecture)**:
    *   **输入**: 用户的一句话需求 (如 "写一个贪吃蛇游戏")。
    *   **Agent**: 架构师 (Architect)。
    *   **职责**: 生成产品需求文档 (PRD)、模块设计和初步的文件结构 (`file_structure.json`)。
    *   **输出**: `architecture.yaml` 定义的 Prompt 引导生成设计文档。
2.  **编码实现 (Coding)**:
    *   **输入**: 架构阶段的产出。
    *   **Agent**: 项目经理 (Project Manager) & 程序员 (Worker)。
    *   **回调增强**: `coding_callback` 会在任务开始前注入前端开发规范和完整的设计上下文。
    *   **任务分发**: 使用 `split_task` 工具将文件列表拆分为多个子任务，并行启动 Worker Agent 进行具体代码编写。
    *   **工件生成**: 使用 `artifact_callback` 将 Agent 生成的代码块 (````js ... ````) 解析并保存为实际文件。
3.  **代码精修 (Refine)**:
    *   **输入**: 已生成的代码文件。
    *   **Agent**: 修复专家 (Refiner)。
    *   **自动化测试**: `eval_callback` 自动执行编译命令 (如 `npm install && npm run build`) 并捕获错误日志。
    *   **修复循环**:
        1.  **信息收集**: 根据报错信息，Refiner 发布任务去读取相关文件内容。
        2.  **方案制定**: 基于收集到的信息制定修复计划。
        3.  **执行修复**: 再次分发任务修改代码。
4.  **人工验收 (Human Evaluation)**:
    *   在所有自动步骤完成后，系统暂停并邀请用户进行测试 (如 `npm run dev`)。
    *   用户可反馈新的需求或 Bug，触发新一轮的精修。

## 3. 关键文件与类

| 文件路径 | 类/函数 | 职责 |
| :--- | :--- | :--- |
| `projects/code_scratch/workflow.yaml` | N/A | **流程定义**。定义了 `architecture` -> `coding` -> `refine` 的跳转逻辑。 |
| `projects/code_scratch/config_handler.py` | `ConfigHandler` | **动态配置**。在 `task_begin` 时根据当前阶段 (如 Worker) 动态注入回调和调整工具。 |
| `projects/code_scratch/callbacks/coding_callback.py` | `CodingCallback` | **上下文注入**。在编码开始前注入代码规范和设计文档。 |
| `projects/code_scratch/callbacks/artifact_callback.py` | `ArtifactCallback` | **文件写入**。解析 Agent 输出的 Markdown 代码块并写入磁盘。 |
| `projects/code_scratch/callbacks/eval_callback.py` | `EvalCallback` | **编译与评估**。负责执行构建命令 (npm install/build) 并向 Agent 提供反馈。 |
| `ms_agent/tools/split_task.py` | `SplitTask` | **任务分发**。核心工具，负责将大任务分解并调度子 Agent 并行执行。 |

## 4. 配置与依赖

### 配置文件
*   **`workflow.yaml`**: 定义顶层 DAG 流程。
*   **`agent.yaml`**: 基础 Agent 配置。
*   **`architecture.yaml`, `coding.yaml`, `refine.yaml`**: 各阶段专用的 Agent 配置 (System Prompt, Tools)。

### 关键机制
*   **Config Lifecycle**: 允许在运行时动态修改 Agent 配置，这是实现 "Manager -> Worker" 模式的关键。
*   **Artifact System**: Agent 不直接操作文件系统 API 写文件，而是通过特定格式的文本输出，由 Callback 拦截处理，降低了模型犯错的概率。

### 外部依赖
*   **Node.js & npm**: 生成的项目通常是前端项目，强依赖 Node 环境进行依赖安装和构建检查。
*   **Python >= 3.10**: 运行框架本身。

## 5. 局限性与改进点
*   **上下文共享**: 目前依赖文件系统共享信息，对于极大规模项目，Token 上下文可能超限。
*   **依赖管理**: 自动修复依赖安装错误的能力有限，有时需要人工干预 `package.json`。
