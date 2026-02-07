---
slug: video-generation
title: 奇点放映室
description: Ms-Agent 奇点放映室项目：基于大模型的短视频生成器
---
# 奇点放映室 (Singularity Cinema)

---
## 效果展示

[![Video Preview](../../../projects/singularity_cinema/show_case/deploy_llm.png)](http://modelscope.oss-cn-beijing.aliyuncs.com/ms-agent/show_case/video/deploy_llm_claude_sonnet_4_5_mllm_gemini_3_pro_image_gen_gemini_3_pro_image.mp4)
[![Video Preview](../../../projects/singularity_cinema/show_case/silu.png)](http://modelscope.oss-cn-beijing.aliyuncs.com/ms-agent/show_case/video/silu_claude_sonnet_4_5_mllm_gemini_3_pro_image_gen_gemini_3_pro_image.mp4)
[![Video Preview](../../../projects/singularity_cinema/show_case/deploy_llm_en.png)](http://modelscope.oss-cn-beijing.aliyuncs.com/ms-agent/show_case/video/en_deploy_llm_claude_sonnet_4_5_mllm_gemini_3_pro_image_gen_gemini_3_pro_image.mp4)
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

### 4）运行命令示例

在使用默认 YAML 的基础上，通过命令行覆盖 LLM / MLLM / 文生图 / 文生视频等关键配置。

以下为生成本页视频预览使用的两个示例
- 运行前请把query中的{path_to_ms-agent}替换成本地参考文件路径
- 将下述api_key替换成真实api-key

```bash
# 英文版即把query内容替换成"Convert /home/user/workspace/ms-agent/projects/singularity_cinema/test_files/J.部署.md
# into a short video in a blue-themed style, making sure to use the important images from the document.
# The short video must be in English."
ms-agent run --project singularity_cinema \
  --query "把/{path_to_ms-agent}/projects/singularity_cinema/test_files/J.部署.md转为短视频，蓝色风格，注意使用其中重要的图片" \
  --trust_remote_code true \
  --openai_base_url https://api.anthropic.com/v1/ \
  --llm.model claude-sonnet-4-5 \
  --openai_api_key {your_api_key_of_anthropic} \
  --mllm_openai_base_url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --mllm_openai_api_key {your_api_key_of_gemini} \
  --mllm_model gemini-3-pro-preview \
  --image_generator.api_key {your_api_key_of_gemini} \
  --image_generator.type google \
  --image_generator.model gemini-3-pro-image-preview
```

```bash
ms-agent run --project singularity_cinema \
  --query "请以介绍丝绸之路为主题创作短视频，视频风格统一" \
  --trust_remote_code true \
  --openai_base_url https://api.anthropic.com/v1/ \
  --llm.model claude-sonnet-4-5 \
  --openai_api_key {your_api_key_of_anthropic} \
  --mllm_openai_base_url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --mllm_openai_api_key {your_api_key_of_gemini} \
  --mllm_model gemini-3-pro-preview \
  --image_generator.api_key {your_api_key_of_gemini} \
  --image_generator.type google \
  --image_generator.model gemini-3-pro-image-preview
```

---

### 5）输出与失败重试

- **预计耗时**：全流程运行约 **20 分钟**（与机器性能、模型调用速度有关）。
- **输出位置**：视频与中间产物默认生成在**命令执行目录**下的 `output_video/`（可通过参数 `--output_dir` 修改）。
  - 最终视频文件：`output_video/final_video.mp4`
- **失败重试 / 断点续跑**：若运行失败（如超时、中断、文件缺失等），可直接**重新执行同一命令**。系统会读取 `output_video/` 中已生成的中间结果，并从断点继续。
  - **完全重新生成**：删除或重命名 `output_video/` 目录后再运行。
  - **只重做某个分镜/某一步**：删除你希望重生成的对应文件，以及其后续依赖生成的文件（例如删除某个分镜的渲染结果后，再运行会只重跑该分镜渲染效果）。
    - 常见做法：删除目标分镜相关文件 + 最后的 `final_video.mp4`，即可触发仅重生成必要部分。

---

## 运行流程与效果调试

当某一步效果不满意时，你可以通过**删除该步骤的输出文件**（以及所有依赖它的后续文件）来触发重新生成。
完整流程与对应代码入口见：`projects/singularity_cinema/workflow.yaml`。下面按顺序说明各步骤的输入、输出与作用范围（均默认在 `output_video/` 下）。

1. **生成基础台本**
   - 输入：用户需求（可能包含用户指定的文件）
   - 输出：
     - `script.txt`：台本正文
     - `topic.txt`：原始需求/主题
     - `title.txt`：短视频标题
   - 代码：`generate_script/agent.py`

2. **台本切分与分镜设计**
   - 输入：`topic.txt`、`script.txt`
   - 输出：`segments.txt`（分镜列表：每个分镜包含旁白、背景图需求、前景动画需求等）
   - 代码：`segment/agent.py`

3. **生成分镜配音（音频）**
   - 输入：`segments.txt`
   - 输出：
     - `audio/segment_N.mp3`：第 N 个分镜的配音（N 从 1 开始）
     - `audio_info.txt`：音频时长等信息（用于后续对齐动画）
   - 代码：`generate_audio/agent.py`
   - 作用范围：默认每个分镜都有配音
     - 例外：当 `use_text2video=true` 且 `use_video_soundtrack=true`，且该分镜在台本设计中为**文生视频**时，将使用视频原声，不再额外使用配音。

4. **生成文生图提示词（Prompt）**
   - 输入：`segments.txt`
   - 输出：
     - `illustration_prompts/segment_N.txt`：第 N 个分镜的背景图提示词
     - 若该分镜需要前景图：`illustration_prompts/segment_N_foreground_K.txt`（第 N 个分镜的第 K 张前景图提示词）
   - 代码：`generate_illustration_prompts/agent.py`
   - 作用范围：描述每个分镜所需图像内容

5. **文生图生成图片**
   - 输入：`illustration_prompts/segment_N.txt` 等提示词文件
   - 输出：`images/illustration_N.png`（以及可能的前景图）
   - 代码：`generate_images/agent.py`
   - 作用范围：各分镜背景图/前景图素材

6. **根据配音时长生成 Remotion 动画代码**
   - 输入：`segments.txt`、`audio_info.txt`
   - 输出：`remotion_code/SegmentN.tsx`（每个分镜一份）
   - 代码：`generate_animation/agent.py`
   - 作用范围：每个分镜的动画实现代码（时长与音频对齐）

7. **渲染 Remotion 并自动修复代码（如有）**
   - 输入：`remotion_code/SegmentN.tsx`
   - 输出：
     - 更新后的 `remotion_code/SegmentN.tsx`
     - 渲染结果：`remotion_render/scene_N/SceneN.mov`
   - 代码：`render_animation/agent.py`

8. **生成统一背景图（标题与口号）**
   - 输入：`title.txt`
   - 输出：`background.jpg`
   - 代码：`create_background/agent.py`
   - 作用范围：视频左上角标题/背景元素（所有分镜共用）

9. **合成最终视频**
   - 输入：上述所有产物（音频、渲染视频、背景图等）
   - 输出：`final_video.mp4`
   - 说明：该阶段可能出现**较长时间无日志**，属于正常现象；通常不消耗 token。


### 示例：只重做第 1 个分镜的动画效果

如果你对第 1 个分镜动画不满意，可在 `output_video/` 中删除以下文件后重新运行命令：

- `remotion_code/Segment1.tsx`（第 1 镜动画代码）
- `remotion_render/scene_1/Scene1.mov`（由该代码渲染出的结果）
- `final_video.mp4`（最终合成依赖渲染结果，需要重新合成）

重新执行后，系统会仅重跑与这些文件相关的步骤，并复用其它未删除的中间产物。

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
