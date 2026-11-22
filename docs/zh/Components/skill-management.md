# Skill 安装与更新

WebUI 与 SDK 共用 `ms_agent.skill.management` 管理托管 Skill 的安装、来源追踪、检查、更新和恢复。原有 `SkillCatalog` 继续负责运行时发现与加载；本功能不会自动执行下载包中的脚本。

## 在 WebUI 中使用

1. 从设置或项目的 Skills 面板选择 **添加 Skill → 从链接安装**。
2. 输入 GitHub 仓库 / 子目录链接，或 ModelScope Skill / 合集页面链接。选择安装位置，勾选所需 Skill；已安装或同名冲突的候选不能在此覆盖。
3. 如静态检查发现风险，展开结果并确认后再安装。
4. 通过 **检查更新** 或 **待更新** 筛选找到更新。详情中逐文件预览，确认后替换。
5. 需要撤回时，在详情的更多菜单中选择 **恢复旧版**，预览后确认。

本地文件与安装基线不一致时，界面显示 **本地有修改**。更新与恢复都会先保留当前实际文件，再替换；恢复只保留最近一次备份，不提供多级历史。没有内容变化的更新不会消耗备份。

本地导入的托管 Skill 可以 **关联来源**：内容完全一致时只补来源记录；不一致时不推断原始版本，必须确认备份替换。标准目录和显式外部路径继续按原有方式发现，不在原位置自动升级。

合集会展开为独立的 Skill 候选，可多选安装。无法读取的条目单独显示错误，不影响其他条目；同名条目需择一安装，“全选”只勾选没有歧义的条目。安装后各自检查更新、升级和恢复；合集新增或移除成员不会自动改变已安装内容。

## 来源与版本

支持 GitHub 公共仓库 / 子目录、ModelScope Skills 条目与 `/collections/owner/name` 合集链接。GitHub 分支名可包含 `/`；系统查询真实 refs 解析。分支跟踪最新提交，tag 或 commit 链接固定版本。GitHub 匿名 API 限流时会尝试公开 Git 查询，因此回退路径需要系统中可用的 `git`。

ModelScope 记录 Skill 仓库的 commit，并按该 commit 下载。也支持 `@owner/name` 和 `modelscope://owner/name`；后者可指定 `@revision#subdir`。需要认证时，后端读取 `MODELSCOPE_API_KEY` 环境变量，凭据不会进入来源记录。

ModelScope 镜像条目的 ID 通常为 `@owner/name`，自行上传的条目使用 `owner/name`。安装时解析并保存真实 `registry_id`，后续检查和下载始终使用同一条目；旧安装记录继续按原来的镜像身份读取。初次解析允许补全链接中的 `@` 差异，已安装来源失效时不会悄悄切换到另一个条目。已实测使用令牌安装和更新自己创建的私有条目。

提交变化只表示需要进一步检查。是否“待更新”取决于该 Skill 所有受管理文件的内容，包括脚本、资源、二进制文件及可执行权限；同仓库其他 Skill 的变化不会误报。内部内容指纹用于比较，不作为面向用户的版本号。

默认在应用打开、进入项目或重新可见时检查全局与当前项目，成功结果缓存 24 小时。自动检查可在 Skills 面板的更多菜单关闭，手动检查仍可用。检查失败保留既有文件与上次结果。服务关闭时不运行定时任务。

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
