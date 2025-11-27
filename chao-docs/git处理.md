方案一：个人 WIP 分支 + Squash 合并（最推荐，符合标准流）

这是最标准的 Git 协作模式。你不直接在团队的 dev 分支上提交，而是建立一个属于你的“个人临时分支”。
核心思路： 在你自己的分支上“脏”提交，合并回团队分支时“洗”干净。

1. 创建个人同步分支

在你的设备上，基于当前的开发分支切出一个属于你的分支，比如叫 feat/docs-wip (Work In Progress)：
Bash
git checkout -b feat/docs-wip

2. 随意提交与同步

你可以在这还是分支上通过 git push 和 git pull 在两台设备间随意同步。

- 设备 A: 写了一半文档 -> git commit -m "sync: A 机进度" -> git push
- 设备 B: git pull -> 继续写 -> git commit -m "sync: B 机进度" -> git push
  此时，只有你的 feat/docs-wip 分支是乱的，团队的主分支依然干净。

3. 关键步骤：Squash 合并（洗白）

当你完成了某个阶段的工作，准备把代码合入团队的 dev 分支时，不要直接 merge，而是使用 Squash（压缩）。
方法 A：使用命令行 切换回团队分支，使用 --squash 参数：
Bash

# 切换回团队开发分支

git checkout dev

# 把你的脏分支压缩成一个更改

git merge --squash feat/docs-wip

# 此时所有改动都在暂存区，需要手动提交一次，这一条就是展示给团队看的完美 Commit

git commit -m "Docs: 更新了项目开发文档和相关说明"
方法 B：使用 GitHub/GitLab 的 PR/MR 如果你通过 Pull Request 提交给团队：

1. 推送你的 feat/docs-wip 到远程。
2. 发起 PR 到 dev。
3. 在合并按钮旁边，选择 "Squash and merge"。这样最后合入的代码只有一条干干净净的记录。
