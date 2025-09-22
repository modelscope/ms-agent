<div align="center">
    <img src="https://github.com/user-attachments/assets/3af76dcd-b229-4597-835f-51617371ebad" alt="Doc Research Logo" width="350" height="350">
</div>

[中文版](README_zh.md)

<div class="main-header">
  <h1>🔬 Doc Research</h1>
  <p class="description">
      <span style="color: #00ADB5;
                  font-weight: 600;
                  font-size: 1.2rem;
                  font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;">
          Your Daily Paper Copilot - URLs or Files In, Multimodal Report Out
      </span>
  </p>
</div>


<br>

## Features

  - 🔍 **Deep Document Research** - Support deep analysis and summarization of documents
  - 📝 **Multiple Input Types** - Support multi-file uploads and URL inputs, including PDF, TXT, PPT, DOCX, etc.
  - 📊 **Multimodal Reports** - Support text and image reports in Markdown format
  - 🚀 **High Efficiency** - Leverage powerful LLMs for fast and accurate research, leveraging key information extraction techniques to further optimize token usage
  - ⚙️ **Flexible Deployment** - Support local run and [ModelScope Studio](https://modelscope.cn/studios) on both CPU and GPU environments.
  - 💰 **Free Model Inference** - Free LLM API inference calls for ModelScope users, refer to [ModelScope API-Inference](https://modelscope.cn/docs/model-service/API-Inference/intro)
  - 📚 **Export & Upload** - Support exporting research reports to PDF, PPTX, DOCX, HTML formats; support uploading reports to ModelScope, HuggingFace, GitHub


<br>

## Demo

### ModelScope Studio
Reference Link: [DocResearchStudio](https://modelscope.cn/studios/ms-agent/DocResearch)



### Local Gradio Application

<div align="center">
<img src="https://github.com/user-attachments/assets/4c1cea67-bef1-4dc1-86f1-8ad299d3b656" alt="Gradio Local Run" width="750">
<p><em>Gradio Interface Displayed in Local Run</em></p>
</div>


<br>

## Installation and Running

### 1. Install Dependencies
```bash
conda create -n doc_research python=3.11
conda activate doc_research

# Version requirement: ms-agent>=1.1.0
pip install 'ms-agent[research]'
```

### 2. Configure Environment Variables

**Free API Inference Calls** - Every registered ModelScope user receives a set number of free API inference calls daily, refer to [ModelScope API-Inference](https://modelscope.cn/docs/model-service/API-Inference/intro) for details.

```bash
export OPENAI_API_KEY=xxx-xxx
export OPENAI_BASE_URL=https://api-inference.modelscope.cn/v1/
export OPENAI_MODEL_ID=Qwen/Qwen3-235B-A22B-Instruct-2507

```
* `OPENAI_API_KEY`: (str), your API key, replace `xxx-xxx` with your actual key. Alternatively, you can use ModelScope API key, refer to [ModelScopeAccessToken](https://modelscope.cn/my/myaccesstoken) <br>
* `OPENAI_BASE_URL`: (str), the base URL for API requests, `https://api-inference.modelscope.cn/v1/` for ModelScope API-Inference <br>
* `OPENAI_MODEL_ID`: (str), the model ID for inference, `Qwen/Qwen3-235B-A22B-Instruct-2507` can be recommended for document research tasks. <br>


### 3. Run Application

**Quick start:**
```bash
# Use ms-agent CLI to run the app
ms-agent app --doc_research

# Use Python script to run the app
cd ms-agent/app
python doc_research.py
```

**Start with Parameters:**
```bash
ms-agent app --doc_research \
    --server_name 0.0.0.0 \
    --server_port 7860 \
    --share
```
* Parameter Description:
> `server_name`: (str), gradio server name, default: `0.0.0.0`  <br>
> `server_port`: (int), gradio server port, default: `7860`  <br>
> `share`: (store_true action), whether to share the app publicly. <br>

* Notes
> When running locally, the default address is http://0.0.0.0:7860/. If the page can't be accessed, try disabling proxy.


### 4. Report Export
DocResearch supports exporting markdown reports to various formats for easy archiving and sharing:
- PDF
- PPTX
- HTML
- DOCX

**Examples of exporting using Python script:**
```python
from ms_agent.utils.markdown_converter import MarkdownConverter

report_path: str = '/path/to/report_dir'
output_path: str = '/path/to/output_dir'

# Call export functions
MarkdownConverter.markdown_to_html(report_path, output_path + "/html")
MarkdownConverter.markdown_to_docx(report_path, output_path + "/docx")
MarkdownConverter.markdown_to_pptx(report_path, output_path + "/pptx")
MarkdownConverter.markdown_to_pdf(report_path, output_path + "/pdf")
```


### 5. Report Uploading & Sharing
DocResearch supports uploading generated markdown research reports to multiple platforms for easy sharing and collaboration:
- **ModelScope**
- **HuggingFace**
- **GitHub**

**Upload to ModelScope:**
```python
from ms_agent.utils.push_to_hub import PushToModelScope

# Get the ModelScope token： https://modelscope.cn/my/myaccesstoken
push_to_ms = PushToModelScope(token='ms-xxx')

push_to_ms.push(
    repo_id='your-username/your-repo-name',
    folder_path='/path/to/report_dir',
    path_in_repo='report',
    commit_message='Upload research report to ModelScope',
)
```

**Upload to HuggingFace:**
```python
from ms_agent.utils.push_to_hub import PushToHuggingFace

# Get the HuggingFace token： https://huggingface.co/settings/tokens
push_to_hf = PushToHuggingFace(token='hf_xxx')

push_to_hf.push(
    repo_id='your-username/your-repo-name',
    folder_path='/path/to/report_dir',
    path_in_repo='report',
    commit_message='Upload research report to HuggingFace',
)
```

**Upload to GitHub:**
```python
from ms_agent.utils.push_to_hub import PushToGitHub

# Get the GitHub PAT(Personal Access Tokens): https://github.com/settings/tokens
push_to_git = PushToGitHub(
    user_name = 'your-username',
    repo_name = 'your-repo-name',
    token = 'xxx',
    visibility = 'public',  # `public` or `private`
    description = 'A repository for research reports generated by MS-Agent DocResearch',)

push_to_git.push(
    folder_path='/path/to/report_dir',
    path_in_repo='report',
    commit_message='Upload research report to GitHub',
)
```


<br>

## Usage Instructions

1. **User Prompt** - Enter your research objective or question in the text box

2. **File Upload** - Select files for analysis (supports multiple selections)

3. **URLs Input** - Enter relevant web links, one URL per line

4. **Start Research** - Click the run button to start the workflow

5. **Research Report** - View the execution results and research report in the right area (fullscreen available)


### Working Directory Structure

Each run creates a new working directory under `temp_workspace`:
```bash
temp_workspace/user_xxx_1753706367955/
├── task_20250728_203927_cc449ba9/
└── task_20250729_143156_e5f6g7h8/
    ├── resources/
    └── report.md
```


## Cases

**1. Single Document Research Report**

* User Prompt: `Deeply analyze and summarize the following document` (Default) <br>
* URLs Input:  `https://modelscope.cn/models/ms-agent/ms_agent_resources/resolve/master/numina_dataset.pdf` <br>

* Research Report:

<https://github.com/user-attachments/assets/d6af658c-d67d-499d-9241-bfeb43496e4a>

<br>


**2. Multi-document Research Report**

* User Prompt: `Compare Qwen3 and Qwen2.5, what optimizations are there?` <br>
* URLs Input:  (Enter the technical report links for Qwen3 and Qwen2.5 separately)
```text
https://arxiv.org/abs/2505.09388
https://arxiv.org/abs/2412.15115
```

* Research Report:

<img src="https://github.com/user-attachments/assets/71de24a5-34fa-47c2-8600-c6f99e4501b3"
     width="750"
     alt="Image"
     style="height: auto;"
/>

<https://github.com/user-attachments/assets/bba1bebd-20db-4297-864b-32ea5bb06a3c>

<br>



## Concurrency Control

### Concurrency Limit
- Support up to 10 concurrent users executing research tasks by default
- Concurrency limit can be adjusted via environment variable `GRADIO_DEFAULT_CONCURRENCY_LIMIT`
- Users exceeding the concurrency limit will receive a system busy message


### Status Monitoring
- Real-time display of system concurrency status: active tasks / maximum concurrency
- Display user task status: running, completed, failed, etc.
- Provides system status refresh functionality

### User Isolation
- Each user has an independent working directory and session data
- In local mode, different sessions are distinguished by timestamps
- In remote mode, isolation is based on user ID

<br>

## Notes

- Ensure sufficient disk space for temporary file storage
- Regularly clean the workspace to free up storage space
- Ensure normal network connection to access external URLs
- In high concurrency scenarios, it is recommended to appropriately increase server resource configuration

<br>
