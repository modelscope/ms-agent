<div align="center">
  <img src="https://github.com/user-attachments/assets/3af76dcd-b229-4597-835f-51617371ebad" alt="Doc Research Logo" width="350" height="350">
</div>


<div class="main-header">
    <h1>🔬 Doc Research - 文档深度研究</h1>
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

## 功能特性

- 🔍 **文档深度研究**：支持文档的深度分析和总结
- 📝 **多种输入类型**：支持多文件上传和URLs输入
- 📊 **多模态报告**：支持Markdown格式的图文报告输出
- ⚙️ **灵活部署**：支持本地运行和魔搭创空间运行模式


<br>

## 演示

### ModelScope创空间
参考链接： [DocResearchStudio](https://modelscope.cn/studios/ms-agent/DocResearch)



### 本地运行Gradio应用

<div align="center">
  <img src="https://github.com/user-attachments/assets/4c1cea67-bef1-4dc1-86f1-8ad299d3b656" alt="本地运行" width="750">
  <p><em>本地运行的Gradio界面展示</em></p>
</div>


<br>

## 安装和运行

### 1. 安装依赖
```bash
conda create -n doc_research python=3.11
conda activate doc_research

# 版本要求：ms-agent>=1.1.0
pip install ms-agent[research]
```

### 2. 配置环境变量
```bash
export OPENAI_API_KEY=sk-xxx        # 替换为您的API密钥
export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export OPENAI_MODEL_ID=qwen-plus-2025-07-14

# 对于阿里云百炼用户，可参考： `https://bailian.console.aliyun.com`
```

### 3. 运行应用

快速启动：
```bash
ms-agent app --doc_research
```

带参数启动：
```bash

ms-agent app --doc_research \
    --server_name 0.0.0.0 \
    --server_port 7860 \
    --share
```
参数说明：
> `server_name`: (str), gradio server name, default: `0.0.0.0`  <br>
> `server_port`: (int), gradio server port, default: `7860`  <br>
> `share`: (store_true action), whether to share the app publicly. <br>


<br>

## 使用说明

1. **用户提示**：在文本框中输入您的研究目标或问题
2. **文件上传**：选择需要分析的文件（支持多选）
3. **URLs输入**：输入相关的网页链接，每行一个URL
4. **开始研究**：点击运行按钮开始执行工作流
5. **查看结果**：在右侧区域查看执行结果和研究报告（可全屏）


<br>

## 工作目录结构

每次运行都会在 `temp_workspace` 目录下创建新的工作目录：
```
temp_workspace/user_xxx_1753706367955/
├── task_20250728_203927_cc449ba9/
└── task_20231201_143156_e5f6g7h8/
    ├── resources/
    └── report.md
```

<br>

## 案例

**1. 单文档研究报告**

* User Prompt: `深入分析和总结下列文档`  (默认) <br>
* URLs Input:  `https://modelscope.cn/models/ms-agent/ms_agent_resources/resolve/master/numina_dataset.pdf` <br>

* 研究报告：

<https://github.com/user-attachments/assets/d6af658c-d67d-499d-9241-bfeb43496e4a>

<br>

**2. 多文档研究报告**

* User Prompt: `Qwen3跟Qwen2.5对比，有哪些优化？` <br>
* URLs Input:  (分别输入Qwen3和Qwen2.5的技术报告链接)
```
https://arxiv.org/abs/2505.09388
https://arxiv.org/abs/2412.15115
```

* 研究报告：

<img src="https://github.com/user-attachments/assets/71de24a5-34fa-47c2-8600-c6f99e4501b3"
     width="750"
     alt="Image"
     style="height: auto;"
/>

<https://github.com/user-attachments/assets/bba1bebd-20db-4297-864b-32ea5bb06a3c>

<br>


## 并发控制说明

### 并发限制
- 系统默认支持最大10个用户同时执行研究任务
- 可通过环境变量 `GRADIO_DEFAULT_CONCURRENCY_LIMIT` 调整并发数
- 超出并发限制的用户会收到系统繁忙提示

### 任务管理
- 任务超时时间默认为20分钟，可通过环境变量 `TASK_TIMEOUT` 调整
- 超时任务会被自动清理，释放系统资源

### 状态监控
- 实时显示系统并发状态：活跃任务数/最大并发数
- 显示用户任务状态：运行中、已完成、失败等
- 提供系统状态刷新功能

### 用户隔离
- 每个用户拥有独立的工作目录和会话数据
- 本地模式下使用时间戳区分不同会话
- 远程模式下基于用户ID进行隔离


<br>

## 注意事项

- 确保有足够的磁盘空间用于临时文件存储
- 定期清理工作空间以释放存储空间
- 确保网络连接正常以访问外部URLs
- 在高并发场景下，建议适当增加服务器资源配置
- 长时间运行的任务可能会被超时机制清理
