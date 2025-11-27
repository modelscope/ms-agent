# Doc Research 模块深度分析

## 1. 项目概览
**Doc Research** 是一个基于 Gradio 的交互式“论文副驾驶” (Paper Copilot)。它专注于深度文档分析，能够处理用户上传的 PDF/TXT/PPT 等文件或 URL 链接，通过 OCR 和多模态大模型技术，生成包含精美图片和表格的结构化 Markdown 研究报告。

此外，它还支持将报告导出为 PDF/PPTX/DOCX 等格式，或直接一键发布到 ModelScope, HuggingFace, GitHub 等社区。

## 2. 核心架构与工作流

### 架构模式
采用 **Gradio Web UI + 异步工作流 + 资源本地化** 的架构。

### 工作流步骤
1.  **输入处理**: 支持多文件上传和多 URL 输入。系统自动为每个 Session 创建隔离的工作目录 (`temp_workspace/user_{id}/task_{id}`).
2.  **环境检查**: 首次运行时自动下载并解压必要的 OCR 模型 (`EasyOCR` / `craft_mlt_25k`) 到本地缓存。
3.  **信息提取 (Extraction)**:
    *   **解析**: 使用 `docling` 或类似工具解析文档结构。
    *   **OCR**: 使用 `EasyOCR` 识别图片中的文字。
    *   **资源提取**: 将文档中的图片、图表提取并保存到本地 `resources/` 目录，确保报告的可视化丰富度。
4.  **智能总结 (Summarization)**:
    *   调用 LLM (推荐 Qwen 系列) 分析提取的内容。
    *   生成 Markdown 格式的深度报告，并自动插入本地图片的引用路径。
5.  **后处理与展示**:
    *   **渲染**: 在 Web 端将 Markdown 转换为 HTML，并处理图片的 Base64 编码以便在线预览。
    *   **导出**: 提供工具类将 Markdown 转换为 PDF, PPTX, DOCX。
    *   **分享**: 提供接口将报告推送到远程代码托管平台。

## 3. 关键文件与类

| 文件路径 | 类/函数 | 职责 |
| :--- | :--- | :--- |
| `ms_agent/app/doc_research.py` | `ResearchWorkflowApp` | **应用入口**。封装 Gradio 界面定义、用户状态管理 (`UserStatusManager`) 和工作流调用。 |
| `ms_agent/workflow/deep_research/research_workflow.py` | `ResearchWorkflow` | **底层逻辑**。复用了 Deep Research 的标准模式 (`search-then-execute`) 核心逻辑。 |
| `ms_agent/cli/app.py` | `AppCMD` | **CLI 适配**。处理 `ms-agent app` 命令参数并启动 Server。 |
| `ms_agent/utils/markdown_converter.py` | `MarkdownConverter` | **格式转换**。负责将 Markdown 报告导出为 HTML/PDF/DOCX/PPTX。 |
| `ms_agent/utils/push_to_hub.py` | `PushToModelScope`等 | **社区集成**。负责将生成的报告上传到 ModelScope/HuggingFace/GitHub。 |

## 4. 配置与依赖

### 启动命令
```bash
# 启动 Doc Research 应用
ms-agent app --app_type doc_research --server_port 7860
```

### 环境变量配置
该模块主要依赖环境变量进行 LLM 配置 (支持 ModelScope 免费额度):
*   `OPENAI_API_KEY`: API 密钥。
*   `OPENAI_BASE_URL`: 接口地址 (如 `https://api-inference.modelscope.cn/v1/`)。
*   `OPENAI_MODEL_ID`: 模型名称 (如 `Qwen/Qwen3-235B-A22B-Instruct-2507`)。
*   `GRADIO_DEFAULT_CONCURRENCY_LIMIT`: 控制并发任务数 (默认 10)。
*   `LOCAL_MODE`: `true/false` (控制是否开启多用户隔离)。

### 关键依赖
*   **Gradio**: Web 界面框架。
*   **EasyOCR**: 图片文字识别 (运行时自动下载模型)。
*   **ModelScope**: 模型下载和 API 调用。
*   **Pandoc** (可能): 用于某些格式转换。

## 5. 局限性与改进点
*   **状态持久化**: 虽然有 Session 隔离，但重启服务后内存中的用户状态 (`UserStatusManager`) 会丢失，建议接入 Redis。
*   **OCR 性能**: EasyOCR 在无 GPU 环境下较慢，大文件处理耗时较长。
