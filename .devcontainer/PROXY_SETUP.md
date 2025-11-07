# DevContainer 代理配置指南

本指南说明如何在 SEU 团队工作区的 DevContainer 中配置网络代理。

## 项目结构说明

```
team-agent/                          # 团队工作区（外层）
├── .devcontainer/                   # 工作区级 DevContainer 配置 ⭐
│   ├── devcontainer.json            # 主配置文件
│   ├── setup-proxy.sh               # 代理配置脚本
│   └── PROXY_SETUP.md               # 本文档
├── team-seu-ms-agent-private/       # 主项目（内层）
│   └── .devcontainer/               # 项目级配置（用于特定开发）
└── scripts/                         # 团队工具脚本
```

## 快速配置方法

### 1. 在主机设置代理环境变量

```bash
# 基本代理配置
export HTTP_PROXY=http://proxy.company.com:8080
export HTTPS_PROXY=http://proxy.company.com:8080
export NO_PROXY=localhost,127.0.0.1,*.local

# 带认证的代理
export HTTP_PROXY=http://username:password@proxy.company.com:8080
export HTTPS_PROXY=http://username:password@proxy.company.com:8080

# SOCKS 代理
export HTTP_PROXY=socks5://proxy.company.com:1080
export HTTPS_PROXY=socks5://proxy.company.com:1080
```

### 2. 重新构建 DevContainer

在 VS Code 中：
1. 打开 `team-agent` 目录
2. 按 `F1` 打开命令面板
3. 选择 "Dev Containers: Rebuild Container"

## 自动配置功能

DevContainer 会自动检测代理环境变量并配置：

- ✅ **Git 代理** - 自动配置 `git config --global http.proxy`
- ✅ **pip 代理** - 自动配置 `~/.pip/pip.conf`
- ✅ **npm 代理** - 自动配置 `npm config`
- ✅ **Docker 代理** - 自动配置 `~/.docker/config.json`

## 验证代理配置

进入 DevContainer 后，可以验证代理是否正常工作：

```bash
# 检查 Git 代理
git config --global --get http.proxy

# 检查 pip 代理
cat ~/.pip/pip.conf

# 测试网络连接
curl -I https://www.google.com

# 测试 pip 安装
pip search numpy

# 测试 Git 操作
git ls-remote https://github.com/modelscope/ms-agent
```

## 企业网络环境

### 常见企业代理配置

```bash
# 标准企业代理
export HTTP_PROXY=http://proxy.company.com:8080
export HTTPS_PROXY=http://proxy.company.com:8080
export NO_PROXY="localhost,127.0.0.1,*.local,*.company.com,company.local"

# 需要认证的企业代理
export HTTP_PROXY=http://domain\\username:password@proxy.company.com:8080
export HTTPS_PROXY=http://domain\\username:password@proxy.company.com:8080
```

### SSL 证书问题

如果企业使用自签名证书：

```bash
# 临时禁用 SSL 验证（仅开发环境）
export GIT_SSL_NO_VERIFY=1
export NODE_TLS_REJECT_UNAUTHORIZED=0

# 或配置企业 CA 证书
export REQUESTS_CA_BUNDLE=/path/to/company-ca.crt
export NODE_EXTRA_CA_CERTS=/path/to/company-ca.crt
```

## 团队协作建议

### 1. 统一配置文件

团队可以创建 `.env.proxy` 文件（不要提交到 git）：

```bash
# .env.proxy（团队内共享，但不要提交到版本控制）
HTTP_PROXY=http://proxy.company.com:8080
HTTPS_PROXY=http://proxy.company.com:8080
NO_PROXY=localhost,127.0.0.1,*.local,*.company.com
```

使用时：
```bash
source .env.proxy
```

### 2. 开发环境区分

- **工作区 DevContainer**：用于日常开发和团队协作
- **项目 DevContainer**：用于特定项目的特殊配置

### 3. 文档更新

更新团队文档，包含代理配置说明：
```markdown
## 网络要求
- 如需使用代理，请设置 HTTP_PROXY 和 HTTPS_PROXY 环境变量
- 重新构建 DevContainer 以应用代理配置
```

## 故障排除

### 1. 代理不生效

```bash
# 检查环境变量是否正确传递
echo $HTTP_PROXY
echo $HTTPS_PROXY

# 手动重新配置
bash ~/.devcontainer/setup-proxy.sh
```

### 2. SSL 证书错误

```bash
# 对于 pip
pip config set global.trusted-host "pypi.org pypi.python.org files.pythonhosted.org"

# 对于 npm
npm config set strict-ssl false
```

### 3. 连接超时

```bash
# 增加超时时间
git config --global http.lowSpeedTime 999999
pip config set global.timeout 60
```

## 安全注意事项

1. **不要在代码中硬编码代理密码**
2. **使用环境变量传递敏感信息**
3. **`.env.proxy` 文件应加入 `.gitignore`**
4. **定期轮换代理认证信息**

## 联系支持

如遇到代理配置问题，请联系：
- 网络管理员：确认代理地址和端口
- 团队负责人：确认团队配置标准
- DevContainer 维护者：报告配置问题
