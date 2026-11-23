# Skill 管理：设计与实现

SDK 管理安装和更新，WebUI 适配请求与状态。使用步骤见[安装与更新](../user-guide/skill-management.md)，人工验收见[走查清单](skill-management-checklist.md)。

## 产品范围

用户可以从 GitHub 仓库或子目录、ModelScope Skill 页面及合集链接安装到全局或项目。安装记录保存真实仓库、分支或固定版本、提交与文件内容指纹。已有本地导入、目录发现及启停语义不变。

首期提供多选安装、手动及低频自动检查、单项差异预览、更新、本地修改保护、恢复旧版和旧安装关联来源。不提供商店搜索、自动覆盖升级、一键全部更新、三方合并或多级版本历史。

## 交互约定

安装在同一个弹窗中完成：输入链接和安装位置，查看候选，多选后安装。仓库版本详情按需展开，日常界面只显示名称、简介、来源和必要状态。

合集先展开独立成员，再发现各仓库内的 Skill。无法读取的成员单独显示错误；同名候选需要择一，“全选”跳过尚未选择的同名组。已安装项和与本地同名冲突的项不能通过安装入口覆盖。安装逐项提交，显示已安装、安装中、等待安装或失败；重试不会重复成功项。

列表使用“待更新”“本地有修改”“检查失败”等短标签。检查失败保留上次结果；列表加载失败保留已有卡片并提供重试。切换作用域和取消操作后，迟到响应不能覆盖新页面。

更新与恢复在详情抽屉内展示文件变化。文本按需读取 diff，二进制或大文件只显示变化状态。用户明确选择覆盖本地修改后才允许替换；成功提示为“已更新”或“已恢复”。“恢复旧版”保留最近一次实际替换前的内容，包括本地自定义文件。

## 来源与版本

| 来源 | 跟踪方式 |
| --- | --- |
| GitHub 仓库 / 子目录 | 解析默认分支或最长匹配的真实 ref，支持分支名中的 `/`；按 commit 下载 |
| GitHub tag / commit | 固定版本，不自动跟随分支 |
| ModelScope Skill | 保存精确 `registry_id`；原生 `owner/name` 与镜像 `@owner/name` 不混用；按仓库 commit 下载 |
| ModelScope 合集 | 仅作为发现入口；每个安装分别记录成员仓库，合集成员变化不自动增删本地 Skill |
| 本地已有托管 Skill | 用户显式关联来源；内容一致时只补记录，不一致时要求确认备份替换 |
| 标准目录 / 显式外部目录 | 继续原有发现机制，不在原位置自动升级 |

提交变化触发内容检查，但不等于该 Skill 有更新。内容指纹由相对路径、文件字节和可执行位计算，包含脚本、资源和二进制文件，排除 `.git` 等已知缓存。它用于一致性判断，不作为用户可读的版本号。

自动检查只在应用打开、进入项目或重新可见时触发；SDK 缓存成功结果 24 小时，失败有短暂退避，手动检查可强制刷新。普通列表读取不联网、不计算内容指纹。

## 一致性与任务边界

预览绑定作用域、候选提交、内容指纹和安装代次，有效期 30 分钟。确认时重新验证；本地内容、安装状态或候选文件已变化则返回 `PLAN_STALE`，要求重新预览。

文件提交在同一文件系统内准备新目录，保留旧目录，执行重命名替换，并写入安装记录和恢复日志。启动时恢复未完成提交；每个 Skill 独立成功或失败，不做跨 Skill 的整体事务。无内容变化的更新不消耗已有备份。

运行中的 SDK / WebUI 回合持有文件使用租约，相关作用域的替换与删除返回 `SKILL_BUSY`。等待用户下一次输入时释放租约；下一回合重新获取。短读锁保护发现和读取，避免观察到目录替换的间隙。操作取消会等待已开始的文件提交完成或恢复，再清理任务自己的暂存。

成功变更主动失效 Skill 索引并发布已有资源变更事件。正在运行的回合保持内容稳定，后续回合读取新内容。外部 SDK 宿主应使用 `SkillUseLease` 接入相同边界。

升级、恢复、手动编辑和原有增删改共用 Skill 变更通知。WebUI 在任务真正开始时同步目录并展开 Skill 调用；SDK 将当前可用 Skill 与会话的 `skill_surface.json` 比较，把变化提醒附加到本轮模型输入，消息成功写入会话记录后才推进基线。界面保留用户原文；仅检查到远端待更新不会通知模型，没有变化也不重复提醒。

WebUI 通过 `skills.update_notice_in_sdk: true` 显式启用 SDK 通知；原有 `skills.update_notice` 仍控制通知模式及系统提示中的 Skill 列表冻结。TUI 保留 `live_config.py` 的独立通知，不启用 SDK 通知，也不改变原有代码和行为，避免同一变化被重复提醒。

连续执行的排队任务保持使用租约，插话延续当前任务，不产生更新窗口。队列结束或停止后才允许管理操作替换文件；停止后保留的消息在恢复执行时使用当前 Skill。编辑器直接修改文件不受租约约束，应在空闲时操作。

## 输入、凭据与资源边界

仅接受支持的 GitHub / ModelScope 来源；带 URL 凭据或查询参数的安装链接被拒绝。ModelScope 令牌来自进程环境，仅发送给受信任的 ModelScope API；下载重定向不把它转发给对象存储。来源记录、任务回执和错误消息不保存令牌或原始请求头。

归档路径必须相对且不能越界；拒绝链接、设备文件和重复路径。下载限 64 MiB，解包限 128 MiB / 5000 项。合集限 100 个条目 / 候选、4 路并发和累计保留 256 MiB 内容；列表限时 30 秒，成员解析限时 240 秒。文本 diff 限单文件 256 KiB / 2000 行。

静态扫描用于提示需检查的内容。安装只下载和写入文件，不执行包内脚本；扫描不等同于运行沙箱或来源可信保证。

## 代码入口

| 位置 | 职责 |
| --- | --- |
| `ms_agent/skill/management/models.py` | 作用域、来源、候选、计划、逐项结果与安全错误契约 |
| `providers.py` | GitHub refs、ModelScope 精确身份、合集分页、按提交下载与凭据边界 |
| `content.py` | 有界归档解包、路径校验、包含二进制和权限的内容指纹及 diff |
| `service.py` | 发现、预览、检查、安装、更新、关联、恢复、安装记录与崩溃恢复 |
| `usage.py` / `io.py` | 跨进程使用租约、短读写锁、取消时等待已有文件工作结束 |
| `operations.py` | 有界并发操作、逐项进度、回执、取消与重启后的中断状态 |
| `ms_agent/config/skills_manager.py` | 让原有本地导入和删除参与同一写入边界 |
| `ms_agent/skill/loader.py` | 让托管目录发现和读取参与短读锁 |
| `ms_agent/skill/notice.py` | 复用原有增删改判定和提醒文案，保存兼容的会话通知基线 |
| `ms_agent/agent/llm_agent.py` / `callbacks/input_callback.py` | 回合运行时获取租约，等待输入及退出时释放 |
| `webui/backend/app/backends/ms_agent/chat.py` / `conversations.py` | 执行时刷新和展开 Skill；连续队列保持使用租约 |
| `webui/backend/app/backends/ms_agent/skill_management.py` | HTTP 作用域映射、元数据补充、操作启动、索引失效和资源事件 |
| `webui/backend/app/api/skills.py` / `schemas/skill.py` | 路由和请求校验，不另写下载或事务实现 |
| `webui/frontend/app/lib/skillManagement.ts` | 操作轮询、取消、迟到响应隔离及业务错误文案 |
| `SkillsFromLinkModal.tsx` | 仓库 / 合集候选、多选、静态检查与逐项安装 |
| `SkillCollection.tsx` / `SkillUpdatePanel.tsx` | 共享列表、状态筛选、失败重试、差异预览、更新与恢复 |
| `SkillUpdateChecks.tsx` | 随应用可见性与作用域变化触发低频检查 |

## 从一次安装理解数据流

1. `inspect_source(scope, source)` 解析来源和提交，下载到暂存目录，发现候选并保存来源快照。合集的每个候选携带独立 `source`；失败成员携带安全错误。
2. `prepare_install(scope, snapshot_id, candidate_ids)` 将选择固定为计划，检查命名冲突，复制候选并静态扫描。旧单仓库快照与合集快照共用 `_candidate_source()`，合集本身不会写入安装来源。
3. `apply_plan()` 逐项复核预览、风险确认与作用域租约，调用文件事务。成功记录独立安装 ID、runtime ID、来源、内容指纹和安装代次；计划重试复用成功回执。
4. 适配层失效索引并发出资源事件，列表和后续回合刷新。

更新先检查上游提交，再比较目标 Skill 内容，排除同仓库其他文件的变化。`prepare_update()` 和 `prepare_restore()` 复用替换计划；恢复保留替换前的实际文件，仅保留一代备份。`prepare_link()` 为无来源的托管目录补记录，不能猜测其历史版本。

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

`installations(scope)` 返回持久化安装 ID。更新使用 `prepare_update(scope, installation_id)`，恢复使用 `prepare_restore(...)`，旧安装关联使用 `prepare_link(scope, runtime_skill_id, source_snapshot_id, candidate_id)`。`diff(plan_id, item_id, path)` 返回某个变化文件的文本差异；二进制与较大文件只返回状态。

计划有效期为 30 分钟，绑定候选提交、本地内容和安装代次。确认时再验证这些条件，改变后返回 `PLAN_STALE`。默认 `local_changes_policy="abort"` 保留本地修改；宿主取得明确覆盖意图后才传 `"replace"`。静态检查需要确认时返回 `SAFETY_REVIEW_REQUIRED`，用户检查后才传 `acknowledge_risk=True`。批量安装逐项返回结果；重试同一个计划不会重复安装成功项。

SDK 运行循环与 WebUI 任务使用共享文件租约，阻止相关作用域运行中替换文件。外部宿主可用 `SkillUseLease([manager.tree(scope)])` 保护自己的执行边界。文件提交使用短锁，取消会等待已开始的临界提交结束或恢复。宿主启动时调用 `recover(scope)` 修复中断的提交，并在关闭时调用 `aclose()`。

安装目录仍是全局 `<MS_AGENT_HOME>/skills` 或项目 `.ms_agent/skills`。来源记录保存在同级 `skill-installs.json`，备份和恢复日志在同级 `skill-state/`；来源快照、预览计划与操作回执统一保存在全局 `<MS_AGENT_HOME>/skill-state/`。已有 `skills.json` 的来源、启停与优先级语义不变。

## HTTP 接口

| HTTP 接口（前缀 `/api/skills`） | 用途 |
| --- | --- |
| `POST /sources/inspect` | 发现来源候选 |
| `POST /install-plans` | 为所选候选准备安装 |
| `POST /update-checks` | 检查作用域或指定安装 |
| `POST /{skill_id}/update-plans`、`restore-plans`、`link-plans` | 准备更新、恢复、关联 |
| `GET /plans/{id}`、`/plans/{id}/diff` | 读取计划或指定文件变化 |
| `POST /plans/{id}/apply` | 应用计划，携带请求 ID 和明确覆盖 / 风险选择 |
| `GET /operations/{id}`、`DELETE /operations/{id}` | 查看或取消操作 |
| `GET /management-settings`、`PATCH /management-settings` | 管理自动检查设置 |

耗时操作返回 202 和 operation ID，状态为 queued、running、succeeded、partial、failed、cancelled 或 interrupted。失败按业务码呈现，不回传第三方异常、凭据或原始响应。

## 回归测试

测试按行为分层，所有构造 Skill 均写入 `tmp_path`，不需要仓库内的静态版本样例或发布脚本。

| 测试入口 | 主要覆盖 |
| --- | --- |
| `tests/skill/test_management.py` | 安装、更新、恢复、本地修改、并发、事务恢复、租约、取消及幂等 |
| `tests/skill/test_management_providers.py` | ref 解析、固定提交下载、精确身份和凭据边界 |
| `tests/skill/test_management_collections.py` | 分页、去重、部分不可用、同名候选、独立更新和取消清理 |
| `webui/backend/tests/test_skill_management.py` | 真实文件上的 HTTP 完整链路和作用域检查 |
| `tests/skill/test_notice_lifecycle.py` | 原有通知判定、会话基线、静默初始化及 TUI 独立通知 |
| `webui/backend/tests/test_skill_notice.py` | 两个聊天入口到 SDK 模型输入的提醒、历史展示、恢复、排队、插话、取消和写入失败 |
| `webui/frontend/scripts/checkSkillOperations.ts` | 进度、部分失败、取消和迟到响应隔离 |

SDK 全量回归使用仓库的外部模型跳过级别；真实模型和平台链路单独验收，不能把 mock 结果当作真实端到端结果：

```bash
MS_AGENT_HOME="$(mktemp -d)" TEST_LEVEL=-1 MS_AGENT_MODEL_CATALOG=local \
  PYTHON_DOTENV_DISABLED=1 MS_AGENT_WEBUI_BACKEND="$PWD/webui/backend" \
  webui/backend/.venv/bin/python -m pytest tests -q --import-mode=importlib
```

后端在 `webui/backend/` 执行 `.venv/bin/python -m pytest tests -q`。前端在 `webui/frontend/` 执行 `pnpm check:skills`、`pnpm typecheck` 和 `pnpm build`。实际运行时还应走查公共来源安装、受控上游变更、同会话读取新版、取消及中英文明暗主题。

测试结果、上游合并状态与未解决限制以本次提交交付记录为准。仓库不保存验收账号、机器路径、会话标识、模型输入输出或临时服务地址。
