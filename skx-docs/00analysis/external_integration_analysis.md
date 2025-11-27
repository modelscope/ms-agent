# 外部集成分析

**日期**: 2025-11-27
**作者**: Role C

## 1. 集成目标分析

根据 00comprehensive_integration_plan.md 文档，角色C的核心任务是实现对 `projects/deep_research` 和 `projects/code_scratch` 的黑盒调用，并开发验证闭环系统。严格遵循"无侵入"原则，不修改现有模块内部实现。

## 2. 技术实现方案分析

### 2.1 黑盒调用方案
- 使用 subprocess 调用 `projects/deep_research` 和 `projects/code_scratch`
- 所有集成代码均位于外部模块，不修改原项目代码
- 需要设置正确的运行时环境（PYTHONPATH、环境变量等）

### 2.2 与 Orchestrator 集成方案
- 基于 Role A 提供的适配器接口 (`deep_research_adapter.py`, `code_adapter.py`)
- 扩展适配器功能，实现完整的外部工具调用逻辑
- 遵循统一的数据流转标准

### 2.3 Prompt 注入实现方案
- 读取 `tech_spec.md` 和 `tests/` 目录内容
- 构造包含这些内容的 "元指令" (Meta-Instruction)
- 将元指令作为 `projects/code_scratch` 的输入query

## 3. 接口设计分析

### 3.1 与 Orchestrator 的接口
- 输入：用户查询、工作目录路径、配置参数
- 输出：Deep Research结果或Code生成结果、验证状态、错误日志
- 通过 Role A 的适配器模式与 Orchestrator 通信

### 3.2 内部组件接口
- `DeepResearchCaller.run(query, output_dir)`: 执行深度研究
- `CodeScratchCaller.run(prompt, work_dir)`: 执行代码生成
- `PromptInjector.inject(spec_path, test_dir)`: 构造元指令
- `TestRunner.run_tests(work_dir)`: 执行验证测试

## 4. 黑盒调用挑战分析

### 4.1 环境隔离
- 需要确保外部工具调用不会影响当前进程环境
- 可能需要使用独立的Python解释器进程
- 避免全局变量或状态冲突

### 4.2 配置传递
- 需要正确传递API密钥等配置给被调用的模块
- 确保被调用模块可以访问必要的模型和资源

### 4.3 错误处理
- 需要捕获外部工具的异常输出
- 解析错误信息以进行故障诊断
- 提供详细的错误日志反馈

## 5. 验证闭环设计分析

### 5.1 测试执行流程
- 在code_scratch生成代码后，自动执行pytest
- 捕获测试结果和错误日志
- 根据测试结果决定是否需要重试

### 5.2 错误反馈机制
- 解析pytest输出，提取关键错误信息
- 将错误信息构造为修复提示
- 与orchestrator的重试机制集成

## 6. 无侵入原则遵守分析

所有实现将严格遵守无侵入原则：
- 不修改 `ms_agent/` 下的任何文件
- 不修改 `projects/deep_research/` 下的任何文件
- 不修改 `projects/code_scratch/` 下的任何文件
- 所有新代码均位于 `external_integration/` 目录
- 通过适配器模式与orchestrator集成
