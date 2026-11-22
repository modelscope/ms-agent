# 检索

本地检索让模型在需要时寻找工作目录中的证据。它不同于网络搜索，也不同于提前把检索结果注入用户消息的[RAG](rag.md)路径。

## 按需启用 localsearch

```yaml
tools:
  localsearch:
    mcp: false
    paths: [./src, ./docs]
    mode: FAST
```

也可以使用CLI：

```bash
ms-agent run --query '说明配置加载流程' --knowledge_search_paths './src,./docs'
```

路径应实际存在；工具可将搜索缩小到配置根目录内的文件/子目录。它不是任意读取服务器文件的授权。未提供独立搜索LLM配置时复用Agent模型；需要分开时配置 `llm_api_key`、`llm_base_url`、`llm_model_name`。

## 查询与证据

`localsearch`由模型按任务调用，而不是每轮自动搜索。返回的文件路径和片段应作为解释依据，必要时再读取原文。旧 `knowledge_search`配置保留兼容，新增配置优先使用工具块。

搜索索引、缓存和原始文件不同。资料改动后检查索引/缓存刷新策略，不要把旧命中当成当前代码事实。长工具结果可能被裁剪或写入产物目录。

## 与其他检索机制的区别

| 机制 | 对象 |
| --- | --- |
| localsearch | 本地代码和资料 |
| web_search | 外部搜索引擎 |
| 技能检索 | 可用Skill的选择 |
| 记忆召回 | 跨任务持久知识 |
| RAG | 文档索引与回答增强流程 |

关键词、向量、重排等后端有不同成本和依赖；不要为基础读取直接安装全部重型依赖。验证安装/导入不能替代真实检索质量验证。

下一步：[RAG](rag.md)、[工具](tools.md)。实现：`tools/search/localsearch_tool.py`、`sirchmunk_search.py`、`retriever/`。
