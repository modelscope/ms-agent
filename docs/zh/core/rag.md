# RAG

RAG将文档索引、检索和回答增强连接起来。仓库保留基于LlamaIndex的实现；它与模型按需调用的 `localsearch` 是不同接入方式，不能认为配置其中一项就启用了另一项。

## 接口与过程

`RAG`抽象定义异步 `add_documents()`、`query()`和`retrieve()`。具体实现负责切块、embedding、索引保存及查询。

```{mermaid}
flowchart TD
 A[文档] --> B[加载与切块]
 B --> C[Embedding和索引]
 D[问题] --> E[检索相关片段]
 C --> E
 E --> F[仅返回片段或生成增强回答]
```

## 配置LlamaIndex实现

```{warning}
当前 `LLMAgent.prepare_rag()` 将字典 `rag_mapping` 当作函数调用，会在配置RAG后抛出 `TypeError: 'dict' object is not callable`。下列是实现的配置结构，不是当前Agent路径已经跑通的承诺。需要该功能时先修复/验证这一接入点，或在应用中显式使用RAG实现；普通按需检索可使用 `localsearch`。本次文档重构未修改SDK代码。
```

独立使用实现还需有效LLM和LlamaIndex/embedding依赖；首次加载可能下载模型：

```yaml
rag:
  name: LlamaIndexRAG
  embedding: Qwen/Qwen3-Embedding-0.6B
  chunk_size: 512
  chunk_overlap: 50
  retrieve_only: false
```

未显式指定 `storage_dir` 时，当前实现将索引放到工作目录 `.ms_agent/search_index/rag`。旧文档的 `./llama_index` 是历史默认说明，不应直接套用。

配置只选择实现，不会凭空导入资料。通过实现提供的文档添加/加载流程建立索引后再查询。`retrieve_only`用于只检索，不要同时依赖生成式query能力。

## 成本与边界

切块大小、重叠和embedding模型会影响索引成本及召回结果。更换embedding模型通常需要兼容的新索引；备份原资料和配置后重建，不直接复用不匹配的数据。

Agent的传统RAG接入会增强初始用户输入；按需搜索由独立工具承担。调用模型生成的总结不能替代引用原文，也不能证明没有遗漏。第三方组件的全局设置和运行资源应由集成层管理，避免多任务配置互相干扰。

下一步：[检索](retrieval.md)、[上下文](context.md)。实现：`rag/base.py`、`rag/llama_index_rag.py`、`LLMAgent.do_rag()`。
