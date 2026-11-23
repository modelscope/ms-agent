# Agent Skills

技能是一组任务说明及按需读取的参考资料、脚本。工具提供可执行操作，技能指导智能体何时、怎样组合这些操作；安装技能不会自动安装它依赖的所有工具或账户。

## 目录与发现

```text
report-helper/
├── SKILL.md
├── references/
└── scripts/
```

```markdown
---
name: report-helper
description: 整理用户提供的资料并生成带依据的摘要。
---

先确认资料范围，再逐份提取证据，最后生成摘要。
```

目录名决定MS-Agent中的 `skill_id`，frontmatter的name不是可以随意替代目录名的另一个ID。发现会扫描内置、用户和项目活动树以及显式来源；同名技能的覆盖与禁用由配置层决定。

```yaml
skills:
  sources:
    - type: local
      path: ./skills
  auto_discover: false
  disabled: []
  prompt_injection: all
  update_notice: false
```

`auto_discover`默认false，不等于所有活动技能树均关闭。显式 `sources` 使用type/path等结构化字段。外部来源只从可信仓库加载。

## 渐进加载

```{mermaid}
flowchart TD
 A[发现技能与元数据] --> B[筛选启用项]
 B --> C[生成摘要供模型选择]
 C --> D[按任务读取SKILL.md]
 D --> E[按需读取参考或调用脚本]
```

`prompt_injection`支持 `all`、`always_only`、`none`。`update_notice: true`稳定的是技能摘要段，其他系统提示层仍可更新。管理和执行依赖启用的工具，不能只凭技能文本推断执行已发生。

## 搜索与安全

默认BM25检索无需向量模型；vector/hybrid需相应依赖和模型。技能扫描、信任策略和LLM检查有各自配置，检查通过不表示技能内容无风险。使用前审查会执行的脚本、网络端点和文件范围。

当前 `ms-agent-skills` 是通过MCP访问框架能力的单个技能包，不是所有技能的集合，也不是自动安装WebUI的助手。用法见[MCP能力服务](capability-gateway.md)。

托管 Skill 的安装、更新和恢复由 `ms_agent.skill.management` 负责，与目录发现和运行时加载分离。WebUI 显式启用 `skills.update_notice_in_sdk`，由 SDK 在消息持久化时提交通知基线；TUI 保留原有独立通知。接口与一致性边界见[Skill 管理设计与实现](../development/skill-management.md)。

下一步：[技能与 MCP](../user-guide/skills-mcp.md)、[安装与更新](../user-guide/skill-management.md)、[Plugins](plugins.md)。实现：`skill/catalog.py`、`schema.py`、`runtime.py`、`prompt_injector.py`、`config/skills_manager.py`。
