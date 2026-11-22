---
orphan: true
---

# 页面已迁移

<a id="ms-agent-架构总览"></a>
<a id="目录"></a>
<a id="1-ms-agent-是什么"></a>
<a id="2-设计原则与理念"></a>
<a id="3-整体架构分层"></a>
<a id="4-运行时核心llmagent-生命周期"></a>
<a id="5-工具调用与安全双层权限--hooks"></a>
<a id="6-system-prompt-组装"></a>
<a id="7-会话与上下文sessionlog--contextassembler--memory"></a>
<a id="8-配置体系"></a>
<a id="9-核心功能模块设计"></a>
<a id="91-项目--会话--工作空间project"></a>
<a id="92-命令系统command"></a>
<a id="93-skillsskill-configskills_managerpy"></a>
<a id="94-pluginsplugins"></a>
<a id="95-mcp-运行时mcpruntimepy-configmcp_managerpy"></a>
<a id="96-llm-provider-层llm"></a>
<a id="97-个性化personalization"></a>
<a id="98-记忆memory"></a>
<a id="99-协议服务acpa2a"></a>
<a id="910-agent-hubagent_hub"></a>
<a id="911-定时任务cron"></a>
<a id="10-磁盘存储布局"></a>
<a id="-全局-homems_agent或-ms_agent_home"></a>
<a id="-工作--项目目录-output_dir"></a>
<a id="日志默认-console-onlyms_agent_log_file-开启--ms_agentlogs"></a>
<a id="11-扩展与开发指南"></a>
<a id="12-术语表"></a>
<a id="附录-a权限与-shell-安全校验参考"></a>
<a id="a1-safetyconfig安全底线配置"></a>
<a id="a2-shell-路径级校验五种提取策略--36-命令注册表"></a>
<a id="a3-纵深防御"></a>
<a id="a4-权限-yaml-配置示例"></a>
<a id="附录-bhooks-协议与事件参考"></a>
<a id="b1-canonical-事件"></a>
<a id="b2-命令执行器子进程协议command-executor"></a>
<a id="b3-决策映射responseadapter"></a>
<a id="b4-matcher-与配置"></a>
<a id="附录-cmcp-运行时状态机与配置"></a>
<a id="c1-状态与转移"></a>
<a id="c2-失败分类与降级"></a>
<a id="c3-公开-api摘要"></a>
<a id="c4-配置模型"></a>
<a id="附录-d配置字段参考"></a>
<a id="d1-agentyaml-主要字段"></a>
<a id="d2-settingsjson--agent-config-映射"></a>

[打开新版文档](../development/architecture.md)。
