# 贡献指南

贡献可以是修复错误、增加工具/模型适配、补充测试或改善文档。先明确问题和影响范围，再选择已有扩展接口，避免在不同界面重复实现SDK能力。

## 开发与验证

从源码安装，在隔离环境中运行最近测试。代码规范以仓库 `setup.cfg` 和 pre-commit配置为准，WebUI遵循 `webui/AGENTS.md`。

```bash
pip install -e .
pytest tests/config -q
```

示例命令只代表配置模块测试；修改其他模块应选择对应测试，并覆盖正常完成、异常及取消。可选服务和付费模型测试需明确环境和预算，不使用维护者真实凭据自动运行。

## 文档写作

- 教程给前提、步骤、结果和失败处理；参考页给字段、类型、默认、作用域。
- 所有行为以当前代码为准，区分默认路径、兼容路径与提案。
- `docs/zh`与`docs/en`使用相同小写路径，内容与承诺强度对齐，不机械逐句翻译。
- 内部链接带 `.md`，搬迁旧页保留迁移入口；不要把无正文占位页加入导航。
- Mermaid说明一个机制，检查中英、明暗和窄屏；复杂图应拆分。
- 示例密钥使用占位符，截图使用测试项目，不能带私有数据。

## 构建文档

在仓库根目录、Python 3.12环境执行：

```bash
pip install -r requirements/docs.txt
python -m sphinx -E -a -b html -W --keep-going docs/zh /tmp/ms-agent-docs/zh
python -m sphinx -E -a -b html -W --keep-going docs/en /tmp/ms-agent-docs/en
```

`-E -a`使用全新读取和输出，`-W`将警告作为错误。成功构建不等于页面美观或链接锚点正确，仍要检查首页、教程、参考和图表，并验证复制、导航、语言切换。

## 分发扩展

可用 [Plugins](../core/plugins.md) 分发技能、命令、Hooks和Agent定义。运行自定义Python节点时，使用 `ms-agent run --config ./task --trust_remote_code true`，先审查来源。

CLI以目录形式接收 `--config ./task` 时会读取 `./task/author.txt` 展示贡献者；传入具体YAML文件时不会自动读取其同级的 `author.txt`。该文件只用于展示，不控制执行权限。

## API注释与提交范围

Python使用Google风格docstring，描述参数、返回和重要副作用。不要把测试夹具或内部调试记录当用户文档。架构变更更新对应模块和必要RFC状态。

提交前检查差异、秘密、生成文件和无关改动。完整源码规范见[仓库贡献说明](https://github.com/modelscope/ms-agent/blob/main/CONTRIBUTING.md)，WebUI维护命令见[WebUI README](https://github.com/modelscope/ms-agent/blob/main/webui/README_ZH.md)。
