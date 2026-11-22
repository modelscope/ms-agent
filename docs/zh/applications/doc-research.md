# DocResearch

DocResearch从用户提供的文件或URL中提取信息，生成图文研究报告。与开放式网络研究不同，它以已有资料为主要输入，适合论文、演示文稿和文档的综合分析。

## 输入与输出

项目支持PDF、TXT、PPT、DOCX等资料，解析能力取决于安装的依赖及输入质量。报告以Markdown及关联图像为基础，可导出PDF、PPTX、DOCX、HTML。导出链路可能需要额外系统组件，不能仅凭生成Markdown就认定所有格式成功。

```{mermaid}
flowchart TD
 A[文件或URL] --> B[解析与关键信息提取]
 B --> C[组织文本及图像证据]
 C --> D[生成研究报告]
 D --> E[人工核查引用与图表]
 E --> F[按需导出]
```

## 本地启动

完成当前源码安装，在仓库根目录安装研究依赖，并配置OpenAI兼容模型：

```bash
pip install -e '.[research]'
export OPENAI_API_KEY='<your-api-key>'
export OPENAI_BASE_URL='https://api-inference.modelscope.cn/v1'
export OPENAI_MODEL_ID='Qwen/Qwen3-235B-A22B-Instruct-2507'
ms-agent app --app_type doc_research --server_name 127.0.0.1 --server_port 7860
```

这是专用Gradio应用入口，不是 `ms-agent ui`。先查看终端就绪地址，用一个小文本/PDF验证上传、生成和下载。模型可用性与额度按提供方账户实际情况确认，不写成永久免费保证。

## 使用步骤

1. 选择自己有权处理的资料，说明研究问题和报告语言。
2. 检查解析结果和可提取图片；扫描件或复杂布局可能需要不同解析组件。
3. 生成后对照原始资料检查关键事实、图表和引用。
4. 下载或导出报告，保留其引用的资源文件，避免只复制Markdown导致图片丢失。

支持上传到外部平台的功能应单独授权，先审查输出中的个人信息和版权内容；首次使用不建议启用公开分享。

## 继续定制

报告导出使用 `MarkdownConverter` 等工具；使用前检查方法所需输入是报告目录还是文件，以及系统字体/转换器依赖。长期批处理应固定模型、解析参数和输出目录，并保存失败记录。

完整项目说明与演示：[中文README](https://github.com/modelscope/ms-agent/blob/main/projects/doc_research/README_zh.md)。相关模块：[RAG](../core/rag.md)、[检索](../core/retrieval.md)、[模型](../core/models.md)。
