# Mock实现说明文档

## 概述

本文档说明了如何使用现有的Mock实现，确保在各角色的实际代码就位前，主流程可以完整运行。

## Mock组件概述

### 1. Role A (Orchestrator) - 已实现
- `orchestrator/main.py` - 主入口和编排逻辑
- `orchestrator/core/` - 核心组件（工作区管理、流程控制等）
- `orchestrator/utils/` - 工具函数

### 2. Role B (Spec/Test Agent) - Mock已实现
- `orchestrator/adapters/spec_adapter.py` - 将report.md转换为tech_spec.md
- `orchestrator/adapters/test_gen_adapter.py` - 基于tech_spec.md生成测试用例

### 3. Role C (Coding Agent) - Mock已实现
- `orchestrator/adapters/code_adapter.py` - 基于spec和tests生成代码

## 主流程验证

使用Mock实现，可以验证完整流程：

```
User Query
    ↓
Orchestrator (Role A)
    ↓
Deep/Doc Research (Role A) -> report.md
    ↓
Spec Adapter (Role B Mock) -> tech_spec.md
    ↓
Test Gen Adapter (Role B Mock) -> tests/
    ↓
Code Adapter (Role C Mock) -> src/
    ↓
Verification -> Success/Fail
```

## 使用示例

要运行带有Mock实现的完整流程：

```bash
# 确保在项目根目录下
cd /path/to/seu-ms-agent

# 运行orchestrator（将使用Mock实现）
python3 orchestrator/main.py "Build a simple calculator" --mode full
```

## Mock实现功能

### Spec Adapter Mock
- 读取 `report.md`
- 使用模板生成 `tech_spec.md`
- 包含基本的架构描述和API定义

### Test Gen Adapter Mock
- 读取 `tech_spec.md`
- 生成基本的 `tests/test_core.py`
- 包含占位测试用例

### Code Adapter Mock
- 接收查询、spec路径和tests路径
- 生成基本的 `src/main.py`
- 包含简单的主函数

## 文件流转

Mock实现确保以下文件在工作目录中正确生成：
- `report.md` - 由Research阶段生成
- `tech_spec.md` - 由Spec Adapter生成
- `tests/test_core.py` - 由Test Gen Adapter生成
- `src/main.py` - 由Code Adapter生成

## 过渡到实际实现

当角色B或角色C的实际实现完成后：
1. 替换相应的适配器文件
2. 保持相同的接口和输入输出格式
3. 运行相同的端到端测试验证功能
