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

在启动前设置以下环境变量。源码安装也可从私有的 `webui/backend/.env` 加载；PyPI 安装不会自动读取 `.env` 文件：

```bash
export MS_AGENT_WEBUI_AUTH_ENABLED=true
export MS_AGENT_WEBUI_USERNAME=admin
export MS_AGENT_WEBUI_PASSWORD='请替换为足够长且不重复使用的密码'
```

重启后使用配置的账号登录。每个实例只有一个账号，用户名默认 `admin`；开启认证但未配置密码会拒绝启动。登录状态保留 7 天，重启后仍有效。**设置 → 退出登录** 可退出；修改用户名或密码并重启会使旧登录失效。

开启认证后，页面、文件、配置及流式 API 都需要登录。登录 Cookie 使用 HttpOnly、SameSite=Lax，HTTPS 下使用 Secure；写入请求仅接受同源或 `MS_AGENT_CORS_ORIGINS` 明确允许的来源，不允许通配来源。该功能不是多用户权限隔离，服务仍以同一实例访问项目资源。

`MS_AGENT_FRONTEND_HOSTED_MODE=1`隐藏不适合远程使用的本地路径控件，但不代替后端访问限制。

## Docker

(credential-volumes)=
### 持久化数据与主密钥

选择已发布且包含目标功能的镜像标签，在以下命令中替换 `TAG`：

```bash
docker run --rm -p 127.0.0.1:9000:8000 \
  -e MS_AGENT_HOME=/data -v ms-agent-data:/data \
  -v ms-agent-secrets:/data.secrets \
  modelscope-registry.us-west-1.cr.aliyuncs.com/modelscope-repo/ms-agent:TAG
```

访问 `http://127.0.0.1:9000`。两个卷分别保存应用数据和默认主密钥 `/data.secrets/master.key`；需要项目文件时另行挂载。**使用加密功能时只挂载 `/data`，重建容器会丢失默认钥匙，已有凭据将不可用。** 容器中临时安装的软件也可能不保留，应在派生镜像或项目环境中声明依赖。可用功能取决于镜像标签，请核对对应版本与发布说明。

非 root 部署时，应将 `/data` 和 `/data.secrets` 的挂载目录所有者设置为实际运行用户，并确保该用户可写。镜像构建阶段不设置密钥目录的 `700` 权限；程序首次创建默认主密钥时仍会将该目录设为 `700`，新密钥文件为 `600`，因此仅放宽目录权限不能代替正确设置所有者。

### 使用平台提供的主密钥

如果平台已提供持久化 Fernet 密钥文件，可以替代默认主密钥卷，只读挂载：

```bash
docker run --rm -p 127.0.0.1:9000:8000 \
  -e MS_AGENT_HOME=/data -v ms-agent-data:/data \
  -e MS_AGENT_SECRET_KEY_FILE=/run/secrets/ms-agent-master \
  --mount type=bind,src=/secure/ms-agent-master,dst=/run/secrets/ms-agent-master,readonly \
  modelscope-registry.us-west-1.cr.aliyuncs.com/modelscope-repo/ms-agent:TAG
```

将宿主机路径替换为实际文件，确保运行用户可读。文件必须预先包含有效 Fernet 主密钥；若已有加密数据，应使用对应的原钥匙。不要同时设置 `MS_AGENT_SECRET_KEY`。两种方案都应在容器重建后验证原凭据仍可用；上面的本机监听不代替远程部署的认证与 HTTPS。

## 备份与升级

1. 停止相关任务和服务，确认没有写入正在进行。
2. 备份 `MS_AGENT_HOME`、实际项目工作目录和对应主密钥，分开控制访问。模板分享应清空凭据并排除钥匙，不能直接公开私有备份。
3. 记录代码/包版本和依赖，同步升级共享 home 或项目的 WebUI、TUI、CLI 和 SDK；旧版不能读取新密文。
4. 确保配置可写且主密钥可读或可创建，启动新版完成旧配置迁移。用已有会话验证续聊、压缩与记忆读写，再检查文件、技能和 MCP，最后恢复调度任务。

源码后端环境和前端依赖/构建目录不是会话备份。不要只复制 `webui/frontend/build`就认为业务数据已保存。新终端仍需激活Python与Node环境。

迁移失败时保留的管理页面不代表所有配置都已加密。先排查并完成迁移，再导出或分享；恢复钥匙、重置凭据和回滚的边界见[密钥保存与恢复](credentials.md)。

开发热更新、运行镜像和环境变量细节见[WebUI维护指南](https://github.com/modelscope/ms-agent/blob/main/webui/README_ZH.md)，存储职责见[存储布局](../development/storage.md)。
