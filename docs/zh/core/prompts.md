# 提示装配

系统提示不仅包含一句角色描述。MS-Agent按层装配基础行为、用户与项目约定、运行能力和技能摘要，让这些信息能分别配置和更新。

## 先区分两种输入

`prompt.system` 定义基础系统提示；`prompt.query` 是初始任务输入。配置了system并不代表任务已经开始，也不会让用户资料和项目指令自动消失。

```yaml
prompt:
  system: >-
    你是资料整理助手。先说明依据，不确定时明确说明。
  query: 总结当前任务的目标。
personalization:
  enabled: true
```

显式system替换的是基础层，不是整个装配结果。若应用要求自包含行为，应同时检查个性化、技能和其他扩展配置。

## 装配与刷新

```{mermaid}
flowchart TD
 A[基础系统提示] --> E[系统提示构建器]
 B[SOUL / AGENTS / PROFILE] --> E
 C[运行与工具相关说明] --> E
 D[技能摘要] --> E
 E --> F[内容比对和刷新]
 F --> G[本轮模型输入]
```

文件内容有读取缓存和注入限制。框架可能清除frontmatter与HTML注释后再注入；文件不为空不等于所有字节都会发送给模型。

`skills.update_notice`只固定技能摘要段，并通过后续消息通知技能变化。它不冻结SOUL、AGENTS、PROFILE或整个system prompt，也不保证供应商前缀缓存命中。

## 编写可靠的项目指令

将跨任务约定放在个性化/项目文件，把当前任务放在用户输入。指令应说明目标、约束和验证方式，避免粘贴大量历史日志；日志和可检索资料有自己的存储。

模型切换、技能热同步、文件编辑都可能改变有效提示。排查时确认来源与生效时机，不只查看一个YAML字段。不要把提示当作权限边界；真正的授权由[权限模块](permissions.md)执行。

下一步：[个性化](personalization.md)、[Skills](skills.md)、[上下文](context.md)。实现：`prompting/`、`LLMAgent._build_system_content()`及刷新逻辑。
