# MS-Agent WebUI Frontend

基于 Next.js + Tailwind CSS 的 MS-Agent 前端界面,参考 sirchmunk/web 架构实现。

## 技术栈

- **框架**: Next.js 16 (App Router)
- **样式**: Tailwind CSS 3
- **语言**: TypeScript 5
- **UI 库**: Lucide React (图标)
- **Markdown**: React Markdown + KaTeX (数学公式)

## 功能特性

### 已实现功能

1. **Home (Chat) 页面**
   - 项目选择器 (支持切换不同的 Agent 项目)
   - 实时对话界面
   - WebSocket 连接支持
   - Markdown 渲染 + 代码高亮
   - 流式输出显示

2. **Settings 页面**
   - LLM 配置 (Provider, Model, API Key, Base URL)
   - Temperature 控制
   - Max Tokens 设置
   - Dark/Light 主题切换

3. **Monitor 页面**
   - 系统健康状态监控
   - 会话列表展示
   - 实时数据刷新
   - 会话状态可视化

4. **核心组件**
   - Sidebar (可折叠侧边栏)
   - GlobalContext (全局状态管理)
   - Theme 系统 (支持 Dark/Light 模式)
   - API 封装 (完整对接后端接口)

## 目录结构

```
frontend/
├── app/                          # Next.js App Router
│   ├── layout.tsx               # 根布局
│   ├── page.tsx                 # Home/Chat 页面
│   ├── monitor/page.tsx         # Monitor 页面
│   ├── settings/page.tsx        # Settings 页面
│   └── globals.css              # 全局样式
├── components/                   # 共享组件
│   ├── Sidebar.tsx              # 侧边栏
│   └── ThemeScript.tsx          # 主题脚本
├── context/                      # React Context
│   └── GlobalContext.tsx        # 全局状态
├── lib/                         # 工具函数
│   ├── api.ts                   # API 封装
│   └── theme.ts                 # 主题工具
├── types/                       # TypeScript 类型
│   └── api.ts                   # API 类型定义
├── next.config.ts               # Next.js 配置
├── tailwind.config.js           # Tailwind 配置
└── package.json                 # 依赖管理
```

## 快速开始

### 开发环境

1. **安装依赖**

```bash
cd webui/frontend
npm install
```

2. **配置环境变量**

创建 `.env.local` 文件:

```bash
# API Base URL (开发环境)
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

3. **启动开发服务器**

```bash
npm run dev
```

访问 http://localhost:3000

### 生产构建

1. **静态导出模式** (推荐用于与 FastAPI 集成)

```bash
# 设置环境变量
export NEXT_BUILD_STATIC=true

# 构建
npm run build

# 输出目录: out/
```

2. **标准模式**

```bash
npm run build
npm start
```

## API 对接

前端完全对接了 `/api` 目录下的后端接口:

### Session APIs
- `POST /api/v1/sessions` - 创建会话
- `GET /api/v1/sessions` - 获取会话列表
- `GET /api/v1/sessions/{id}` - 获取会话详情

### Project APIs
- `GET /api/v1/projects` - 获取项目列表
- `GET /api/v1/projects/{id}` - 获取项目详情

### Config APIs
- `GET /api/v1/config/llm` - 获取 LLM 配置
- `POST /api/v1/config/llm` - 保存 LLM 配置

### Agent APIs
- `POST /api/v1/agent/run` - 启动 Agent
- `POST /api/v1/agent/stop` - 停止 Agent
- `WS /ws/agent/{session_id}` - WebSocket 实时通信

### Health Check
- `GET /health` - 健康检查

## WebSocket 消息格式

### 客户端 → 服务器

```json
{
  "type": "start",
  "query": "用户查询内容",
  "project_id": "项目ID",
  "workflow_type": "standard"
}
```

### 服务器 → 客户端

```json
{
  "type": "stream",
  "content": "流式输出内容"
}
```

支持的消息类型:
- `connected` - 连接成功
- `status` - 状态更新
- `log` - 日志消息
- `stream` - 流式输出
- `result` - 最终结果
- `error` - 错误消息

## 主题系统

支持 Dark/Light 主题切换,主题设置保存在 localStorage。

```typescript
import { setTheme } from '@/lib/theme';

// 切换主题
setTheme('dark'); // or 'light'
```

## 全局状态管理

使用 React Context 管理全局状态:

```typescript
import { useGlobal } from '@/context/GlobalContext';

function MyComponent() {
  const { agentState, createSession, sendMessage } = useGlobal();
  // ...
}
```

## 开发说明

### 添加新页面

1. 在 `app/` 目录下创建新文件夹
2. 添加 `page.tsx` 文件
3. 在 `Sidebar.tsx` 中添加导航链接

### 添加新 API

1. 在 `types/api.ts` 中定义类型
2. 在 `lib/api.ts` 中添加 API 函数
3. 在组件中使用

### 样式定制

修改 `tailwind.config.js` 来自定义样式:

```javascript
module.exports = {
  theme: {
    extend: {
      colors: {
        // 自定义颜色
      },
    },
  },
}
```

## 与旧版本的对比

### 架构改进

- ✅ React + MUI → Next.js + Tailwind CSS
- ✅ 单体应用 → 页面分离的 App Router 架构
- ✅ 内联样式 → Tailwind 实用类
- ✅ 基础状态管理 → 完整的 GlobalContext

### 功能增强

- ✅ 更现代的 UI 设计
- ✅ 更好的主题切换体验
- ✅ 更完整的 WebSocket 支持
- ✅ 更丰富的项目选择功能
- ✅ 实时系统监控

## 注意事项

1. **API 配置**: 确保后端 API 服务器正在运行 (默认 http://localhost:8000)
2. **CORS**: 后端需要配置 CORS 允许前端访问
3. **WebSocket**: 确保 WebSocket 端点可访问
4. **LLM 配置**: 使用前需要在 Settings 页面配置 LLM API Key

## 后续开发建议

1. **增强功能**
   - 添加文件预览功能
   - 实现 Workflow 进度可视化
   - 添加 Deep Research 事件流展示
   - 实现 Code Genesis 文件树预览

2. **UI 优化**
   - 添加更多动画效果
   - 优化移动端响应式布局
   - 添加加载骨架屏

3. **性能优化**
   - 实现虚拟滚动 (长消息列表)
   - 优化 WebSocket 重连机制
   - 添加请求缓存

## 许可证

Copyright (c) Alibaba, Inc. and its affiliates.
