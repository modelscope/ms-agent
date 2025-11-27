# Orchestrator 模块深度分析与结构说明

**日期**: 2025-11-26
**版本**: v0.1 (Initial Architecture)
**对应命令**: `python3 orchestrator/main.py ...`

## 1. 命令解析
当您执行以下命令时：
```bash
python3 orchestrator/main.py "Build a calculator based on this requirement doc" --files ./req.txt
```

系统内部发生了以下流转：
1.  **入口 (`main.py`)**: 接收命令行参数。解析出 `query` 为 "Build a calculator..."，并检测到 `--files` 参数。
2.  **初始化 (`core/`)**:
    *   加载配置 (`config.py`)。
    *   创建一个新的带时间戳的工作目录 (`workspace/run_xxxx/`)。
    *   初始化日志系统 (`utils/logger.py`)。
3.  **Phase 1 (Research)**:
    *   由于检测到 `--files`，系统智能选择 `DocResearchAdapter`。
    *   适配器调用底层的 `ms_agent` 文档分析能力，读取 `req.txt`，生成 `report.md` 并保存到工作区。
4.  **Phase 2-4 (Generation & Coding)**:
    *   (当前为 Mock) 读取 `report.md`，生成技术规格书 `tech_spec.md`。
    *   (当前为 Mock) 基于规格书生成测试用例 `tests/`。
    *   (当前为 Mock) 生成代码 `src/`。
5.  **验证**: 运行 `pytest` 检查生成的代码是否通过测试。

---

## 2. 项目结构深度解析 (`orchestrator/`)

`orchestrator` 模块设计遵循 **"洋葱架构" (Onion Architecture)** 和 **"适配器模式" (Adapter Pattern)**，旨在不修改上游代码的前提下，将现有能力串联成复杂流水线。

```text
orchestrator/
├── main.py                     # [CLI入口]
│                               # 程序的"大门"。负责参数解析(Argparse)、异常捕获顶层逻辑、
│                               # 以及各个阶段(Phase 1-4)的宏观调度。
│
├── core/                       # [核心领域层] (Business Logic)
│   ├── config.py               # 配置中心。统一管理 API Keys、模型名称、重试次数。
│   │                           # 优先读取环境变量，支持 .env 文件。
│   │
│   ├── workspace.py            # 战场环境管理。
│   │                           # 职责：每次任务都在 workspace/ 下创建一个隔离的
│   │                           # run_YYYYMMDD_HHMMSS 目录，防止任务间文件冲突。
│   │                           # 提供 get_path() 方法，统一管理文件路径。
│   │
│   ├── flow.py                 # 交互流控制器。
│   │                           # 职责：实现 "Human-in-the-Loop"。在关键节点(如Spec生成后)
│   │                           # 暂停程序，等待用户审查/修改文件，然后继续。
│   │
│   ├── templates.py            # 提示词与文档模板。
│   │                           # 定义了 report.md 和 tech_spec.md 的标准 Markdown 结构。
│   │
│   └── const.py                # 常量定义。文件名(如 report.md)的唯一定义处。
│
├── adapters/                   # [适配器层] (Interface Adapters)
│   │                           # 核心设计模式：将外部不稳定的接口转换为内部稳定的接口。
│   │
│   ├── base.py                 # 抽象基类。定义了所有 Agent 必须实现的 run() 方法标准。
│   │
│   ├── doc_research_adapter.py # Doc Research 适配器。
│   │                           # 作用：封装 ms_agent.workflow，屏蔽 Gradio UI 依赖，
│   │                           # 仅调用核心文档分析逻辑。
│   │
│   ├── deep_research_adapter.py# Deep Research 适配器。
│   │                           # 作用：根据配置自动选择 Arxiv/Exa/SerpApi 引擎，
│   │                           # 执行联网深度搜索。
│   │
│   ├── spec_adapter.py         # [Mock] Spec 生成适配器 (Role B)。
│   ├── test_gen_adapter.py     # [Mock] 测试生成适配器 (Role B)。
│   └── code_adapter.py         # [Mock] 代码生成适配器 (Role C)。
│
└── utils/                      # [基础设施层] (Infrastructure)
    ├── logger.py               # 双路日志。
    │                           # Console: 输出简洁的 INFO 信息给用户看。
    │                           # File: 输出详细的 DEBUG 信息到 logs/orchestrator.log 供调试。
    │
    └── verifier.py             # 验证器。
                                # 封装 subprocess 调用 pytest，返回 (exit_code, stdout, stderr)，
                                # 为外循环(Outer Loop)提供反馈信号。
```

---

## 3. 运行时目录结构 (`workspace/`)

这是您执行命令后，实际产出物存放的地方。它被设计为**完全自包含**的，意味着您可以直接打包某个 `run_xxx` 目录发给别人，里面包含了从需求到代码的所有过程资产。

```text
workspace/
└── run_20251126_130922/        # [任务容器] 以时间戳命名，隔离每次运行
    │
    ├── report.md               # [阶段1产出] 研究报告
    │                           # 包含：从 req.txt 或网络搜索中提取的关键知识、API定义建议。
    │
    ├── tech_spec.md            # [阶段2产出] 技术规格书
    │                           # 包含：系统架构、文件结构、API签名。这是连接 Research 和 Code 的桥梁。
    │
    ├── tests/                  # [阶段3产出] 测试用例
    │   └── test_core.py        # 基于 Spec 生成的自动化测试代码 (Pytest)。
    │
    ├── src/                    # [阶段4产出] 源代码
    │   └── main.py             # Agent 编写的实际业务代码。
    │
    └── logs/                   # [系统日志]
        └── orchestrator.log    # 记录了每一步的 LLM 调用、Token 消耗、错误堆栈。
```

## 4. 设计理念总结

1.  **无侵入 (Non-Invasive)**:
    我们没有修改 `ms_agent` 或 `projects/` 下的任何一行既有代码。所有的集成都是通过 `import` 和 `adapters` 封装实现的。这保证了上游仓库更新时，我们的编排器不会轻易损坏。

2.  **数据驱动 (Data-Driven Flow)**:
    流程不是通过函数调用栈隐式传递的，而是通过文件系统上的**显式工件** (Artifacts: report.md -> spec.md -> code) 传递的。这使得人工可以随时介入（修改 Markdown 文件），Agent 也能理解上下文。

3.  **外循环 (Outer Loop)**:
    Code Generator 不再是“一锤子买卖”。`main.py` 中包含一个 `while` 循环，利用 `verifier.py` 的反馈结果，如果测试失败，会自动把错误日志喂回给 Coding Agent 进行重试。
