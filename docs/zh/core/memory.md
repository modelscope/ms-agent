# 记忆

记忆保存跨轮次、跨会话有复用价值的信息。它与记录原始对话的[会话日志](sessions.md)、控制模型输入长度的[上下文](context.md)分工不同。是否自动提取、如何检索、何时生效，由所选后端决定。

## 统一接口，可替换后端

```{mermaid}
flowchart TD
  A[智能体生命周期] --> B[MemoryOrchestrator]
  B --> C[MemoryBackend 协议]
  C --> D[文件后端]
  C --> E[检索或外部适配器]
  C --> F[自定义后端]
  G[注册表与配置] --> B
```

`MemoryOrchestrator` 将注入、写入、压缩前处理、检索和关闭转发给后端。公共契约是 `MemoryBackend`；`BaseMemoryBackend` 为可选方法提供默认行为。内部存储/提取器不是必须实现的额外公共接口。

当前仓库包含 `file`、`reme`、`mempalace`、`mem0`、`byterover`、`supermemory` 适配代码。依赖、凭据和服务要求不同；存在适配器不等于环境已就绪，也不代表所有第三方链路已经通过测试。

## 从文件后端开始

```yaml
memory:
  unified_memory:
    enabled: true
    storage:
      backend: file
      file:
        memory_path: MEMORY.md
        char_limit: 2200
    ingest_interval: 1
```

由此路径载入且未指定 `base_dir` 时，记忆目录根据工作目录落在 `.ms_agent/memory` 下；WebUI 可配置独立作用域。文件后端使用有界记忆，不意味着把全部对话自动复制进 MEMORY.md。管理操作见[记忆管理](../user-guide/memory.md)。

## 最小自定义后端

```python
from copy import deepcopy
from ms_agent.memory.unified import BaseMemoryBackend, backend_registry

class DemoBackend(BaseMemoryBackend):
    def __init__(self, config):
        self.config = config

    async def start(self, **kwargs):
        pass

    async def inject(self, messages):
        return deepcopy(messages)

    async def close(self):
        pass

backend_registry.register('demo', DemoBackend)
assert backend_registry.resolve('demo') is DemoBackend
```

在加载配置前导入注册模块，再选择 `storage.backend: demo`。这个例子只展示协议，不存储数据；实际后端需按需要实现 `on_messages`、`search`、工具及压缩回调。关闭时释放其持有的连接或锁。

## 压缩前提取

压缩可先从原始消息中提取长期事实，使用实际记忆模型的预算，给提示、既有记忆和输出预留空间，输入过长则分片。文件后端默认 `char_limit: 2200` 是最终记忆文件的字符限制，不是模型 token 窗口。

提取结果区分 `updated`、`unchanged`、`skipped`、`failed`。分片全部成功才替换记忆文件；普通失败保留旧记忆及原始消息序号，让后续压缩重试，不阻止合格摘要提交。用户取消会中止操作。记忆文件与日志分别写入，崩溃恢复可能重复提取，因此不应承诺跨存储事务。

## 写入、共享与限制

- 完整回复后的写入可能在后台运行。待写消息按快照处理，成功后才推进去重账本；不能把“已调度”当作“已保存”。
- 关闭和重配置协调待写任务与存储锁；同一存储可能被多个会话共享，避免自行构造互相争抢本地数据库的实例。
- 文件内容、召回块和系统提示快照的刷新时机不同，修改后先验证下一轮或新会话实际看到什么。
- 旧 `context_compressor`、`refine_condenser`、`code_condenser` 仍被部分项目使用，不应批量删除。
- 不在记忆中保存密钥、完整私有文件或无必要的原始日志。远程后端可能将信息发送给外部服务。

实现：`memory/unified/protocols.py`、`registry.py`、`orchestrator.py`、`backends/`。下一步：[个性化](personalization.md)、[存储布局](../development/storage.md)。
