# Singularity Cinema

奇点放映室将主题或文本材料组织成台本、分镜、配音、图像/动画和最终视频。适合科普与原理解释类内容；结果仍需检查事实、画面、字幕、声音及素材授权。

## 从材料到视频

```{mermaid}
flowchart TD
 A[台本与素材解析] --> B[分段与配音]
 B --> C[图像与动画]
 C --> D[可选视频片段]
 D --> E[字幕、背景与合成]
```

当前 `workflow.yaml` 的13个节点按顺序分成五个阶段：

| 阶段 | 节点 |
| --- | --- |
| 台本与素材 | 生成台本 → 解析文档图片 |
| 分段与配音 | 分段 → 生成音频 |
| 图像与动画 | 插图提示 → 生成图像 → 生成动画 → 渲染动画 |
| 视频片段 | 视频提示 → 生成视频片段 |
| 合成 | 生成字幕 → 创建背景 → 合成视频 |

某些节点根据开关跳过实际生成，不能把13个节点都理解为每次都会请求付费模型。

## 环境与服务

在源码根目录安装 `pip install -e '.[cinema]'`，准备FFmpeg。使用Remotion还需Node.js和前端渲染依赖；Manim路径有自己的系统依赖。检查实际引擎和安装版本，不将WebUI环境要求等同于全部视频依赖。

分别配置主LLM、质量检查的多模态模型、图像生成服务，以及启用时的视频生成服务。`projects/singularity_cinema/agent.yaml`中的示例模型未必由默认端点提供，运行前逐项替换成账号可用组合。

## 关键开关

| 字段 | 当前项目默认值 | 作用 |
| --- | --- | --- |
| animation_engine | remotion | 动画渲染引擎 |
| use_doc_image | true | 使用资料图片 |
| use_subtitle | false | 字幕生成 |
| use_text2video | false | 文生视频片段 |
| use_video_soundtrack | false | 使用视频配乐 |
| t2i_num_parallel | 5 | 图像生成并发 |
| t2v_num_parallel | 1 | 视频生成并发 |
| video.fps | 24 | 帧率 |

默认值属于项目配置，不是所有工具的全局默认。修改并发前检查服务限流、成本和内存。

## 首次运行

先在项目配置中完成凭据和模型配置，再从仓库根执行：

```bash
ms-agent run --config projects/singularity_cinema/workflow.yaml \
  --query '生成一个介绍雨水循环的简短科普视频' \
  --output_dir ./cinema-output --trust_remote_code true
```

运行自定义节点需要信任代码。先选短小材料，不立即启用所有生成分支。原始文档、图片提取和模型读图是不同路径，不能承诺任意多模态文件都能直接输入。

## 查看与重试

保留台本、分段音频、图像、渲染中间结果及合成视频，按日志打印的路径检查。遇到限流先定位失败节点，核对已有产物和缓存，再决定重试范围，避免重复计费。

字体、背景音乐和图像可能有单独许可；公开发布前人工复核。项目原有[中英文示例和视频展示](https://github.com/modelscope/ms-agent/tree/main/projects/singularity_cinema)继续保留，历史模型组合不等于当前最佳配置。
