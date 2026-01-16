# MS-Agent WebUI Backend - 开发者指南

## 概述

MS-Agent WebUI后端负责管理前端与ms-agent框架之间的通信，通过WebSocket实现实时交互，支持多种项目类型的运行和监控。

## 架构设计

### 核心组件

```
┌─────────────┐         WebSocket          ┌──────────────────┐
│  Frontend   │ ◄────────────────────────► │ WebSocket Handler│
└─────────────┘                            └────────┬─────────┘
                                                    │
                                                    │
                                                    ▼
┌──────────────────┐                    ┌──────────────────────┐
│Project Discovery │                    │    Agent Runner      │
└──────────────────┘                    └──────────┬───────────┘
                                                    │
                                                    ▼
┌──────────────────┐                    ┌──────────────────────┐
│ Session Manager  │                    │    ms-agent Process  │
└──────────────────┘                    └──────────────────────┘
```

### 文件职责

| 文件 | 职责 |
|------|--------|
| `main.py` | FastAPI应用入口，路由配置 |
| `api.py` | REST API端点定义 |
| `websocket_handler.py` | WebSocket连接管理和消息处理 |
| `agent_runner.py` | ms-agent进程管理和输出解析 |
| `project_discovery.py` | 项目发现和类型识别 |
| `session_manager.py` | 会话状态管理 |
| `config_manager.py` | 配置文件管理 |
| `shared.py` | 共享实例初始化 |

## 请求处理流程

### 1. 项目发现阶段

**文件**: `project_discovery.py`

系统启动时扫描项目目录，根据配置文件识别项目类型：

```python
def _analyze_project(self, name: str, path: str):
    # 检查配置文件确定项目类型
    workflow_file = os.path.join(path, 'workflow.yaml')
    agent_file = os.path.join(path, 'agent.yaml')
    run_file = os.path.join(path, 'run.py')
    
    if os.path.exists(workflow_file):
        project_type = 'workflow'      # 工作流项目
        config_file = workflow_file
    elif os.path.exists(agent_file):
        project_type = 'agent'         # 代理项目
        config_file = agent_file
    elif os.path.exists(run_file):
        project_type = 'script'        # 脚本项目
        config_file = run_file
```

**项目类型说明**:
- **workflow**: 使用`workflow.yaml`配置，通过ms-agent CLI运行
- **agent**: 使用`agent.yaml`配置，通过ms-agent CLI运行
- **script**: 使用`run.py`脚本，直接Python执行

### 2. WebSocket连接阶段

**文件**: `websocket_handler.py`

前端通过WebSocket连接到后端：

```python
@router.websocket("/session/{session_id}")
async def websocket_session(websocket: WebSocket, session_id: str):
    await connection_manager.connect(websocket, session_id)
    
    try:
        while True:
            data = await websocket.receive_json()
            await handle_session_message(session_id, data, websocket)
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket, session_id)
```

**支持的消息类型**:
- `start`: 启动代理
- `stop`: 停止代理
- `send_input`: 向运行中的代理发送输入
- `get_status`: 获取当前状态

### 3. 代理启动阶段

**文件**: `websocket_handler.py`

处理启动请求，创建AgentRunner实例：

```python
async def start_agent(session_id: str, data: Dict[str, Any], websocket: WebSocket):
    # 1. 获取会话信息
    session = session_manager.get_session(session_id)
    
    # 2. 获取项目信息
    project = project_discovery.get_project(session['project_id'])
    
    # 3. 创建AgentRunner
    runner = AgentRunner(
        session_id=session_id,
        project=project,  # 包含项目类型和配置文件路径
        config_manager=config_manager,
        on_output=lambda msg: asyncio.create_task(on_agent_output(session_id, msg)),
        on_log=lambda log: asyncio.create_task(on_agent_log(session_id, log)),
        on_progress=lambda prog: asyncio.create_task(on_agent_progress(session_id, prog)),
        on_complete=lambda result: asyncio.create_task(on_agent_complete(session_id, result)),
        on_error=lambda err: asyncio.create_task(on_agent_error(session_id, err))
    )
    
    # 4. 启动代理
    task = asyncio.create_task(runner.start(data.get('query', '')))
```

### 4. 命令构建阶段

**文件**: `agent_runner.py`

根据项目类型构建对应的ms-agent命令：

```python
def _build_command(self, query: str) -> list:
    project_type = self.project.get('type')
    config_file = self.project.get('config_file', '')
    
    if project_type == 'workflow' or project_type == 'agent':
        # workflow/agent类型：使用ms-agent CLI
        cmd = [
            'ms-agent', 'run',
            '--config', config_file,           # workflow.yaml 或 agent.yaml
            '--trust_remote_code', 'true'
        ]
        
        if query:
            cmd.extend(['--query', query])
        
        # 添加MCP服务器配置
        mcp_file = self.config_manager.get_mcp_file_path()
        if os.path.exists(mcp_file):
            cmd.extend(['--mcp_server_file', mcp_file])
        
        # 添加LLM配置
        llm_config = self.config_manager.get_llm_config()
        if llm_config.get('api_key'):
            provider = llm_config.get('provider', 'modelscope')
            if provider == 'modelscope':
                cmd.extend(['--modelscope_api_key', llm_config['api_key']])
            elif provider == 'openai':
                cmd.extend(['--openai_api_key', llm_config['api_key']])
    
    elif project_type == 'script':
        # script类型：直接运行Python脚本
        cmd = [python, self.project['config_file']]  # run.py
    
    return cmd
```

## 不同项目类型的命令对应

| 项目类型 | 配置文件 | ms-agent命令 |
|---------|----------|--------------|
| **workflow** | `workflow.yaml` | `ms-agent run --config workflow.yaml --trust_remote_code true --query "xxx" --mcp_server_file xxx.json --modelscope_api_key xxx` |
| **agent** | `agent.yaml` | `ms-agent run --config agent.yaml --trust_remote_code true --query "xxx" --mcp_server_file xxx.json --modelscope_api_key xxx` |
| **script** | `run.py` | `python run.py` |