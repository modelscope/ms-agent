# DocResearch

DocResearch extracts information from supplied files or URLs and produces illustrated reports. Unlike open-ended web research, it starts primarily from existing material: papers, presentations, and documents.

## Inputs and outputs

The project supports formats including PDF, TXT, PPT, and DOCX, subject to parser dependencies and input quality. Reports use Markdown and associated images, with PDF/PPTX/DOCX/HTML export options. Exports may require system components; producing Markdown does not validate every export format.

```{mermaid}
flowchart TD
 A[Files or URLs] --> B[Parse and extract key information]
 B --> C[Organize text and image evidence]
 C --> D[Generate report]
 D --> E[Review citations and figures]
 E --> F[Export as needed]
```

## Run locally

After source installation, install research dependencies from the root and configure an OpenAI-compatible model:

```bash
pip install -e '.[research]'
export OPENAI_API_KEY='<your-api-key>'
export OPENAI_BASE_URL='https://api-inference.modelscope.cn/v1'
export OPENAI_MODEL_ID='Qwen/Qwen3.8-Flash-Next'
ms-agent app --app_type doc_research --server_name 127.0.0.1 --server_port 7860
```

This launches the dedicated Gradio app, not `ms-agent ui`. Follow the ready URL and test uploading, generating, and downloading with a small file. Model access and quotas depend on your account, not a universal free-use guarantee.

## Work through a document

1. Select material you are authorized to process and state the question/language.
2. Inspect extraction and images. Scans or complex layouts may need different parsers.
3. Compare important facts, figures, and citations against originals.
4. Keep associated resources when downloading/exporting; copying Markdown alone may lose images.

Uploading to external platforms requires separate authorization. Review personal information and copyright before sharing; avoid public-sharing options on a first run.

## Customize

Export uses helpers such as `MarkdownConverter`. Check whether each method expects a report directory or file and which fonts/converters it requires. For batch work, fix model/parser settings and output locations, and retain failure records.

See the [project README](https://github.com/modelscope/ms-agent/blob/main/projects/doc_research/README.md) for examples. Related: [RAG](../core/rag.md), [Retrieval](../core/retrieval.md), [Models](../core/models.md).
