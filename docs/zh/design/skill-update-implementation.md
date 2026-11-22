# Skill 管理：开发概要与验证

本功能由 SDK 管理安装和更新，WebUI 适配请求与状态。产品边界见[设计说明](skill-update-management.md)，人工复查见[走查清单](skill-update-walkthrough.md)，用户文档提供[中文](../Components/skill-management.md)与[English](../../en/Components/SkillManagement.md)。

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
| `ms_agent/agent/llm_agent.py` / `callbacks/input_callback.py` | 回合运行时获取租约，等待输入及退出时释放 |
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

## 存储与接口

安装目录是全局 `<MS_AGENT_HOME>/skills` 或项目 `.ms_agent/skills`。同级 `skill-installs.json` 保存安装记录；同级 `skill-state/` 保存事务和备份。全局 `skill-state/` 还保存有有效期的来源快照、计划与操作回执。原有 `skills.json` 的启停、来源优先级不变。

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
| `webui/frontend/scripts/checkSkillOperations.ts` | 进度、部分失败、取消和迟到响应隔离 |

SDK 全量回归使用仓库的外部模型跳过级别；真实模型和平台链路单独验收，不能把 mock 结果当作真实端到端结果：

```bash
MS_AGENT_HOME="$(mktemp -d)" TEST_LEVEL=-1 MS_AGENT_MODEL_CATALOG=local \
  PYTHON_DOTENV_DISABLED=1 MS_AGENT_WEBUI_BACKEND="$PWD/webui/backend" \
  webui/backend/.venv/bin/python -m pytest tests -q --import-mode=importlib
```

后端在 `webui/backend/` 执行 `.venv/bin/python -m pytest tests -q`。前端在 `webui/frontend/` 执行 `pnpm check:skills`、`pnpm typecheck` 和 `pnpm build`。实际运行时还应走查公共来源安装、受控上游变更、同会话读取新版、取消及中英文明暗主题。

测试结果、上游合并状态与未解决限制以本次提交交付记录为准。仓库不保存验收账号、机器路径、会话标识、模型输入输出或临时服务地址。
