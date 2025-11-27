# 用户操作指南：完整流程运行

本文档将指导您如何运行完整的"Research-to-Code"流程，从用户查询到代码生成和验证。

## 1. 环境准备

### 1.1 安装依赖

确保安装了项目的所有依赖：

```bash
pip install -r requirements/framework.txt
pip install -r requirements/research.txt
pip install -r requirements/code.txt
```

### 1.2 设置环境变量

在运行流程之前，您需要设置必要的环境变量：

```bash
# 设置OpenAI API密钥（必需）
export OPENAI_API_KEY="your-openai-api-key"

# 或者设置ModelScope API密钥
export MODELSCOPE_API_KEY="your-modelscope-api-key"

# 可选：设置Exa API密钥用于增强搜索（deep research）
export EXA_API_KEY="your-exa-api-key"

# 可选：设置SerpAPI密钥作为搜索引擎备选
export SERPAPI_API_KEY="your-serpapi-key"
```

## 2. 运行完整流程

### 2.1 使用orchestrator运行流程

orchestrator是整个流程的编排器，集成了所有组件：

```bash
cd /path/to/seu-ms-agent

# 运行完整流程（Research -> Spec -> Test -> Code -> Verify）
python3 orchestrator/main.py "Build a simple calculator app" --mode full

# 或者仅运行研究阶段
python3 orchestrator/main.py "Analyze latest AI trends" --mode research_only

# 使用本地文件进行分析
python3 orchestrator/main.py "Analyze the provided research paper" --files ./paper.pdf --mode full
```

### 2.2 参数说明

- `query`: 用户的自然语言需求或问题
- `--files`: 附加的本地文件路径列表（可选）
- `--urls`: 附加的URL列表（可选）
- `--mode`: 运行模式，`research_only` 或 `full`（默认）

## 3. 流程详解

### 3.1 Phase 1: Research（研究阶段）

orchestrator会根据输入决定使用哪种研究模式：

- **Deep Research**: 如果没有提供附件，系统会调用`projects/deep_research`进行网络搜索
- **Doc Research**: 如果提供了文件或URL，系统会调用`ms_agent/app/doc_research.py`进行文档分析

### 3.2 Phase 2: Spec Generation（规范生成）

系统会调用Role B的适配器（当前为Mock实现）生成技术规范：
- 输入：`report.md`（研究结果）
- 输出：`tech_spec.md`（技术规范）

### 3.3 Phase 3: Test Generation（测试生成）

系统会调用Role B的适配器（当前为Mock实现）生成测试用例：
- 输入：`tech_spec.md`（技术规范）
- 输出：`tests/`目录（测试文件）

### 3.4 Phase 4: Coding & Verify（编码与验证）

这是角色C负责的部分，包含以下子步骤：

1. **Prompt注入**：使用`PromptInjector`将技术规范和测试用例构造成"元指令"
2. **代码生成**：通过`CodeScratchCaller`调用`projects/code_scratch`生成代码
3. **验证**：使用`TestRunner`运行`pytest`验证生成的代码
4. **错误反馈**：如果验证失败，提取错误信息并触发重试机制

## 4. 查看输出

每次运行都会在`workspace/`目录下生成一个带时间戳的文件夹：

```
workspace/run_YYYYMMDD_HHMMSS/
├── report.md         # 研究阶段产出
├── tech_spec.md      # 规范阶段产出
├── tests/            # 测试生成阶段产出
│   └── test_core.py
├── src/              # 编码阶段产出
│   └── main.py
└── logs/
    └── orchestrator.log # 详细运行日志
```

## 5. 故障排除

### 5.1 常见错误

**错误1：API Key未设置**
```
ValueError: API Key is missing. Please set OPENAI_API_KEY or MODELSCOPE_API_KEY.
```
解决方案：按第1.2节设置相应的API密钥。

**错误2：超时错误**
```
Code Scratch execution timed out after 300 seconds
```
解决方案：
- 检查网络连接
- 增加API配额或尝试在非高峰时段运行

**错误3：pytest失败**
系统会自动提取错误信息并尝试重试，您可以在日志中查看详细错误信息。

### 5.2 调试日志

详细的运行日志保存在：
```
workspace/run_YYYYMMDD_HHMMSS/logs/orchestrator.log
```

## 6. 自定义配置

### 6.1 配置文件

您可以通过配置文件自定义运行参数，创建一个YAML配置文件：

```bash
python3 orchestrator/main.py "Your query" --config /path/to/your/config.yaml
```

### 6.2 重试设置

在外循环验证机制中，默认最大重试次数为3次，您可以在配置中调整此参数。

## 7. 验证流程完整性

运行以下命令来验证整个流程是否正常工作：

```bash
# 1. 验证外部集成模块
python3 tests/test_external_integration.py

# 2. 运行一个简单测试查询
python3 orchestrator/main.py "Say hello world" --mode full

# 3. 检查输出目录
ls -la workspace/
```

## 8. 进一步操作

在流程成功运行后，您可以：

1. **检查生成的代码**：查看`src/`目录中的文件
2. **运行生成的测试**：手动在工作目录中运行`pytest tests/`
3. **分析日志**：查看`orchestrator.log`了解详细执行过程
4. **调整参数**：根据需求修改配置文件，再次运行
