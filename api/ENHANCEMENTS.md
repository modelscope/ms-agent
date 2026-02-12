# API功能完善说明

本文档说明了参考 `webui/backend` 功能对 `api` 文件夹进行的完善工作。

## 完善概览

基于 webui/backend 的功能，为 api 文件夹添加了以下增强功能，使其功能更加完整和健壮。

---

## 1. 配置管理增强 (api/config.py)

### 1.1 MCP服务器配置管理

新增MCP (Model Context Protocol) 服务器的完整管理功能：

**新增端点：**
- `GET /api/v1/config/mcp` - 获取MCP服务器配置
- `PUT /api/v1/config/mcp` - 更新MCP服务器配置
- `POST /api/v1/config/mcp/servers` - 添加新的MCP服务器
- `DELETE /api/v1/config/mcp/servers/{server_name}` - 删除指定MCP服务器

**功能特点：**
- 支持stdio和sse两种服务器类型
- 单独的mcp_servers.json文件存储，兼容ms-agent格式
- 支持服务器环境变量配置

### 1.2 EdgeOne Pages配置

新增EdgeOne Pages部署配置管理：

**新增端点：**
- `GET /api/v1/config/edgeone-pages` - 获取EdgeOne Pages配置
- `PUT /api/v1/config/edgeone-pages` - 更新EdgeOne Pages配置

**配置项：**
- `api_token` - API访问令牌
- `project_name` - 项目名称

### 1.3 Deep Research完整配置

完善Deep Research配置结构，支持多角色配置：

**新增端点：**
- `GET /api/v1/config/deep-research` - 获取完整Deep Research配置
- `PUT /api/v1/config/deep-research` - 更新完整Deep Research配置

**配置结构：**
```json
{
  "researcher": {
    "model": "qwen-plus",
    "api_key": "xxx",
    "base_url": "https://api.example.com"
  },
  "searcher": {
    "model": "qwen-plus",
    "api_key": "xxx",
    "base_url": "https://api.example.com"
  },
  "reporter": {
    "model": "qwen-plus",
    "api_key": "xxx",
    "base_url": "https://api.example.com"
  },
  "search": {
    "summarizer_model": "qwen-plus",
    "summarizer_api_key": "xxx",
    "summarizer_base_url": "https://api.example.com"
  }
}
```

### 1.4 可用模型列表

新增端点返回支持的LLM模型列表：

**新增端点：**
- `GET /api/v1/config/models` - 获取可用模型列表

**返回模型：**
- Qwen系列（Qwen3-235B, Qwen2.5-72B, Qwen2.5-32B）
- DeepSeek-V3
- GPT-4o系列
- Claude 3.5 Sonnet

### 1.5 环境变量导出

新增方法用于agent执行时的环境变量配置：

```python
def get_env_vars(self) -> Dict[str, str]
```

自动根据配置导出：
- `MODELSCOPE_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`
- `OPENAI_BASE_URL`
- `EXA_API_KEY` / `SERPAPI_API_KEY`

### 1.6 配置文件分离

- 主配置：`~/.ms-agent/config/settings.json`
- MCP服务器：`~/.ms-agent/config/mcp_servers.json`（兼容ms-agent格式）

---

## 2. 项目管理增强 (api/project.py)

### 2.1 Workflow配置获取

新增获取项目workflow配置的端点：

**新增端点：**
- `GET /api/v1/projects/{project_id}/workflow?session_id={session_id}` - 获取项目workflow配置

**功能特点：**
- 支持standard和simple两种workflow类型
- 根据session的workflow_type自动选择相应的yaml文件
- 对于code_genesis项目，支持workflow切换

**使用场景：**
```
GET /api/v1/projects/code_genesis/workflow?session_id=xxx
```
- 如果session的workflow_type为'simple'，返回simple_workflow.yaml
- 如果为'standard'，返回workflow.yaml

---

## 3. 文件操作功能 (api/files.py - 新建)

完整实现文件操作端点，支持session工作目录和项目输出目录的文件管理。

### 3.1 文件列表

**端点：**
- `GET /api/v1/files/list?root_dir={dir}&session_id={id}` - 列出目录下的文件树

**功能特点：**
- 支持session工作目录和项目目录
- 返回树状结构，包含文件夹和文件
- 自动过滤node_modules、__pycache__等目录
- 文件包含名称、相对路径、大小、修改时间

**响应格式：**
```json
{
  "success": true,
  "data": {
    "tree": {
      "folders": {
        "src": {
          "files": [...],
          "folders": {}
        }
      },
      "files": [
        {
          "name": "config.json",
          "path": "config.json",
          "abs_path": "/full/path/config.json",
          "size": 1024,
          "modified": 1234567890.0
        }
      ]
    },
    "root_dir": "/full/path/to/root"
  }
}
```

### 3.2 文件读取

**端点：**
- `POST /api/v1/files/read` - 读取文件内容

**请求体：**
```json
{
  "path": "src/main.py",
  "session_id": "xxx",  // 可选
  "root_dir": "output"  // 可选
}
```

**功能特点：**
- 支持UTF-8文本文件读取
- 自动识别文件语言类型（python, javascript, typescript等）
- 最大支持1MB文件
- 返回相对路径和绝对路径

**响应格式：**
```json
{
  "success": true,
  "data": {
    "content": "file content here...",
    "path": "src/main.py",
    "abs_path": "/full/path/src/main.py",
    "root_dir": "/full/path/to/root",
    "filename": "main.py",
    "language": "python",
    "size": 1024
  }
}
```

### 3.3 文件流式传输

**端点：**
- `GET /api/v1/files/stream?path={path}&session_id={id}` - 流式传输文件

**功能特点：**
- 用于文件下载或预览
- 自动识别MIME类型
- 支持内联显示（inline disposition）
- 适用于图片、PDF等二进制文件

### 3.4 路径解析

**智能路径解析：**
1. 支持绝对路径
2. 支持相对路径（相对于root_dir或session工作目录）
3. 支持projects/前缀路径（从项目根目录解析）
4. 自动搜索项目output目录

**Session工作目录：**
- 位置：`api/work_dir/{session_id}/`
- 自动创建
- 隔离不同session的文件

---

## 4. 数据模型增强 (api/models.py)

新增以下Pydantic模型：

### 4.1 配置相关模型

```python
class DeepResearchConfig(BaseModel):
    """完整的Deep Research配置"""
    researcher: DeepResearchAgentConfig
    searcher: DeepResearchAgentConfig
    reporter: DeepResearchAgentConfig
    search: DeepResearchSearchConfig

class MCPServerConfig(BaseModel):
    """MCP服务器配置"""
    name: str
    type: str  # 'stdio' or 'sse'
    command: Optional[str]
    args: Optional[List[str]]
    url: Optional[str]
    env: Optional[Dict[str, str]]

class EdgeOnePagesConfig(BaseModel):
    """EdgeOne Pages配置"""
    api_token: Optional[str]
    project_name: Optional[str]
```

### 4.2 文件操作模型

```python
class FileReadRequest(BaseModel):
    """文件读取请求"""
    path: str
    session_id: Optional[str]
    root_dir: Optional[str]
```

---

## 5. 主应用集成 (api/main.py)

**更新内容：**
- 导入并注册files路由
- 更新API端点列表，添加files端点
- 保持与现有路由的一致性

**新增路由：**
```python
app.include_router(files_router)
```

---

## 6. 测试支持 (api/test_new_endpoints.py - 新建)

创建完整的测试脚本，覆盖所有新增功能：

**测试覆盖：**
1. 配置管理
   - 获取所有配置
   - 获取可用模型列表
   - MCP服务器增删改查
   - EdgeOne Pages配置
   - Deep Research配置
   - 配置状态检查

2. 项目管理
   - 列出项目
   - 获取workflow配置

3. 文件操作
   - 列出文件树
   - 读取文件内容
   - 流式传输文件

4. Session管理
   - 创建session
   - 查询session
   - 获取消息
   - 删除session

**运行测试：**
```bash
# 启动API服务器
cd /Users/luyan/workspace/my_repo/modelscope-agent
python -m api.main --port 8000

# 在另一个终端运行测试
python api/test_new_endpoints.py
```

---

## 7. 功能对比总结

| 功能 | webui/backend | api (增强前) | api (增强后) |
|------|--------------|-------------|-------------|
| MCP服务器管理 | ✅ | ❌ | ✅ |
| EdgeOne Pages配置 | ✅ | ❌ | ✅ |
| Deep Research完整配置 | ✅ | 部分 | ✅ |
| 可用模型列表 | ✅ | ❌ | ✅ |
| Workflow配置获取 | ✅ | ❌ | ✅ |
| 文件列表（树状） | ✅ | ❌ | ✅ |
| 文件读取 | ✅ | ❌ | ✅ |
| 文件流式传输 | ✅ | ❌ | ✅ |
| Session工作目录 | ✅ | ❌ | ✅ |
| 环境变量导出 | ✅ | ❌ | ✅ |
| MCP配置文件分离 | ✅ | ❌ | ✅ |

---

## 8. 迁移说明

从webui/backend迁移到api时的注意事项：

### 8.1 配置文件位置
- webui使用：`~/.ms-agent/webui/`
- api使用：`~/.ms-agent/config/`

### 8.2 API路径变化
- webui: `/api/projects` → api: `/api/v1/projects`
- webui: `/api/config` → api: `/api/v1/config`
- webui: `/api/sessions` → api: `/api/v1/sessions`

### 8.3 响应格式标准化
API统一使用APIResponse格式：
```json
{
  "success": true/false,
  "message": "optional message",
  "data": {...},
  "error": "optional error"
}
```

### 8.4 Session工作目录
- webui: `webui/backend/work_dir/{session_id}/`
- api: `api/work_dir/{session_id}/`

---

## 9. 使用示例

### 9.1 配置MCP服务器

```python
import requests

# 添加文件系统MCP服务器
server_config = {
    "name": "filesystem",
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"],
    "env": {"ENV_VAR": "value"}
}

response = requests.post(
    "http://localhost:8000/api/v1/config/mcp/servers",
    json=server_config
)
```

### 9.2 获取项目Workflow

```python
import requests

# 获取code_genesis项目的workflow配置
response = requests.get(
    "http://localhost:8000/api/v1/projects/code_genesis/workflow",
    params={"session_id": "your-session-id"}
)
workflow = response.json()["data"]["workflow"]
```

### 9.3 列出和读取文件

```python
import requests

# 列出session工作目录的文件
response = requests.get(
    "http://localhost:8000/api/v1/files/list",
    params={"session_id": "your-session-id"}
)
files = response.json()["data"]["tree"]["files"]

# 读取文件
file_request = {
    "path": files[0]["path"],
    "session_id": "your-session-id"
}
response = requests.post(
    "http://localhost:8000/api/v1/files/read",
    json=file_request
)
content = response.json()["data"]["content"]
```

---

## 10. 安全注意事项

### 10.1 路径安全
当前实现中的TODO标记需要在生产环境中完善：
- 严格验证文件路径在允许的根目录内
- 防止路径遍历攻击（../ 等）
- 限制可访问的目录范围

### 10.2 文件大小限制
- 文本文件读取限制：1MB
- 建议为流式传输也添加大小限制

### 10.3 敏感信息保护
- API key在响应中自动掩码处理
- 配置文件存储在用户目录
- 建议生产环境使用加密存储

---

## 11. 后续建议

1. **添加权限控制**
   - 用户认证
   - 文件访问权限
   - API访问限流

2. **增强错误处理**
   - 更详细的错误信息
   - 错误码标准化
   - 日志记录

3. **性能优化**
   - 文件列表缓存
   - 大文件分块读取
   - 异步文件操作

4. **功能扩展**
   - 文件上传
   - 文件删除
   - 文件搜索

---

## 12. 联系与贡献

如有问题或建议，请通过以下方式联系：
- 提交Issue
- 发起Pull Request
- 查看文档：api/README.md

---

**版本**: 1.0.0  
**更新日期**: 2026-02-12  
**作者**: MS-Agent Team
