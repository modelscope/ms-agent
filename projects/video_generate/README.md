# Video Generate

一个“AI 科普短视频”工作流。支持全自动与人工协同两种模式，产生脚本、语音、插画/动画、字幕，并合成为成片。

## 快速检查（必读）

在首次运行前，建议完成以下检查：

1) 运行环境
- Windows / Python 3.10+（推荐）
- 已安装 FFmpeg，并添加到 PATH（ffmpeg -version 可执行）
- Manim 可用（manim -h 可执行）

2) Python 依赖（若未安装）
- 依赖在仓库 requirements 下，或按需安装：moviepy、Pillow、edge-tts、matplotlib 等

3) 资源文件（已随仓库提供）
- 自定义字体与背景音乐：`projects/video_generate/core/asset/`
	- `bg_audio.mp3`
	- `字小魂扶摇手书(商用需授权).ttf`

4) 可选的 API Key（全自动模式常用）
- MODELSCOPE_API_KEY：用于 ModelScope 模型调用

提示：未设置 Key 也可运行“只合成/人工模式”，但全自动模式可能因缺少 LLM 能力失败。

## 运行方式一：全自动模式（auto）

按主题从零到一自动生成并合成视频：

```powershell
# 可选：设置 API Key
$env:MODELSCOPE_API_KEY="你的ModelScopeKey"

# 运行三步工作流（脚本 → 素材 → 合成）
ms-agent run --config "ms-agent/projects/video_generate/workflow.yaml" --query "主题" --animation_mode auto --trust_remote_code true
```

输出将位于 `ms-agent/projects/video_generate/output/<主题>/`。

## 运行方式二：人工模式（human）

适合需要人工把控动画的流程：自动产出“脚本/语音/插画/字幕/占位前景”，然后在“人工工作室”内逐段制作/审批前景动画，最终一键完整合成。

1) 先生成素材（不自动渲染 Manim）
```powershell
ms-agent run --config "ms-agent/projects/video_generate/workflow.yaml" --query "主题" --animation_mode human --trust_remote_code true
```

2) 打开人工工作室（指向上一步生成的主题目录）
```powershell
# 确保将 ms-agent 包目录加入 PYTHONPATH
$env:PYTHONPATH="项目本地目录\ms-agent"

# 以模块方式启动交互式工作室
python -m projects.video_generate.core.human_animation_studio "项目本地目录\ms-agent\projects\video_generate\output\主题"
```

在工作室中：
- 1 查看待制作任务 → 2 开始制作动画 → 生成/改进 Manim 代码 → 创建预览 → 批准动画
- 当所有片段完成后，系统会自动合并前景并执行“完整合成（背景+字幕+音频+前景+音乐）”生成成片

## 运行方式三：只合成（已有素材）

如果目录中已经有 `asset_info.json`（或你只想重新合成）：

```powershell
ms-agent run --config "ms-agent/projects/video_generate/workflow_from_assets.yaml" `
	--query "项目本地目录\ms-agent\projects\video_generate\output\<主题>\asset_info.json" `
	--animation_mode human `
	--trust_remote_code true
```

该流程只执行合成，不会重新生成脚本/插画/动画。若存在已审批的透明前景（finals/scene_*_final.mov），将优先使用。

## 目录说明
- `video_agent.py`：三步逻辑的 Agent 封装
- `workflow.yaml`：三步编排；`workflow_from_assets.yaml`：只合成编排
- `core/workflow.py`：主流程；`core/human_animation_studio.py`：人工工作室
- `core/asset/`：字体与背景音乐
- `output/`：运行产物
- `scripts/compose_from_asset_info.py`：从现有 `asset_info.json` 直接合成的辅助脚本

## 常见问题
- 退出码 1：
	- 检查是否缺少 MODELSCOPE_API_KEY（全自动模式常见）
	- 检查 ffmpeg / manim 是否可执行（PATH）
	- 查看终端最后 80 行日志定位具体异常
- 字体/背景不一致：
	- 背景由 `create_manual_background` 生成，字体/音乐来自 `core/asset/`；确保该目录可读
- TTS/事件循环冲突：
	- 已内置 loop-safe 处理；若仍报错，重试并贴出日志尾部

## 许可证与注意
- 自定义字体文件标注为“商用需授权”，请在合规授权范围内使用
- 背景音乐仅作示例，商业使用请更换或确保版权无虞
