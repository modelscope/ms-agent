# MS-Agent 演示手册更新日志

**更新日期**: 2025-11-25
**基于官方文档版本**: Latest (2025-01-25)
**更新人**: GitHub Copilot

## 主要更新内容

### 1. 快速开始部分

- ✅ 更新了推荐的安装方式（PyPI vs 源码）
- ✅ 添加了针对不同功能的 extras 安装说明 `[research]`, `[code]`
- ✅ 更新了 Python 脚本示例，使用流式输出（`stream=True`）

### 2. Doc Research 部分

- ✅ 补充了完整的核心特性列表
- ✅ **重要更新**：配置使用 ModelScope 免费 API 而非 OpenAI
  - 新增 API Key 获取链接：https://modelscope.cn/my/myaccesstoken
  - 修正 base_url：`https://api-inference.modelscope.cn/v1/`
  - 推荐模型：`Qwen/Qwen3-235B-A22B-Instruct-2507`
- ✅ 添加了自定义参数启动示例（`--server_name`, `--server_port`, `--share`）
- ✅ 补充了工作目录结构说明
- ✅ 添加了多文档对比分析的演示案例

### 3. Deep Research 部分

- ✅ 补充了基础版本和扩展版本的详细特性说明
- ✅ **修复配置说明**：
  - 明确默认使用免费的 arXiv search（无需 API Key）
  - 可选切换到 Exa 或 SerpApi（需要注册获取 API Key）
  - 扩展版本需配置 OpenAI 兼容端点用于查询改写
- ✅ 提供了完整的基础版本和扩展版本 Python 代码示例
- ✅ 使用 ModelScope API 替代 OpenAI API
- ✅ 添加了 Ray 加速的配置说明（`use_ray=True`）
- ✅ 展示了扩展版本的递归搜索流程说明

### 4. Code Scratch 部分（**重点修复**）

- ✅ **关键修复**：明确 Node.js 和 npm 的必要性
  - 未安装 Node.js 会导致编译失败和无限循环
  - 添加了详细的 Node.js 安装指南（Mac/Linux）
  - 添加了验证命令：`npm --version`
- ✅ **配置修复**：
  - 明确了 Code Scratch 默认使用 DashScope 作为 LLM 后端
  - 配置文件路径：`architecture.yaml`, `coding.yaml`, `refine.yaml`
  - 需要设置环境变量：`OPENAI_API_KEY` 和 `OPENAI_BASE_URL`
- ✅ 添加了 PYTHONPATH 的使用说明（避免导入问题）
- ✅ 补充了各阶段的详细观察重点
- ✅ 添加了人工反馈优化的流程说明
- ✅ **新增常见问题排查**：
  - npm 相关错误或无限循环
  - API Key 错误
  - 生成代码质量不佳

### 5. FAQ 部分

- ✅ 重新组织为分类结构：
  - 安装与环境
  - Doc Research
  - Deep Research
  - Code Scratch
  - ModelScope API
  - 性能优化
- ✅ 添加了 15+ 个常见问题及解决方案
- ✅ 特别强调了 Node.js 安装对 Code Scratch 的重要性
- ✅ 添加了 ModelScope API 免费额度说明

### 6. 新增参考资源部分

- ✅ 添加了官方文档链接
- ✅ 添加了 GitHub 仓库链接
- ✅ 添加了 ModelScope 平台和 API 文档链接
- ✅ 添加了各项目的详细文档链接

## 已修复的配置问题

### Code Scratch 无限循环问题

**根本原因**: 未安装 Node.js 或 npm 不在 PATH 中，导致 `npm install` 和 `npm run build/dev` 失败，Refiner 陷入无限修复循环。

**解决方案**:

1. 安装 Node.js（Mac 使用 `brew install node`）
2. 验证 `npm --version` 有输出
3. 确保 npm 在系统 PATH 中

### API 配置问题

**根本原因**: 官方配置文件使用 DashScope 作为后端，但未明确说明需要配置对应的 API Key。

**解决方案**:

```bash
export OPENAI_API_KEY="sk-xxx"  # DashScope API Key
export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

## 测试验证

已验证的环境：

- ✅ Python 3.10+
- ✅ ms-agent 2.0.0
- ✅ Node.js 11.6.2 / npm 11.6.2
- ✅ Ubuntu 22.04.5 LTS (Dev Container)

已测试的功能：

- ✅ ms-agent 命令行工具安装成功
- ✅ 依赖包正确安装（requests, modelscope, openai, anthropic, pandas 等）
- ✅ Node.js 和 npm 环境配置正确

## 建议

为了获得最佳演示效果，建议：

1. **Doc Research**:

   - 使用 ModelScope 免费 API（无需信用卡）
   - 准备几篇 arXiv 论文链接作为演示材料
   - 演示多文档对比功能（如 Qwen3 vs Qwen2.5）

2. **Deep Research**:

   - 基础版本适合快速演示（几分钟完成）
   - 扩展版本适合展示深度搜索能力
   - 准备科研领域的查询（如 "AI Agent 最新进展"）

3. **Code Scratch**:
   - **务必先安装 Node.js**
   - 准备简单但完整的项目需求（如"贪吃蛇游戏"）
   - 预留时间观察三个阶段的完整流程
   - 准备人工反馈示例（如调整样式、添加功能）

## 相关文档链接

- 官方文档：https://ms-agent.readthedocs.io/zh-cn/latest/
- Code Scratch README：https://github.com/modelscope/ms-agent/blob/main/projects/code_scratch/README.md
- ModelScope API：https://modelscope.cn/docs/model-service/API-Inference/intro
