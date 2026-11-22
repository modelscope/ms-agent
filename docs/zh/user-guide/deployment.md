# 部署与数据管理

本地使用先按[快速开始](../get-started/quick-start.md)启动。部署到远程服务器时，还必须处理访问控制、文件权限、进程生命周期和备份。

## 本机监听

```bash
ms-agent ui --host 127.0.0.1 --port 8080 --no-browser
```

端口必须空闲；前端访问端口与内部API端口不能相同。启动器监督前后端，任一进程异常退出会停止另一端。`--skip-install`不代表跳过构建有效性检查；`--reload`不是源码热更新入口。

## 远程访问

当前应用没有内置登录。只有在反向代理认证、TLS和网络策略准备好后，才考虑 `--host 0.0.0.0`。Agent使用服务器上的文件和工具，不是浏览器本地资源；只挂载和授权必要工作目录。

`MS_AGENT_FRONTEND_HOSTED_MODE=1`隐藏不适合远程使用的本地路径控件，但不代替后端访问限制。

## Docker

选择已发布且包含目标功能的镜像标签，在以下命令中替换 `TAG`：

```bash
docker run --rm -p 127.0.0.1:9000:8000 \
  -e MS_AGENT_HOME=/data -v ms-agent-data:/data \
  modelscope-registry.us-west-1.cr.aliyuncs.com/modelscope-repo/ms-agent:TAG
```

访问 `http://127.0.0.1:9000`。数据卷保存应用数据；需要项目文件时另行挂载。容器替换后运行中临时安装的软件不一定保留，应在派生镜像或项目环境中声明依赖。未核验某个镜像标签时不要把源码可用等同于镜像已发布。

## 备份与升级

1. 停止相关任务和服务，确认没有写入正在进行。
2. 备份 `MS_AGENT_HOME`以及实际项目工作目录；敏感配置加密或限制访问。
3. 记录代码/包版本和依赖，更新后先验证一个测试项目。
4. 检查模型选择、历史、文件、技能与MCP，再恢复调度任务。

源码后端环境和前端依赖/构建目录不是会话备份。不要只复制 `webui/frontend/build`就认为业务数据已保存。新终端仍需激活Python与Node环境。

开发热更新、运行镜像和环境变量细节见[WebUI维护指南](https://github.com/modelscope/ms-agent/blob/main/webui/README_ZH.md)，存储职责见[存储布局](../development/storage.md)。
