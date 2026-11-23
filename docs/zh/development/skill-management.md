# Skill 管理：设计与实现

SDK 负责安装、更新和恢复，WebUI 提供交互与异步 HTTP 接口。操作流程见[用户指南](../user-guide/skill-management.md)，验收见[走查清单](skill-management-checklist.md)。TUI 本次保留独立通知。

<a id="产品范围"></a>
<a id="交互约定"></a>

## 代码入口

| 入口 | 职责 |
| --- | --- |
| `ms_agent/skill/management/service.py`、`models.py` | 来源快照、变更计划、安装记录、文件事务与恢复 |
| 同目录 `providers.py`、`content.py` | 来源解析、下载、归档校验、内容指纹与 diff |
| 同目录 `usage.py`、`io.py`、`operations.py` | 文件租约、取消安全、有界并发与操作进度 |
| `ms_agent/config/skills_manager.py`、`skill/loader.py` | 原有导入、删除与读取接入同一文件边界 |
| `ms_agent/skill/notice.py`、`agent/llm_agent.py` | 通知判定与回合持久化 |
| `webui/backend/app/backends/ms_agent/` | `skill_management.py` 适配管理接口；`chat.py`、`conversations.py` 管理执行时刷新与队列租约 |
| `webui/frontend/app/components/resources/` | `SkillsFromLinkModal` 安装；`SkillCollection` 列表；`SkillUpdatePanel` 预览、更新与恢复；`SkillUpdateChecks` 自动检查 |
| `webui/frontend/app/lib/skillManagement.ts` | 操作轮询、取消、迟到响应隔离与错误展示 |

## 从一次安装理解数据流

`inspect_source()` 解析并下载来源，保存候选快照；`prepare_install()` 固定选择、检查冲突并静态扫描；`apply_plan()` 复核后逐项提交，失效索引并发出资源变更事件。

更新、恢复和关联来源分别通过 `prepare_update()`、`prepare_restore()`、`prepare_link()` 生成计划，再共用提交入口。`installations(scope)` 返回持久化安装 ID，`diff(plan_id, item_id, path)` 按需读取文件差异。

## 一致性与任务边界

- **计划**：绑定作用域、候选提交、本地内容和安装代次，30 分钟过期；应用时再次验证，变化后返回 `PLAN_STALE`。默认 `local_changes_policy="abort"`；用户确认覆盖后才用 `"replace"`。风险确认使用 `acknowledge_risk=True`，否则返回 `SAFETY_REVIEW_REQUIRED`。
- **提交**：同文件系统暂存、备份、重命名替换并保存记录。批次逐项提交，重试复用成功回执；无内容变化不消耗备份。取消等待已开始的文件提交完成或恢复。宿主启动时调用 `recover(scope)`，关闭时调用 `aclose()`。
- **执行**：SDK / WebUI 使用 `SkillUseLease` 阻止相关作用域运行中替换或删除，冲突返回 `SKILL_BUSY`；短读锁保护发现与读取。连续队列和插话保持租约，队列结束或停止后释放。外部宿主可用 `SkillUseLease([manager.tree(scope)])` 接入；编辑器直接写文件不受其约束。

WebUI 在任务真正开始时刷新目录并展开 Skill，避免排队消息使用旧内容。SDK 比较当前可用 Skill 与会话 `skill_surface.json`，将提醒附加到模型输入；消息持久化成功后才推进基线，聊天气泡保留用户原文。无变化或仅远端待更新时不通知。

`skills.update_notice` 冻结系统提示中的 Skill 列表；WebUI 另启用 `skills.update_notice_in_sdk` 交由 SDK 通知。TUI 继续使用 `live_config.py` 的独立通知，避免重复发送。

## 来源与版本

GitHub 查询真实 refs，支持含 `/` 的分支；分支跟踪新提交，tag / commit 固定版本。匿名 API 限流时回退到公开 Git 查询，需要系统 `git`。

ModelScope 保存精确 `registry_id`，区分原生 `owner/name` 与镜像 `@owner/name`，按 commit 下载；兼容旧记录，但后续检查不切换条目身份。除页面链接外，接受 `@owner/name`、`modelscope://owner/name[@revision][#subdir]`。合集仅用于发现，每个安装独立保存成员来源。

更新比较相对路径、文件字节和可执行位，包含脚本、资源与二进制文件，排除 `.git` 等缓存；同仓库其他 Skill 的变化不触发更新。指纹不作为展示版本，普通列表读取不联网或计算指纹。

文件位于 `<MS_AGENT_HOME>/skills` 或项目 `.ms_agent/skills`；同级 `skill-installs.json` 保存来源，`skill-state/` 保存备份与恢复日志。来源快照、计划和回执位于全局 `skill-state/`；原有 `skills.json` 语义不变。

## 输入、凭据与资源边界

拒绝带凭据或查询参数的来源 URL，以及越界路径、链接、设备文件和重复归档项。`MODELSCOPE_API_KEY` 仅发送给受信任的 ModelScope API，不转发到下载重定向目标，也不写入记录或错误。安装不执行脚本；静态扫描不等同于运行沙箱。

下载限 64 MiB；解包限 128 MiB / 5000 项；合集限 100 个条目 / 候选、4 路并发、累计保留 256 MiB，列表 / 成员解析分别限时 30 / 240 秒；文本 diff 限单文件 256 KiB / 2000 行。

## SDK 示例

```python
import asyncio
import uuid

from ms_agent.project.paths import global_home
from ms_agent.skill.management import SkillManagementService, SkillScope


async def main():
    manager = SkillManagementService(str(global_home()))
    scope = SkillScope()  # 项目安装使用 SkillScope("/path/to/project")
    try:
        preview = await manager.inspect_source(
            scope, "https://github.com/anthropics/skills/tree/main/skills/pdf")
        plan = await manager.prepare_install(
            scope, preview.id, [preview.candidates[0].id])
        # 宿主在此展示来源、文件变化及 plan.items[].safety。
        results = await manager.apply_plan(plan.id, request_id=uuid.uuid4().hex)
        for item in results:
            print(item.status, item.error)
        print(await manager.check_updates(scope, force=True))
    finally:
        await manager.aclose()


asyncio.run(main())
```

宿主需在应用计划前展示来源、文件变化和静态检查结果，并取得相应确认。

## HTTP 接口

前缀为 `/api/skills`。耗时操作返回 202 与 operation ID；客户端轮询状态和逐项结果，可取消或重试。

| 接口 | 用途 |
| --- | --- |
| `POST /sources/inspect`、`/install-plans` | 发现候选、准备安装 |
| `POST /update-checks` | 检查更新 |
| `POST /{skill_id}/update-plans`、`restore-plans`、`link-plans` | 准备更新、恢复、关联 |
| `GET /plans/{id}`、`/plans/{id}/diff` | 读取计划与文件差异 |
| `POST /plans/{id}/apply` | 携带 request ID 和确认选项应用计划 |
| `GET /operations/{id}`、`DELETE /operations/{id}` | 查询、取消操作 |
| `GET /management-settings`、`PATCH /management-settings` | 自动检查设置 |

## 回归测试

SDK 行为见 `tests/skill/test_management*.py`、`test_notice_lifecycle.py`；HTTP 和会话链路见 `webui/backend/tests/test_skill_management.py`、`test_skill_notice.py`。测试 Skill 均在临时目录生成。

开发检查命令见 [WebUI README](https://github.com/modelscope/ms-agent/blob/main/webui/README_ZH.md)。真实模型、公共来源及界面体验按[走查清单](skill-management-checklist.md)验收，不能以 mock 结果替代。
