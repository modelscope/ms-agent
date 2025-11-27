# Research-to-Code 全链路实施方案 (Non-Invasive SOTA Edition)

## 1. 背景与目标
当前 `seu-ms-agent` 仓库中，`doc_research`、`deep_research` 和 `code_scratch` 是三个独立且成熟的模块，且上游持续更新。
**核心约束**：**严禁修改现有模块的内部实现**（如 `ms_agent/` 核心代码或 `projects/` 下的现有逻辑），以避免合并冲突。
**目标**：通过 **外部编排 (External Orchestration)** 和 **适配器模式 (Adapter Pattern)**，将这三个“黑盒”模块串联成一个符合 SOTA 标准的自动化流水线。

## 2. 行业 SOTA 架构深度调研与理论溯源

本方案综合了 **AWS**、**OpenAI**、**DeepMind** 及开源社区的最新成果，采用 **"无侵入式编排"** 策略。

### 2.1 核心模式对比与溯源
| 模式 | 理论/项目来源 | 核心思想 | 本方案应用 |
| :--- | :--- | :--- | :--- |
| **Plan-Execute (计划-执行)** | **AWS Amazon Q Developer** | 强制生成 "Plan" 并 Review。 | **Phase 1.5: Spec Adapter**。在 Research 和 Code 之间插入一个独立的“规划转化”步骤。 |
| **Test-Driven Generation** | **DeepMind AlphaCodium** | 先生成测试，再生成代码。 | **Phase 2: External Test Gen**。在调用 Code Scratch 前，先在工作区预置测试用例。 |
| **Human-in-the-Loop** | **OpenAI O1 / SWE-bench** | 关键节点的人工确认能大幅降低幻觉风险。 | **Phase 2.5: Human Review**。允许用户在生成测试前修订 Spec。 |

## 3. 架构设计：无侵入式 R-S-T-C 流水线

我们保持 `doc_research`、`deep_research`、`code_scratch` 代码**一字不动**，将它们视为 **CLI 工具** 或 **Library**。通过一个外部的 `Orchestrator` 脚本来管理数据流。

### 3.1 角色与组件
1.  **Orchestrator (编排器)**: 全局控制器，负责调用各模块，管理工作目录，处理异常与重试。
2.  **Research Module (原样复用)**:
    *   **Deep Research**: 调用 `projects/deep_research`，用于开放域搜索。
    *   **Doc Research**: 调用 `ms_agent/app/doc_research.py` (或底层 `ResearchWorkflow`)，用于特定文档/URL分析。
    *   输出: `report.md` (自然语言)。
3.  **Spec Adapter (新增适配器)**:
    *   **独立 Agent**。
    *   输入: `report.md`。
    *   输出: `tech_spec.md` (结构化), `api_definitions.json`。
    *   作用: 将“作文”翻译成“蓝图”。
4.  **Test Generator (新增生成器)**:
    *   **独立 Agent**。
    *   输入: `tech_spec.md`。
    *   输出: `tests/test_*.py` (写入工作区)。
    *   作用: 预置 AlphaCodium 风格的测试用例。
5.  **Coding Module (原样复用)**:
    *   调用 `projects/code_scratch`。
    *   **Prompt Injection**: 通过构造特殊的 `Query`，引导它读取预置的 Spec 和 Tests。

### 3.2 数据流转图
```mermaid
graph TD
    User[用户输入] --> Orch[Orchestrator 脚本];
    Orch -->|1. 分流| Branch{有无附件?};
    Branch -->|无附件| Deep[Deep Research (Web Search)];
    Branch -->|有附件/URL| Doc[Doc Research (File Analysis)];

    Deep -->|产出| Report[report.md];
    Doc -->|产出| Report;

    Report -->|2. 输入| Adapter[Spec Adapter (New Agent)];
    Adapter -->|清洗/结构化| Spec[tech_spec.md];

    Spec -->|2.5 人工确认 (可选)| Human{Human Review};
    Human -->|修订| Spec;

    Spec -->|3. 输入| TestGen[Test Generator (New Agent)];
    TestGen -->|产出| Tests[tests/test_core.py];

    Spec & Tests -->|4. 注入 Workspace| Workspace;

    Orch -->|5. 构造 Prompt| Prompt["任务：实现功能... \n 参考：请严格遵循当前目录下的 tech_spec.md 并通过 tests/ 中的测试"];
    Prompt -->|6. 调用| Code[Code Scratch (Blackbox)];
    Code -->|读取| Workspace;
    Code -->|产出| FinalCode[最终代码];

    FinalCode -->|7. 验证| Verifier{Orchestrator 验证};
    Verifier -->|测试通过| Success[交付];
    Verifier -->|测试失败| Retry[重试 (带 Error Log)];
    Retry -->|8. 再次调用| Code;
```

## 4. 详细实施步骤

### Phase 1: Research (Blackbox Call)
**目标**：获取高质量的领域知识和上下文。
**操作逻辑**：
1.  Orchestrator 接收用户 Query 和可选的附件/URL。
2.  **模式选择**：
    *   **Deep Research 模式**：如果用户仅提供 Query，调用 `projects/deep_research` 进行全网搜索。
    *   **Doc Research 模式**：如果用户提供了 PDF/文档/URL，调用 `ResearchWorkflow` (参考 `ms_agent/app/doc_research.py`) 并传入 `urls_or_files` 参数。
    2选1，or 并行
3.  指定输出目录为当前任务的工作区。
4.  **验证**：检查是否生成了 `report.md`。如果失败，允许用户手动上传文档或提供 URL 作为替代。

### Phase 2: Spec & Test Generation (The Glue)
**目标**：将非结构化的自然语言报告转化为结构化的工程蓝图。这是连接 Research 和 Code 的关键“胶水层”。
**操作逻辑**：
1.  **Spec Generation**:
    *   - 读取 `report.md`，给下游coding agent的。
    *   - 全面的用来阅读的report ` 给人看的report.md 或者其他格式`
    *   使用高智商模型提取关键技术约束（API 签名、数据结构、依赖版本）。
    *   关键技术约束，**结合demo**，可能需要硬编码something
    *   生成 `tech_spec.md`。
2.  **Human Review (关键环节)**:
    *   Orchestrator 暂停流程。
    *   提示用户检查 `tech_spec.md`。用户可以直接选择/编辑文件来修正理解偏差。
    *   用户确认后继续。
3.  **Test Generation (AlphaCodium Pattern)**:
    *   读取最终确认的 `tech_spec.md`。
    *   生成 `pytest` 测试用例 (`tests/test_core.py`)。
        *   测试用例应该在coding过程中写，一个模块一个模块去写
    *   **重点**：测试用例应包含 Happy Path 和 Edge Cases，且必须独立于实现代码运行。

### Phase 3: Coding (Prompt Engineering Injection)
**目标**：利用现有的 Coding Agent 实现功能，但强制其遵循我们的 Spec 和 Test。
**操作逻辑**：
1.  **Context Injection (上下文注入)**:
    *   构造一个 **"Meta-Instruction" (元指令)** Prompt。
    *   Prompt 核心内容：“不要从零开始设计。我已为你准备了 `tech_spec.md` 和 `tests/`。请读取它们，并编写代码以通过测试。”
2.  **Blackbox Execution**:
    *   调用 `projects/code_scratch` 模块。
    *   将构造好的 Prompt 作为任务输入。
    *   设置工作目录为包含 Spec 和 Tests 的目录。
3.  **Outer Loop Verification (外循环验证)**:
    *   Coding 结束后，Orchestrator 运行 `pytest`。
    *   **Success**: 测试通过 -> 交付。
    *   **Failure**: 捕获错误日志 -> 构造“修复任务” Prompt -> 再次调用 Coding Module (Retry)。
    *   **Max Retries**: 超过重试次数则人工介入。

## 5. 运营与配置 (Operational Excellence)

### 5.1 目录结构规范
为了保证多次运行不冲突，建议采用基于时间戳的工作区管理：
```
workspace/
  run_20251121_1000/
    report.md       (Phase 1 Output)
    tech_spec.md    (Phase 2 Output)
    tests/          (Phase 2 Output)
      test_core.py
    src/            (Phase 3 Output)
      main.py
    logs/           (Orchestrator Logs)
```

### 5.2 模型策略 (Model Strategy)
*   **Research**: 使用 `gpt-4o-mini` 或 `haiku` 以降低大量阅读的成本。
*   **Spec & Test**: 必须使用 **SOTA 模型** (`gpt-4o`, `claude-3-5-sonnet`)，因为这是整个系统的“大脑”。如果 Spec 错了，后面全错。
*   **Coding**: `code_scratch` 默认配置的模型（通常也是强模型）。

## 6. 优势分析
1.  **零侵入 (Zero Intrusion)**: 不需要修改 `ms_agent` 或 `projects/` 下的任何一行代码。上游更新，我们直接 pull 即可。
2.  **解耦 (Decoupling)**: Research 模块想换成别的？Code 模块想换成别的？改一下 `orchestrator.py` 即可，模块间互不依赖。
3.  **SOTA 能力保留**: 虽然没改内部代码，但通过 **"Prompt Injection"** 和 **"Workspace Pre-seeding"** (预置文件)，我们依然实现了 Spec-First 和 Test-Driven 的高级流程。
4.  **鲁棒性 (Robustness)**: 增加了 Human Review 和 Outer Loop 重试机制，使其真正具备生产可用性。

## 7. 总结
本方案通过 **"外部编排 + 上下文注入"** 的方式，完美平衡了 **"引入先进架构"** 与 **"维护上游兼容性"** 的矛盾。它就像一个指挥家（Orchestrator），指挥着三个顶级乐手（现有模块）协同演奏，而不需要教乐手如何拉琴。

## 8. 团队分工方案 (Team Roles & Responsibilities)

基于本项目 **"非侵入式编排"** 与 **"黑盒集成"** 的技术特性，建议三人团队按 **“流水线阶段”** 与 **“技能栈侧重”** 进行分工。此分工旨在最大化并行开发效率，同时确保各模块接口（Interface）的清晰定义。

### 成员 A: 核心架构与编排 (System Architect & Orchestrator)-fyc
**定位**: 系统的“骨架”与“神经中枢”，负责数据流转、状态管理及核心对象封装。
**技术要求**: 熟练掌握 Python 高级编程、进程管理、文件系统操作。
**核心职责**:
1.  **Orchestrator 主程序**: 开发 `orchestrator.py`，实现 CLI 入口、参数解析、工作区目录生命周期管理 (`workspace/run_timestamp/`)。
2.  **Doc Research 深度集成**: 深入阅读 `ms_agent/app/doc_research.py`，绕过 Gradio 层直接封装底层 `ResearchWorkflow` 类，实现对本地文件/URL 的分析调用。
3.  **交互控制 (Human-in-the-Loop)**: 实现控制台的交互逻辑（如：暂停流水线、等待用户选择/编辑 `tech_spec.md`、接收确认指令后继续）。
4.  **全链路联调**: 负责最终将各成员开发的模块串联，确保数据在 Phase 1 到 Phase 3 之间无损流转。

### 成员 B: 智能体适配与提示工程 (Agent Specialist & Prompt Engineering)-wyh
**定位**: 系统的“大脑”，负责 Phase 2 的核心逻辑，即“自然语言”到“工程语言”的转译。
**技术要求**: 精通 LLM Prompt 设计、熟悉软件工程文档规范、了解测试驱动开发 (TDD)。
**核心职责**:
1.  **Spec Adapter (Agent)**: 设计高鲁棒性的 Prompt，负责读取 `report.md` 并提取出精确的 `tech_spec.md`（包含 API 签名、数据结构、依赖库版本）。这是项目成败的关键。
2.  **Test Generator (Agent)**: 基于 AlphaCodium 理念，设计 Prompt 让 LLM 根据 Spec 生成可执行的 `pytest` 测试用例 (`tests/test_core.py`)。
3.  **Prompt 迭代与评测**: 建立简单的评测集，反复调优 Prompt，确保生成的 Spec 不产生幻觉，生成的测试代码语法正确且覆盖边界条件。

### 成员 C: 外部工具集成与验证闭环 (Integration Engineer & Verification Loop)-skx
**定位**: 系统的“双手”与“质检员”，负责外部黑盒工具的调用及代码质量的自动化验证。
**技术要求**: 熟悉 Subprocess/Shell 调用、Pytest 测试框架、日志分析。
**核心职责**:
1.  **Deep Research & Coding 集成**: 负责 `projects/deep_research` 和 `projects/code_scratch` 的黑盒调用封装（可能涉及环境隔离或子进程调用）。
2.  **Prompt Injection 构造**: 实现 Phase 3 的核心逻辑——构造“元指令” (Meta-Instruction)，将成员 B 生成的 Spec 和 Test 巧妙地注入到 Coding Agent 的上下文中。
3.  **外循环验证 (Outer Loop)**: 开发自动化测试执行模块，运行 `pytest`，捕获 stdout/stderr，并从错误日志中提取关键信息，构造“修复任务”反馈给 Coding Agent 实现自动重试。

---

**协作里程碑 (Milestones)**:
1.  **接口定义 (Day 1)**: 全员共同商定 `report.md`、`tech_spec.md` 的标准模板结构，以及各 Python 模块的输入输出接口。
2.  **模块开发 (Day 2-4)**:
    *   A 完成编排器框架与 Doc 接口；
    *   B 完成 Spec/Test 生成的 Prompt 验证；
    *   C 完成 Deep/Code 模块的黑盒调用与测试运行器。
3.  **集成联调 (Day 5)**: 串联 Phase 1 -> 2 -> 3，进行端到端测试。
