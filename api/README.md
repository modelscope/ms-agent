# MS-Agent API Server

MS-Agent API Server 提供了完整的 REST API 和 WebSocket 接口，用于管理和执行 MS-Agent 框架的各项功能。

> **最近更新**: 参考 webui/backend 功能增强了 API 服务，新增了 MCP 服务器管理、文件操作、完整 Deep Research 配置等功能。详细说明请查看 [ENHANCEMENTS.md](./ENHANCEMENTS.md)。

## 功能特性

### 核心功能

1. **配置管理** (`/api/v1/config`)
   - LLM 配置管理
   - MCP 服务器配置管理 (新增)
   - 编辑文件配置
   - 搜索 API 密钥管理
   - Deep Research 完整配置 (researcher/searcher/reporter) (增强)
   - EdgeOne Pages 配置 (新增)
   - 可用模型列表查询 (新增)

2. **项目管理** (`/api/v1/projects`)
   - 项目发现和列表
   - 项目详情查询
   - README 文件获取
   - 项目文件访问
   - Workflow 配置获取 (新增)

3. **会话管理** (`/api/v1/sessions`)
   - 创建和管理会话
   - 消息历史记录
   - 会话状态追踪
   - Deep Research 事件管理
   - Session 工作目录管理 (新增)

4. **文件操作** (`/api/v1/files`) (新增)
   - 文件列表查询 (树状结构)
   - 文件内容读取
   - 文件流式传输
   - Session 工作目录支持

5. **Agent 执行** (`/api/v1/agent`)
   - 启动 Agent 执行
   - 停止 Agent 执行
   - 执行状态查询
   - 进度追踪

6. **WebSocket 通信**
   - 实时 Agent 通信 (`/ws/agent/{session_id}`)
   - 聊天功能 (`/ws/chat`)
   - 双向消息传递
   - 流式输出支持

## 安装依赖

```bash
pip install fastapi uvicorn websockets pydantic
```

## 启动服务器

### 方法 1: 使用启动脚本

```bash
python api/run_server.py
```

### 方法 2: 直接运行

```bash
python -m api.main
```

### 方法 3: 使用 uvicorn

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 命令行参数

- `--host`: 绑定的主机地址 (默认: 0.0.0.0)
- `--port`: 绑定的端口 (默认: 8000)
- `--reload`: 启用自动重载 (开发模式)

## API 文档

启动服务器后，可以通过以下地址访问 API 文档:

- **Swagger UI**: http://localhost:8000/api/docs
- **ReDoc**: http://localhost:8000/api/redoc

## API 端点说明

### 配置管理 API

```
GET    /api/v1/config                     # 获取所有配置
GET    /api/v1/config/llm                 # 获取 LLM 配置
POST   /api/v1/config/llm                 # 保存 LLM 配置
GET    /api/v1/config/mcp                 # 获取 MCP 服务器配置
PUT    /api/v1/config/mcp                 # 更新 MCP 服务器配置
POST   /api/v1/config/mcp/servers         # 添加新的 MCP 服务器
DELETE /api/v1/config/mcp/servers/{name} # 删除 MCP 服务器
GET    /api/v1/config/edgeone-pages       # 获取 EdgeOne Pages 配置
PUT    /api/v1/config/edgeone-pages       # 更新 EdgeOne Pages 配置
GET    /api/v1/config/deep-research       # 获取完整 Deep Research 配置
PUT    /api/v1/config/deep-research       # 更新完整 Deep Research 配置
GET    /api/v1/config/models              # 获取可用模型列表
GET    /api/v1/config/search-keys         # 获取搜索密钥
POST   /api/v1/config/search-keys         # 保存搜索密钥
GET    /api/v1/config/status              # 获取配置状态
```

### 项目管理 API

```
GET    /api/v1/projects                        # 列出所有项目
GET    /api/v1/projects/{project_id}           # 获取项目详情
GET    /api/v1/projects/{project_id}/readme    # 获取项目 README
GET    /api/v1/projects/{project_id}/workflow  # 获取项目 workflow 配置
```

### 会话管理 API

```
POST   /api/v1/sessions                   # 创建新会话
GET    /api/v1/sessions                   # 列出所有会话
GET    /api/v1/sessions/{session_id}      # 获取会话详情
PUT    /api/v1/sessions/{session_id}      # 更新会话
DELETE /api/v1/sessions/{session_id}      # 删除会话
GET    /api/v1/sessions/{session_id}/messages  # 获取会话消息
POST   /api/v1/sessions/{session_id}/messages  # 添加消息
GET    /api/v1/sessions/{session_id}/events    # 获取 DR 事件
GET    /api/v1/sessions/{session_id}/progress  # 获取进度事件
```

### 文件操作 API (新增)

```
GET    /api/v1/files/list                 # 列出文件树
POST   /api/v1/files/read                 # 读取文件内容
GET    /api/v1/files/stream               # 流式传输文件
```

### Agent 执行 API

```
POST   /api/v1/agent/run                  # 启动 Agent 执行
POST   /api/v1/agent/stop                 # 停止 Agent 执行
GET    /api/v1/agent/status/{session_id}  # 获取执行状态
```

### WebSocket 端点

```
WS     /ws/agent/{session_id}             # Agent 实时通信
WS     /ws/chat                            # 聊天功能
```

## 配置管理

### 配置优先级

执行Agent/Workflow时,配置按以下优先级合并:

1. **API配置**: 通过 `/api/v1/config/llm` 保存的LLM配置(最高优先级)
2. **项目配置**: 项目的workflow.yaml或agent.yaml中的配置
3. **默认配置**: ms_agent框架的默认配置

API配置会覆盖项目配置中的以下字段:
- `llm.api_key`
- `llm.model`
- `llm.base_url`
- `llm.temperature` (如果启用)
- `llm.max_tokens`

### 工作目录

每个会话都有独立的工作目录:
```
~/.ms-agent/api/work_dir/{session_id}/
```

所有Agent生成的文件都会保存在该目录下。

## WebSocket 消息格式

### 客户端到服务器

**启动Agent执行:**
```json
{
  "type": "start",
  "query": "用户查询内容",
  "project_id": "项目ID(可选,默认为chat)",
  "workflow_type": "standard或simple(可选)"
}
```

**停止执行:**
```json
{
  "type": "stop"
}
```

**心跳检测:**
```json
{
  "type": "ping"
}
```

### 服务器到客户端

**连接确认:**
```json
{
  "type": "connected",
  "session_id": "会话ID",
  "timestamp": "ISO时间戳"
}
```

**状态更新:**
```json
{
  "type": "status",
  "status": "running|completed|stopped|error",
  "message": "状态描述",
  "timestamp": "ISO时间戳"
}
```

**日志消息:**
```json
{
  "type": "log",
  "level": "info|warning|error",
  "message": "日志内容",
  "timestamp": "ISO时间戳"
}
```

**工具调用:**
```json
{
  "type": "tool_call",
  "tool_name": "工具名称",
  "tool_args": {"参数": "值"},
  "tool_call_id": "调用ID",
  "timestamp": "ISO时间戳"
}
```

**工具结果:**
```json
{
  "type": "tool_result",
  "tool_name": "工具名称",
  "tool_call_id": "调用ID",
  "result": "结果内容(截断到500字符)",
  "timestamp": "ISO时间戳"
}
```

**最终结果:**
```json
{
  "type": "result",
  "content": "最终输出内容",
  "round": "执行轮次",
  "timestamp": "ISO时间戳"
}
```

**错误消息:**
```json
{
  "type": "error",
  "error": "错误描述",
  "details": "详细堆栈(可选)",
  "timestamp": "ISO时间戳"
}
```

**流式输出(仅chat):**
```json
{
  "type": "stream",
  "content": "流式输出内容",
  "session_id": "会话ID"
}
```

## 使用示例

### Python 客户端示例

```python
import requests

# 创建会话
response = requests.post('http://localhost:8000/api/v1/sessions', json={
    'project_id': 'code_genesis',
    'session_type': 'project'
})
session = response.json()['data']
session_id = session['id']

# 启动 Agent 执行
response = requests.post('http://localhost:8000/api/v1/agent/run', json={
    'session_id': session_id,
    'query': '创建一个简单的 Python 项目'
})

# 获取执行状态
response = requests.get(f'http://localhost:8000/api/v1/agent/status/{session_id}')
status = response.json()['data']
```

## 测试

### 运行测试脚本

启动服务器后,运行测试脚本验证功能:

```bash
python api/test_api.py
```

测试脚本会验证:
- 健康检查
- 配置管理
- 项目列表
- 会话创建和管理
- Agent状态查询
- WebSocket连接

### 手动测试WebSocket

使用Python WebSocket客户端:

```python
import asyncio
import websockets
import json

async def agent_communication():
    uri = f"ws://localhost:8000/ws/agent/{session_id}"
    
    async with websockets.connect(uri) as websocket:
        # 发送启动消息
        await websocket.send(json.dumps({
            'type': 'start',
            'query': '创建一个 Python 项目'
        }))
        
        # 接收消息
        async for message in websocket:
            data = json.loads(message)
            print(f"收到消息: {data}")
            
            if data.get('type') == 'status' and data.get('status') == 'completed':
                break

asyncio.run(agent_communication())
```

### 测试Agent执行

```python
import requests
import time

# 1. 创建会话
response = requests.post('http://localhost:8000/api/v1/sessions', json={
    'project_id': 'chat',
    'session_type': 'chat'
})
session_id = response.json()['data']['id']

# 2. 启动agent(需要先配置LLM)
response = requests.post('http://localhost:8000/api/v1/agent/run', json={
    'session_id': session_id,
    'query': '你好,介绍一下你自己',
    'project_id': 'chat'
})

# 3. 查询状态
while True:
    response = requests.get(f'http://localhost:8000/api/v1/agent/status/{session_id}')
    status = response.json()['data']['status']
    print(f"Status: {status}")
    if status in ['completed', 'error', 'stopped']:
        break
    time.sleep(1)

# 4. 获取消息历史
response = requests.get(f'http://localhost:8000/api/v1/sessions/{session_id}/messages')
messages = response.json()['data']
for msg in messages:
    print(f"[{msg['role']}]: {msg['content'][:100]}")
```

## 架构设计

### 核心组件

```
api/
├── __init__.py              # 包初始化
├── main.py                  # 主应用入口,路由配置
├── models.py                # 数据模型定义(Pydantic)
├── utils.py                 # 工具函数
├── session_manager.py       # 会话管理器(内存存储)
├── config.py                # 配置管理 API
├── project.py               # 项目管理 API
├── session.py               # 会话管理 API
├── agent.py                 # Agent 执行 API
├── websocket.py             # WebSocket 通信 API
├── agent_executor.py        # Agent执行引擎(新增)
├── run_server.py            # 启动脚本
└── test_api.py              # API测试脚本
```

### 执行流程

**Agent/Workflow执行流程:**

1. **创建会话**: 前端调用 `POST /api/v1/sessions` 创建新会话
2. **建立WebSocket**: 前端连接到 `ws://host:port/ws/agent/{session_id}`
3. **启动执行**:
   - 方式1: 通过WebSocket发送start消息
   - 方式2: 通过REST API调用 `POST /api/v1/agent/run`
4. **实时通信**: AgentExecutor通过WebSocketCallback将事件实时广播:
   - 任务开始/结束
   - LLM响应生成
   - 工具调用和结果
   - 错误信息
5. **获取结果**: 通过WebSocket接收最终结果或查询会话消息

**关键类:**

- `AgentExecutor`: 核心执行引擎,管理LLMAgent/Workflow生命周期
- `WebSocketCallback`: 自定义回调,继承ms_agent.callbacks.Callback
- `SessionManager`: 会话状态和消息历史管理
- `ConfigManager`: 配置持久化管理
- `ConnectionManager`: WebSocket连接管理

## 参考项目

本 API Server 的设计参考了以下项目:

1. **modelscope-mcp-playground-server**: MCP 服务器实现和 Agent 调用
2. **sirchmunk**: API 架构设计、会话管理和 WebSocket 通信

## 开发说明

### 添加新的 API 端点

1. 在对应的模块文件中添加新的路由函数
2. 在 `models.py` 中定义相应的请求/响应模型
3. 在 `main.py` 中确保路由已被包含

### 扩展 WebSocket 功能

在 `websocket.py` 中的 `websocket_agent` 或 `websocket_chat` 函数中添加新的消息类型处理逻辑。

## 注意事项

1. **安全性**: 生产环境中需要配置适当的 CORS 策略和认证机制
2. **持久化**: 会话和配置数据当前存储在内存中,生产环境建议使用数据库
3. **LLM配置**: 执行Agent前需要先通过 `/api/v1/config/llm` 配置有效的API密钥
4. **并发执行**: 支持多个会话同时执行,每个会话有独立的工作目录
5. **日志记录**: 服务器日志记录在控制台,可以调整logging级别
6. **错误处理**: 所有API都有统一的错误处理,返回标准错误格式

## 常见问题

### 1. Agent执行失败

**症状**: WebSocket收到error消息或status为error

**可能原因**:
- LLM API密钥未配置或无效
- 项目配置文件有误
- 网络连接问题

**解决方案**:
- 检查 `/api/v1/config/status` 确认配置状态
- 查看服务器日志获取详细错误信息
- 通过 `/api/v1/sessions/{session_id}/messages` 查看错误消息

### 2. WebSocket连接失败

**症状**: 无法连接到WebSocket端点

**可能原因**:
- 会话ID不存在
- 服务器未启动
- CORS配置问题

**解决方案**:
- 先创建会话再连接WebSocket
- 确认服务器正在运行
- 检查浏览器控制台错误信息

### 3. 配置不生效

**症状**: Agent使用了错误的配置

**原因**: 配置优先级问题

**解决方案**:
- API配置会覆盖项目配置
- 通过 `/api/v1/config` 查看当前配置
- 保存新配置后重新启动Agent执行

## 扩展开发

### 添加新的API端点

1. 在对应的模块文件(如`agent.py`)中添加新的路由函数
2. 在 `models.py` 中定义相应的请求/响应模型
3. 确保在 `main.py` 中路由已被包含

### 扩展WebSocket功能

在 `websocket.py` 中添加新的消息类型处理:

```python
elif message_type == 'custom_action':
    # 处理自定义动作
    await manager.broadcast_to_session({
        'type': 'custom_response',
        'data': result
    }, session_id)
```

### 自定义Callback

继承 `WebSocketCallback` 添加更多事件监听:

```python
class CustomCallback(WebSocketCallback):
    async def on_custom_event(self, runtime, messages):
        await self._broadcast({
            'type': 'custom_event',
            'data': 'custom data'
        })
```

## 许可证

Copyright (c) Alibaba, Inc. and its affiliates.
