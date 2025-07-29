<div align="center">
  <img src="https://github.com/user-attachments/assets/3af76dcd-b229-4597-835f-51617371ebad" alt="Doc Research Logo" width="300" height="300">

  # Doc Research Workflow

  这是一个基于Gradio的文档研究工作流应用，支持文件上传和URL输入的智能研究分析，输出图文并茂的多模态研究报告。
</div>


## 功能特性

- 📝 **用户提示输入**：支持中英文输入研究问题或任务描述
- 📁 **文件上传功能**：支持多文件上传，默认支持PDF格式
- 🔗 **URLs输入功能**：支持多个URL输入，每行一个
- 🚀 **一键运行**：点击按钮即可开始研究工作流
- 📊 **结果显示**：实时显示执行结果和工作目录
- 🗂️ **临时工作目录**：每次运行创建新的工作目录
- 🌐 **多语言支持**：支持中文和英文界面
- 👥 **多用户并发**：支持多用户同时使用，默认最大并发数为8
- 🔒 **用户隔离**：每个用户拥有独立的工作空间和会话数据
- ⏱️ **任务超时控制**：自动清理超时任务，默认超时时间15分钟
- 📈 **实时状态监控**：显示系统并发状态和用户任务状态
- ⚙️ **灵活部署**：支持本地和魔搭创空间运行模式切换


## 演示

### ModelScope创空间
参考链接： [DocResearchStudio](https://modelscope.cn/studios/ms-agent/DocResearch/summary)

### 本地运行Gradio应用

<div align="center">
  <img src="https://github.com/user-attachments/assets/4c1cea67-bef1-4dc1-86f1-8ad299d3b656" alt="本地运行" width="700">
  <p><em>本地运行的Gradio界面展示</em></p>
</div>


## 安装和运行

1. 安装依赖：
```bash
git clone git@github.com:modelscope/ms-agent.git

cd ms-agent/projects/doc_research
pip install -r requirements.txt
```

2. 配置环境变量：
```bash
cp .env.example .env
# 编辑 .env 文件，填入你的API配置
```

3. 运行应用：
```bash
python app.py
```

4. 打开浏览器访问：http://localhost:7860

## 环境变量配置

- `OPENAI_API_KEY`: OpenAI API密钥
- `OPENAI_BASE_URL`: OpenAI API基础URL
- `OPENAI_MODEL_ID`: 使用的模型ID
- `GRADIO_DEFAULT_CONCURRENCY_LIMIT`: Gradio默认并发限制（可选，默认：8）
- `TASK_TIMEOUT`: 任务超时时间，单位秒（可选，默认：1200，即20分钟）
- `LOCAL_MODE`: 本地模式开关（可选，默认：true）

## 使用说明

1. **用户提示**：在文本框中输入您的研究目标或问题
2. **文件上传**：选择需要分析的文件（支持多选）
3. **URLs输入**：输入相关的网页链接，每行一个URL
4. **开始研究**：点击运行按钮开始执行工作流
5. **查看结果**：在右侧区域查看执行结果和工作目录路径

## 工作目录结构

每次运行都会在 `temp_workspace` 目录下创建新的工作目录：
```
temp_workspace/user_xxx_1753706367955/
├── task_20250728_203927_cc449ba9/
└── task_20231201_143156_e5f6g7h8/
    ├── resources/
    └── report.md
```

## 并发控制说明

### 并发限制
- 系统默认支持最大8个用户同时执行研究任务
- 可通过环境变量 `GRADIO_DEFAULT_CONCURRENCY_LIMIT` 调整并发数
- 超出并发限制的用户会收到系统繁忙提示

### 任务管理
- 每个用户同时只能执行一个研究任务
- 任务超时时间默认为20分钟，可通过 `TASK_TIMEOUT` 调整
- 超时任务会被自动清理，释放系统资源

### 状态监控
- 实时显示系统并发状态：活跃任务数/最大并发数
- 显示用户任务状态：运行中、已完成、失败等
- 提供系统状态刷新功能

### 用户隔离
- 每个用户拥有独立的工作目录和会话数据
- 本地模式下使用时间戳区分不同会话
- 远程模式下基于用户ID进行隔离

## 注意事项

- 确保有足够的磁盘空间用于临时文件存储
- 定期清理工作空间以释放存储空间
- 确保网络连接正常以访问外部URLs
- 在高并发场景下，建议适当增加服务器资源配置
- 长时间运行的任务可能会被超时机制清理
