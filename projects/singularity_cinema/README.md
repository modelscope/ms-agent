# SingularityCinema

一个轻量优秀的短视频生成器

## 安装

1. 克隆代码
```shell
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
```

2. 安装依赖
```shell
pip install .
cd projects/singularity_cinema
pip install -r requirements.txt
```

安装[ffmpeg](https://www.ffmpeg.org/download.html#build-windows).

在执行上面的安装命令之前，请确保你的Python>=3.10。安装Python可以参考[Conda](https://docs.conda.io/projects/conda/en/stable/user-guide/install/index.html)

## 适配性和局限性

SingularityCinema基于大模型生成台本和分镜，并生成短视频。

### 适配性

- 短视频类型：科普类、经济类，尤其包含报表、公式、原理性解释的短视频
- 语言：不限，字幕和语音语种跟随你的原始query和文档材料
- 读取外部材料：支持纯文本，不支持多模态
- 二次开发：完整代码均在stepN/agent.py中，没有license限制，可自由二次开发和商用
  - 请注意并遵循你使用的背景音乐、字体的商用许可

### 局限性

- LLM测试范围：Claude，其他模型效果未测试
- AIGC模型测试范围：Qwen-Image，其他模型效果未测试

## 运行

1. 准备API Key

### 准备LLM Key

以Claude为例，你需要先申请或购买Claude模型的使用。Claude的Key可以在环境变量中设置：

```shell
OPENAI_API_KEY=xxx-xxx
```

### 准备魔搭文生图Key

目前默认模型是Qwen-Image，魔搭API Key可以在[这里](https://www.modelscope.cn/my/myaccesstoken)申请。之后在环境变量中设置：

```shell
T2I_API_KEY=ms-xxx-xxx
```

### 准备一个多模态大模型用于质量检测

```shell
MANIM_TEST_API_KEY=xxx-xxx
```

2. 准备你的短视频材料

你可以选择使用一句话生成视频，例如：

```text
生成一个描述GDP经济知识的短视频，约3分钟左右。
```

或者使用自己之前采集的文本材料：

```text
生成一个描述大模型技术的短视频，阅读/home/user/llm.txt获取详细内容
```

3. 运行命令

```shell
ms-agent run --config "projects/singularity_cinema" --query "你的自定义主题，见上面描述" --load_cache true --trust_remote_code true
```

4. 运行持续约20min左右。视频生成在output/final_video.mp4。生成完成后你可以查看这个文件，把不满足要求的地方汇总起来，输入命令行input中，工作流会继续改进。如果达到了要求，输入quit或者exit程序会自动退出。

5. 如果运行失败了，比如URL调用超时、文件没有生成等，可以重新执行上面的命令。ms-agent在output/memory文件夹中保存了执行信息，重新运行命令后会从失败的地方继续执行
   * 如果希望重新生成，请将output文件夹重命名或迁移到别处，或者删除对应的memory以及输入文件
   * 删除输入文件可以仅删除某个分镜的部分，这样重新执行也仅执行对应分镜的，这也是最后一步的人工反馈修复的原理

## 技术原理

1. 根据用户需求生成基本台本
    * 输入：用户需求，可能读取用户指定的文件
    * 输出：台本文件script.txt，原始需求文件topic.txt，短视频名称文件title.txt
2. 根据台本切分分镜设计
    * 输入：topic.txt, script.txt
    * 输出：segments.txt，描述旁白、背景图片生成要求、前景manim动画要求的分镜列表
3. 生成分镜的音频讲解
    * 输入：segments.txt
    * 输出：audio/audio_N.mp3列表，N为segment序号从1开始，以及根目录audio_info.txt，包含audio时长
4. 根据语音时长生成manim动画代码
    * 输入：segments.txt，audio_info.txt
    * 输出：manim代码文件列表 manim_code/segment_N.py，N为segment序号从1开始
5. 修复manim代码
    * 输入：manim_code/segment_N.py N为segment序号从1开始，code_fix/code_fix_N.txt 预错误文件
    * 输出：更新的manim_code/segment_N.py文件
6. 渲染manim代码
    * 输入：manim_code/segment_N.py
    * 输出：manim_render/scene_N文件夹列表，如果segments.txt中对某个步骤包含了manim要求，则对应文件夹中会有manim.mov文件
7. 生成文生图提示词
    * 输入：segments.txt
    * 输出：illustration_prompts/segment_N.txt，N为segment序号从1开始
8. 文生图
    * 输入：illustration_prompts/segment_N.txt列表
    * 输出：images/illustration_N.png列表，N为segment序号从1开始
9. 生成字幕
    * 输入：segments.txt
    * 输出：subtitles/bilingual_subtitle_N.png列表，N为segment序号从1开始
10. 生成背景，为纯色带有短视频title和slogans的图片
    * 输入：title.txt
    * 输出：background.jpg
11. 拼合整体视频
    * 输入：前序所有的文件信息
    * 输出：final_video.mp4
12. 人工反馈

## 可调参数

所有的可调参数大部分都在agent.yaml中。在运行前，你可以调节这个文件来进行自定义。

下面列出一些比较重要的参数：

- llm: 该组参数控制大模型的url、apikey等
- generation_config: 该组参数控制大模型生成的参数
- prompt.system: 控制台本生成阶段的system
  - 如果你想修改分镜生成的system，可以修改step2_segment/agent.py的system
- text2image: 文生图模型的参数，包括url、模型id等
  - t2i_transition: 背景图片的效果，默认为ken-burns效果
  - t2i_style: 图片风格，可以设置你期望的文生图风格
- t2i_num_parallel: 文生图调用并行度。默认为1防止被限流
- llm_num_parallel: 大模型调用并行度，默认为10
- video: 视频生成的比特率等参数
- voice/voices: edge_tts的声音设置，如果你有其他声音选项，可以添加到这里
- subtitle_translate: 多语言字幕的语种，如果不设置则不进行翻译
- slogan: 展示在屏幕右侧，一般展示出品人名字和短视频集合
