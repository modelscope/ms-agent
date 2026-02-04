# SingularityCinema

一个轻量的短视频生成器：基于大语言模型生成**台本与分镜**，并自动生成**配音 /（可选）字幕 / 图片 /（可选）文生视频**，最终合成短视频。

---
## 效果展示

http://modelscope.oss-cn-beijing.aliyuncs.com/ms-agent/show_case/video/deploy_llm_claude_sonnet_4_5_mllm_gemini_3_pro_image_gen_gemini_3_pro_image.mp4

## 安装

项目需要 Python 和 Node.js 环境。

1. **环境准备**
   - **Python**: 版本需要 >= 3.10。建议使用 [Conda](https://docs.conda.io/projects/conda/en/stable/user-guide/install/index.html) 创建虚拟环境。
   - **Node.js**: 如果你使用默认的 Remotion 引擎生成视频，必须安装 [Node.js](https://nodejs.org/) (建议版本 >= 16)。
   - **FFmpeg**: 安装 [ffmpeg](https://www.ffmpeg.org/download.html#build-windows) 并加入环境变量。


2. **获取代码**
   ```bash
   git clone https://github.com/modelscope/ms-agent.git
   cd ms-agent
   ```

3. **安装依赖**
   ```bash
   pip install .
   cd projects/singularity_cinema
   pip install -r requirements.txt
   ```

---

## 适配性和局限性

SingularityCinema 基于大模型生成台本和分镜，并生成短视频。

### 适配性
- 短视频类型：科普类、经济类（尤其包含报表、公式、原理解释）
- 语言：不限（字幕与配音语种跟随你的 query 和材料）
- 外部材料：支持读取纯文本（不支持多模态材料直接输入）
- 二次开发：运行流程可参考 `projects/singularity_cinema/workflow.yaml`；核心实现位于projects/singularity_cinema文件夹下，
各 step 的 `agent.py`，可二次开发与商用
  - 请注意并遵循你使用的背景音乐、字体等的商用许可

### 局限性
- 不同 LLM / AIGC 模型效果差异较大，建议优先使用已验证组合并自行测试。当前的默认配置可参考`projects/singularity_cinema/agent.yaml`

---

## 运行

### 1）准备API Key
**准备LLM Key**

以gemini为例，你需要先申请或购买gemini模型的使用。运行时参数配置：
```shell
  --llm.openai_base_url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --llm.model gemini-3-pro \
  --llm.openai_api_key {your_api_key_of_openai_base_url} \
```

**准备文生图模型 key**
以魔搭提供的Qwen/Qwen-Image-2512为例。魔搭每日每账号提供少量免费额度，触发高频限流时可直接再次执行同一命令重试，会从失败处重试。
```shell
  --image_generator.api_key {your_modelscope_api_key} \
  --image_generator.type modelscope \
  --image_generator.model Qwen/Qwen-Image-2512 \
```

**准备一个多模态大模型用于质量检测**
以gemini为例，你需要先申请或购买gemini模型的使用。运行时参数配置：
```shell
  --mllm_openai_base_url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --mllm_openai_api_key {your_api_key_of_mllm_openai_base_url} \
  --mllm_model gemini-3-pro \
```

### 2）准备材料（可选）
你可以只用一句话生成视频，例如：
```text
生成一个描述GDP经济知识的短视频，约3分钟左右。
```

也可以引用本地文本材料，例如：
```text
生成一个描述大模型技术的短视频，阅读/home/user/llm.txt获取详细内容
```

---

### 3）配置方式说明

当前的默认配置可参考`projects/singularity_cinema/agent.yaml`，运行时，命令行参数配置会覆盖yaml中的对应默认参数，具体地：

- 如果一个字段名在配置中**命名唯一**，可以直接用同名参数覆盖，例如：
  - `--openai_api_key ...`
- 如果字段名在配置中**不唯一/存在同名字段**（例如多个模块都有 `api_key`），也可以用**多级路径**指定，例如：
  - `--image_generator.api_key ...`
  - `--video_generator.api_key ...`

> 规则直观理解：
> - “唯一字段”可以用 `--field`
> - “嵌套字段/可能冲突字段”用 `--a.b.c`

默认 YAML（示例）中相关结构如下（节选）：
```yaml
llm:
  model: claude-sonnet-4-5-20250929 # LLM 模型名称（如 gemini-3-pro）
  openai_api_key: ""                # 必填：API Key（与 openai_base_url 对应的服务商 Key）
  openai_base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1" # OpenAI 兼容接口 Base URL（不同服务商不同）

mllm:
  mllm_model: gemini-3-pro-preview  # 多模态模型名称（如 gemini-3-pro）
  mllm_openai_api_key: ""           # 必填：多模态模型 API Key
  mllm_openai_base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1" # 多模态模型 OpenAI 兼容 Base URL

image_generator:
  api_key: ""                       # 必填：所选 provider 的 API Key
  type: dashscope                   # 服务商/平台类型：modelscope | dashscope | google
  model: gemini-3-pro-image-preview # 该 type 支持的具体模型 ID/名称（如 Qwen/Qwen-Image-2512）

video_generator:
  api_key: ""                       # 所选 provider 的 API Key
  type: dashscope                   # modelscope | dashscope | google
  model: sora-2-2025-10-06          # 该 type 支持的视频模型 ID/名称


```

---

### 3）运行命令示例

下面示例展示了：在使用默认 YAML 的基础上，通过命令行覆盖 LLM / MLLM / 文生图 / 文生视频等关键配置。

```bash
ms-agent run --project singularity_cinema \
  --query "把/Users/me/workspace/ms-agent/projects/singularity_cinema/test_files/J.部署.md转为短视频，蓝色风格，注意使用其中重要的图片，并包含至少一个分镜的文生视频" \
  --trust_remote_code true \
  --openai_base_url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --llm.model gemini-3-pro \
  --openai_api_key {your_api_key_of_openai_base_url} \
  --mllm_openai_base_url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --mllm_openai_api_key {your_api_key_of_mllm_openai_base_url} \
  --mllm_model gemini-3-pro \
  --image_generator.api_key {your_modelscope_api_key} \
  --image_generator.type modelscope \
  --image_generator.model Qwen/Qwen-Image-2512 \
  --video_generator.api_key {your_modelscope_api_key} \
  --video_generator.type modelscope
```

---

### 4）输出与失败重试

- 运行持续约20min左右。
- 生成视频输出在 命令执行目录/`output_video/`（由配置项 `--output_dir` 控制）final_video.mp4
- 如果运行失败（超时/中断/文件缺失），可直接重新运行命令：系统会读取 `output_video` 中的执行信息从断点继续
  - 若希望完全重新生成：重命名/删除 output_video 目录
  - 删除输入文件可以仅删除某个分镜的部分，这样重新执行也仅执行对应分镜的。

---
## 技术原理流程
1. 根据用户需求生成基本台本
   - 输入：用户需求，可能读取用户指定的文件
   - 输出：台本文件script.txt，原始需求文件topic.txt，短视频名称文件title.txt
2. 根据台本切分分镜设计
   - 输入：topic.txt, script.txt
   - 输出：segments.txt，描述旁白、背景图片生成要求、前景manim动画要求的分镜列表
3. 生成分镜的音频讲解
   - 输入：segments.txt
   - 输出：audio/audio_N.mp3列表，N为segment序号从1开始，以及根目录audio_info.txt，包含audio时长
4. 根据语音时长生成remotion动画代码
   - 输入：segments.txt，audio_info.txt
   - 输出：manim代码文件列表 remotion_code/segment_N.py，N为segment序号从1开始
5. 修复remotion代码
   - 输入：remotion_code/segment_N.py N为segment序号从1开始，code_fix/code_fix_N.txt 预错误文件
   - 输出：更新的remotion_code/segment_N.py文件
6. 渲染remotion代码
   - 输入：remotion_code/segment_N.py
   - 输出：remotion_render/scene_N文件夹列表，如果segments.txt中对某个步骤包含了manim要求，则对应文件夹中会有remotion.mov文件
7. 生成文生图提示词
   - 输入：segments.txt
   - 输出：illustration_prompts/segment_N.txt，N为segment序号从1开始
8. 文生图
   - 输入：illustration_prompts/segment_N.txt列表
   - 输出：images/illustration_N.png列表，N为segment序号从1开始
10. 生成背景，为纯色带有短视频title和slogans的图片
    - 输入：title.txt
    - 输出：background.jpg
11. 拼合整体视频
    - 输入：前序所有的文件信息。这一步会有较长无日志耗时，这一阶段不消耗token。
    - 输出：final_video.mp4
---

## 可调参数（概览）

主要参数在默认 `agent.yaml` 中；推荐做法是：**保留默认 YAML 不改动**，需要改什么就在命令行覆盖什么。

常用项示例：
- LLM/MLLM：`--openai_base_url`、`--openai_api_key`、`--llm.model`、`--mllm_model` 等
- 文生图/文生视频：
  - `--image_generator.type`、`--image_generator.model`、`--image_generator.api_key`
  - `--video_generator.type`、`--video_generator.model`、`--video_generator.api_key`
- 并行度：`--t2i_num_parallel`、`--t2v_num_parallel`、`--llm_num_parallel`
- 视频参数：`--video.fps`、`--video.bitrate` 等
- 开关项：`--use_subtitle`、`--use_text2video`、`--use_doc_image` 等

---
