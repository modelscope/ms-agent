# 与角色A集成计划

**日期**: 2025-11-27
**作者**: Role C

## 1. 集成概述

本计划描述了角色C如何以最小化修改的方式与Role A开发的orchestrator（编排器）进行集成。角色C负责外部工具集成与验证闭环，将通过最少的代码修改替换Role A提供的Mock实现，实现完整的"Research-to-Code"流水线。

## 2. 集成架构

### 2.1 系统组件关系
```
User Query
     |
     v
Orchestrator (Role A)
     |
     | (选择调用模式)
     v
Orchestrator -> Deep Research? -> Role C (Deep Research Adapter)
     |              |
     |              v
     |         (产出report.md)
     |              |
     +--------> Spec/Test Gen (Role B)
                       |
                       v
                 (tech_spec.md, tests/)
                       |
     +-----------------+
     |
     v
Orchestrator -> Code Integration? -> Role C (Code Adapter)
     |                                    |
     |                              (Prompt Injection)
     |                                    |
     |                              (Code Generation)
     |                                    |
     |                              (Test Execution)
     |                                    |
     +--> Orchestrator (处理结果或错误反馈)
```

### 2.2 集成接口

#### 2.2.1 输入接口
- **用户查询**: 从orchestrator传入的原始用户请求
- **工作目录**: orchestrator指定的工作目录路径
- **配置参数**: 从orchestrator传递的运行时参数

#### 2.2.2 输出接口
- **Deep Research结果**: 生成的 `report.md` 文件
- **Code生成结果**: 生成的代码文件在 `src/` 目录
- **验证结果**: 测试执行状态和错误日志
- **状态报告**: 执行进度和状态信息

## 3. 最小化修改集成实现

### 3.1 替换适配器实现
- **修改文件**: `orchestrator/adapters/deep_research_adapter.py`
  - 保持现有的类结构和接口
  - 将Mock实现替换为调用 `external_integration/deep_research_caller.py`

- **修改文件**: `orchestrator/adapters/code_adapter.py`
  - 保持现有的类结构和接口
  - 将Mock实现替换为完整的外部工具调用逻辑
  - 集成 `external_integration/prompt_injector.py` 和 `external_integration/test_runner.py`

### 3.2 数据格式约定
- 输入：遵循orchestrator定义的查询格式
- 输出：生成符合orchestrator期望的文件结构
- 日志：采用orchestrator支持的日志格式

## 4. 交互流程

### 4.1 Deep Research流程
1. Orchestrator调用`DeepResearchAdapter.run()`
2. 适配器使用`external_integration.DeepResearchCaller`执行外部调用
3. 将生成的报告保存到指定工作目录
4. 适配器返回执行结果给orchestrator

### 4.2 Code生成与验证流程
1. Orchestrator调用`CodeAdapter.run()`并传入spec和tests路径
2. 适配器使用`external_integration.PromptInjector`构造元指令
3. 使用`external_integration.CodeScratchCaller`执行代码生成
4. 使用`external_integration.TestRunner`执行验证测试
5. 适配器返回结果或错误信息给orchestrator

### 4.3 错误处理与重试流程
1. 如果验证失败，`TestRunner`生成错误日志
2. `CodeAdapter`将错误信息返回给orchestrator
3. Orchestrator根据错误信息决定是否重试
4. 如果重试，orchestrator再次调用`CodeAdapter`并传递错误信息

## 5. 修改范围总结

### 5.1 需要修改的文件（最小化修改）
- `orchestrator/adapters/deep_research_adapter.py` - 替换内部实现
- `orchestrator/adapters/code_adapter.py` - 替换内部实现

### 5.2 新增的外部模块
- `external_integration/` 目录及所有内容
- skx-docs目录文档

## 6. 部署与配置

### 6.1 环境要求
- 与orchestrator相同的Python环境
- 访问相同的服务（如LLM API、文件系统等）

### 6.2 集成方式
- 作为orchestrator的功能扩展模块
- 遵循orchestrator的版本管理策略
