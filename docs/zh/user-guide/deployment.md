# 部署与数据管理

本地使用先按[快速开始](../get-started/quick-start.md)启动。部署到远程服务器时，还必须处理访问控制、文件权限、进程生命周期和备份。

## 本机监听

```bash
ms-agent ui --host 127.0.0.1 --port 8080 --no-browser
```

端口必须空闲；前端访问端口与内部API端口不能相同。启动器监督前后端，任一进程异常退出会停止另一端。`--skip-install`不代表跳过构建有效性检查；`--reload`不是源码热更新入口。

## 远程访问

WebUI 默认关闭认证，仅供本机使用。开放网络访问前启用下方的内置登录，或使用无法绕过的认证网关，并配置 HTTPS 和网络策略。Agent 使用服务器上的文件和工具，不是浏览器本地资源；只挂载和授权必要工作目录。

### 可选单用户登录

在启动前设置以下变量，也可保存到私有的 `webui/backend/.env`：

```ini
MS_AGENT_WEBUI_AUTH_ENABLED=true
MS_AGENT_WEBUI_USERNAME=admin
MS_AGENT_WEBUI_PASSWORD=请替换为足够长且不重复使用的密码
```

重启后使用配置的账号登录。每个实例只有一个账号，用户名默认 `admin`；开启认证但未配置密码会拒绝启动。登录状态保留 7 天，重启后仍有效。**设置 → 退出登录** 可退出；修改用户名或密码并重启会使旧登录失效。

开启认证后，页面、文件、配置及流式 API 都需要登录。登录 Cookie 使用 HttpOnly、SameSite=Lax，HTTPS 下使用 Secure；写入请求仅接受同源或 `MS_AGENT_CORS_ORIGINS` 明确允许的来源，不允许通配来源。该功能不是多用户权限隔离，服务仍以同一实例访问项目资源。

`MS_AGENT_FRONTEND_HOSTED_MODE=1`隐藏不适合远程使用的本地路径控件，但不代替后端访问限制。

## Docker

选择已发布且包含目标功能的镜像标签，在以下命令中替换 `TAG`：

```bash
docker run --rm -p 127.0.0.1:9000:8000 \
  -e MS_AGENT_HOME=/data -v ms-agent-data:/data \
  modelscope-registry.us-west-1.cr.aliyuncs.com/modelscope-repo/ms-agent:TAG
```

访问 `http://127.0.0.1:9000`。数据卷保存应用数据；需要项目文件时另行挂载。容器替换后运行中临时安装的软件不一定保留，应在派生镜像或项目环境中声明依赖。可用功能取决于所选镜像标签，请核对该标签对应的版本与发布说明；需要较新功能时选择包含相应提交的镜像。

## 备份与升级

1. 停止相关任务和服务，确认没有写入正在进行。
2. 备份 `MS_AGENT_HOME`以及实际项目工作目录；敏感配置加密或限制访问。
3. 记录代码/包版本和依赖，更新后先验证一个测试项目。
4. 检查模型选择、历史、文件、技能与MCP，再恢复调度任务。

源码后端环境和前端依赖/构建目录不是会话备份。不要只复制 `webui/frontend/build`就认为业务数据已保存。新终端仍需激活Python与Node环境。

开发热更新、运行镜像和环境变量细节见[WebUI维护指南](https://github.com/modelscope/ms-agent/blob/main/webui/README_ZH.md)，存储职责见[存储布局](../development/storage.md)。
