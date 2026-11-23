# CodeGenesis

CodeGenesis（代码创世纪）将自然语言需求转成软件项目，通过多个阶段组织需求、设计、依赖、编码和验证。它是MS-Agent上的领域工作流，不是另一个通用对话入口。生成结果仍需测试和人工审查。

## 两种流程

```{mermaid}
flowchart TD
 A[用户故事] --> B[架构设计]
 B --> C[文件设计]
 C --> D[依赖排序]
 D --> E[环境安装]
 E --> F[编码]
 F --> G[优化与验证]
```

标准流程7阶段，适合需要显式设计和中间产物的项目；简化流程为“编排器→安装→编码→优化”4阶段，适合原型。两者都会产生设计与代码文件，不保证一次生成即可上线。

拓扑排序帮助按依赖组织文件，LSP和运行反馈辅助修复。目录LSP调用当前只做索引，不能把空诊断当作全项目通过；最终需运行项目自己的编译、类型检查和测试。

## 准备环境

完成[源码安装](../get-started/quick-start.md)，在仓库根目录安装代码相关依赖：

```bash
pip install -e '.[code]'
npm --version
```

配置各节点 `llm` 中实际可用的模型和端点。项目YAML主要使用OpenAI兼容服务，Key可由 `OPENAI_API_KEY` 提供；不要只改主节点而遗漏后续节点。

若保留默认沙箱配置，需要Docker和对应镜像：

```bash
bash projects/code_genesis/tools/build_sandbox_image.sh
```

这会构建镜像，先检查脚本及Docker环境。选择本地执行会改变隔离边界，见[执行环境](../core/execution-environments.md)。

## 运行与产物

```bash
ms-agent run --config projects/code_genesis/workflow.yaml \
  --query '创建一个简单的待办事项网页，先给出设计再实现' \
  --output_dir ./codegen-output --trust_remote_code true
```

简化流程将config改为 `projects/code_genesis/simple_workflow.yaml`。该项目包含自定义Python节点，所以需要显式信任代码。示例固定输出目录，避免与其他工作混淆；项目现有YAML也有 `./output` 默认值，不等于基础SDK默认目录。

检查生成的设计、文件清单、代码和验证结果，再决定是否继续优化或部署。重跑前保留产物并核对缓存配置，不盲目覆盖已有项目。

## 文件编辑与部署边界

当前 `file_system.edit_file` 使用 `old_string/new_string` 精确替换。旧配置处理器仍可能读取 `tools.file_system.edit_file_config`决定开放编辑工具，但不意味着配置 `diff_model` 就启用Morph服务。

EdgeOne部署通过配置的MCP工具实现，需要单独凭据和授权；首次示例不自动部署。部署前检查生成内容及外部公开范围。

更多项目设计、样例和配置见[项目目录](https://github.com/modelscope/ms-agent/tree/main/projects/code_genesis)。相关模块：[工作流](../core/workflows.md)、[工具](../core/tools.md)。
