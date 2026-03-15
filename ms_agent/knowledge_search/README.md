# Sirchmunk Knowledge Search 集成

本模块实现了 [sirchmunk](https://github.com/modelscope/sirchmunk) 与 ms_agent 框架的集成，提供了基于代码库的智能搜索功能。

## 功能特性

- **智能代码搜索**: 使用 LLM 和 embedding 模型对代码库进行语义搜索
- **多模式搜索**: 支持 FAST、DEEP、FILENAME_ONLY 三种搜索模式
- **知识复用**: 自动缓存和复用之前的搜索结果，减少 LLM 调用
- **前端友好**: 提供详细的搜索日志和结果，方便前端展示
- **无缝集成**: 与 LLMAgent 无缝集成，像使用 RAG 一样简单

## 安装

```bash
pip install sirchmunk
```

## 配置

在您的 `agent.yaml` 或 `workflow.yaml` 中添加以下配置：

```yaml
llm:
  service: dashscope
  model: qwen3.5-plus
  dashscope_api_key: <your-api-key>
  dashscope_base_url: https://dashscope.aliyuncs.com/compatible-mode/v1

generation_config:
  temperature: 0.3
  stream: true

# Knowledge Search 配置
knowledge_search:
  # 必选：要搜索的路径列表
  paths:
    - ./src
    - ./docs

  # 可选：sirchmunk 工作目录
  work_path: ./.sirchmunk

  # 可选：LLM 配置（如不配置则自动复用上面 llm 模块的配置）
  # llm_api_key: <your-api-key>
  # llm_base_url: https://api.openai.com/v1
  # llm_model_name: gpt-4o-mini

  # 可选：Embedding 模型
  embedding_model: text-embedding-3-small

  # 可选：搜索模式 (DEEP, FAST, FILENAME_ONLY)
  mode: FAST

  # 可选：是否重用之前的知识
  reuse_knowledge: true
```

**LLM 配置自动复用机制**：

`SirchmunkSearch` 会自动从主配置的 `llm` 模块复用 LLM 相关参数：
- 如果 `knowledge_search.llm_api_key` 未配置，自动使用 `llm.{service}_api_key`
- 如果 `knowledge_search.llm_base_url` 未配置，自动使用 `llm.{service}_base_url`
- 如果 `knowledge_search.llm_model_name` 未配置，自动使用 `llm.model`

其中 `service` 是 `llm.service` 的值（如 `dashscope`, `modelscope`, `openai` 等）。

通过 CLI 使用时，只需传入 `--knowledge_search_paths` 参数，无需额外配置 LLM 参数。

## 使用方式

### 1. 通过 CLI 使用（推荐）

从命令行直接运行，无需编写代码：

```bash
# 基本用法 - LLM 配置自动从 agent.yaml 的 llm 模块复用
ms-agent run --query "如何实现用户认证功能？" --knowledge_search_paths "./src,./docs"

# 指定配置文件
ms-agent run --config /path/to/agent.yaml --query "你的问题" --knowledge_search_paths "/path/to/docs"
```

**说明**：
- `--knowledge_search_paths` 参数支持逗号分隔的多个路径
- LLM 相关配置（api_key, base_url, model）会自动从配置文件的 `llm` 模块复用
- 如果 `knowledge_search` 模块单独配置了 `llm_api_key` 等参数，则优先使用模块自己的配置

### 2. 通过 LLMAgent 使用

```python
from ms_agent import LLMAgent
from ms_agent.config import Config

# 从配置文件加载
config = Config.from_task('path/to/agent.yaml')
agent = LLMAgent(config=config)

# 运行查询 - 会自动触发知识搜索
result = await agent.run('如何实现用户认证功能？')

# 获取搜索结果
for msg in result:
    if msg.role == 'user':
        # 搜索详情（用于前端展示）
        print(f"Search logs: {msg.searching_detail}")
        # 搜索结果（作为 LLM 上下文）
        print(f"Search results: {msg.search_result}")
```

### 2. 单独使用 SirchmunkSearch

```python
from ms_agent.knowledge_search import SirchmunkSearch
from omegaconf import DictConfig

config = DictConfig({
    'knowledge_search': {
        'paths': ['./src', './docs'],
        'work_path': './.sirchmunk',
        'llm_api_key': 'your-api-key',
        'llm_model_name': 'gpt-4o-mini',
        'mode': 'FAST',
    }
})

searcher = SirchmunkSearch(config)

# 查询（返回合成答案）
answer = await searcher.query('如何实现用户认证？')

# 检索（返回原始搜索结果）
results = await searcher.retrieve(
    query='用户认证',
    limit=5,
    score_threshold=0.7
)

# 获取搜索日志
logs = searcher.get_search_logs()

# 获取搜索详情
details = searcher.get_search_details()
```

## 环境变量

可以通过环境变量配置：

```bash
# LLM 配置（如不设置则自动从 agent.yaml 的 llm 模块读取）
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL_NAME="gpt-4o-mini"

# Embedding 模型配置
export EMBEDDING_MODEL_ID="text-embedding-3-small"
export SIRCHMUNK_WORK_PATH="./.sirchmunk"
```

**注意**：通过 CLI 使用时，推荐直接在 `.env` 文件或 agent.yaml 中配置 LLM 参数，`SirchmunkSearch` 会自动复用。

## 测试

### 单元测试

```bash
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL_NAME="gpt-4o-mini"

python -m unittest tests/knowledge_search/test_sirschmunk.py
```

### CLI 测试

```bash
# 基本测试
python tests/knowledge_search/test_cli.py

# 指定查询
python tests/knowledge_search/test_cli.py -q "如何实现用户认证？"

# 仅测试 standalone 模式
python tests/knowledge_search/test_cli.py -m standalone

# 仅测试 agent 模式
python tests/knowledge_search/test_cli.py -m agent
```

## 配置参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| paths | List[str] | 必选 | 要搜索的目录/文件路径列表 |
| work_path | str | ./.sirchmunk | sirchmunk 工作目录，用于缓存 |
| llm_api_key | str | 从 llm 配置继承 | LLM API 密钥 |
| llm_base_url | str | 从 llm 配置继承 | LLM API 基础 URL |
| llm_model_name | str | 从 llm 配置继承 | LLM 模型名称 |
| embedding_model | str | text-embedding-3-small | Embedding 模型 ID |
| cluster_sim_threshold | float | 0.85 | 聚类相似度阈值 |
| cluster_sim_top_k | int | 3 | 聚类 TopK 数量 |
| reuse_knowledge | bool | true | 是否重用之前的知识 |
| mode | str | FAST | 搜索模式 (DEEP/FAST/FILENAME_ONLY) |
| max_loops | int | 10 | 最大搜索循环次数 |
| max_token_budget | int | 128000 | 最大 token 预算 |

## 搜索模式

- **FAST**: 快速模式，使用贪婪策略，1-5 秒内返回结果，0-2 次 LLM 调用
- **DEEP**: 深度模式，并行多路径检索 + ReAct 优化，5-30 秒，4-6 次 LLM 调用
- **FILENAME_ONLY**: 仅文件名模式，基于模式匹配，无 LLM 调用，非常快

## Message 字段扩展

为了支持知识搜索，`Message` 类增加了两个字段：

- **searching_detail** (Dict[str, Any]): 搜索过程日志和元数据，用于前端展示
  - `logs`: 搜索日志列表
  - `mode`: 使用的搜索模式
  - `paths`: 搜索的路径
  - `work_path`: 工作目录
  - `reuse_knowledge`: 是否重用知识

- **search_result** (List[Dict[str, Any]]): 搜索结果，作为下一轮 LLM 的上下文
  - `text`: 文档内容
  - `score`: 相关性分数
  - `metadata`: 元数据（如源文件、类型等）

## 工作原理

1. 用户发送查询
2. LLMAgent 调用 `prepare_knowledge_search()` 初始化 SirchmunkSearch
3. `do_rag()` 方法执行知识搜索：
   - 调用 `searcher.retrieve()` 获取相关文档
   - 将搜索结果存入 `message.search_result`
   - 将搜索日志存入 `message.searching_detail`
   - 将搜索结果格式化为上下文，附加到用户查询
4. LLM 接收 enriched query 并生成回答
5. 前端可以通过 `searching_detail` 展示搜索过程

## 故障排除

### 常见问题

1. **ImportError: No module named 'sirchmunk'**
   ```bash
   pip install sirchmunk
   ```

2. **搜索结果为空**
   - 检查 `paths` 配置是否正确
   - 确保路径下有可搜索的文件
   - 尝试降低 `cluster_sim_threshold` 值

3. **LLM API 调用失败**
   - 检查 API key 是否正确
   - 检查 base URL 是否正确
   - 查看搜索日志了解详细错误

### 日志查看

```python
# 查看搜索日志
logs = searcher.get_search_logs()
for log in logs:
    print(log)

# 或在配置中启用 verbose
knowledge_search:
  verbose: true
```

## 参考资源

- [sirchmunk GitHub](https://github.com/modelscope/sirchmunk)
- [ModelScope Agent](https://github.com/modelscope/modelscope-agent)
