# ROADMAP

## 中文

本ROADMAP截止到2025年S4完成，即12月31日。

### 功能性

- [x] 支持基础短视频生成pipeline P0
- [x] 支持读取知识类文件并转为短视频 P0
- [x] 支持manim动画 P0
- [x] 支持生图 P0
- [x] 支持前景部分可选文生图 P0
- [x] 支持输入多模态数据 P0
    * [x] 分析多模态数据 P0
    * [x] 直接使用多模态数据（图表、图片等） P0
    * [ ] 支持额外的梗图 P1
- [ ] 默认支持更多的tts语音 P0
- [ ] 支持更多LLM模型，例如Qwen系列、DeepSeek系列等 P0
- [ ] 支持一个segment中多个字幕切换，防止文字超长 P0
- [ ] 支持文生视频 P1
- [ ] 支持更复杂的前景设计和背景特效 P0

### 稳定性

- [x] 增加manim动画的稳定性, 并防止截断 P0
- [ ] 提升生成速度，尤其是缩小video生成的大量时间占用 P0
- [x] 支持利用多模态模型分析视频问题，减少人工反馈成本 P0
- [ ] 支持代码修复的memory管理 P1

### 端到端

- [ ] 支持web-ui生成 P0
- [ ] 创空间和space部署 P0

### Bug修复

- [ ] title和slogan需要始终展示，目前在没有manim动画时看不到

## English

This ROADMAP is to be completed by the end of S4 2025, i.e., December 31st.

### Functionality

- [x] Support the basic pipeline framework P0
- [x] Support read documentation to generate videos P0
- [x] Support manim animation P0
- [x] Support image generation for backgrounds P0
- [x] Support optional text-to-image generation for foreground elements P0
- [x] Support multimodal data input P0
    * [x] Analyze multimodal data P0
    * [x] Directly use multimodal data (charts, images, etc.) P0
    * [ ] Support for additional memes P1
- [ ] Support more TTS voices by default P0
- [ ] Support more LLM models, such as Qwen series, DeepSeek series, etc. P0
- [ ] Support multiple subtitles in one segment P0
- [ ] Support text-to-video generation P1
- [ ] Support more complex foreground design and background effects P0

### Stability

- [x] Increase stability of Manim animations, and preventing being cutting off P0
- [ ] Improve generation speed, especially for the process of video file generation P0
- [x] Support using multimodal models to analyze video issues and reduce manual feedback costs P0
- [ ] Support memory management for code fixes P1

### End-to-End

- [ ] Support web UI generation P0
- [ ] Create space and deploy to Hugging Face Spaces P0

### BugFix

- [ ] title and slogan need to show all the time
