// API Types for MS-Agent

export interface SessionCreate {
  project_id?: string;
  query?: string;
  workflow_type?: 'standard' | 'simple';
  session_type?: 'project' | 'chat';
}

export interface SessionInfo {
  id: string;
  project_id: string;
  project_name: string;
  status: 'idle' | 'running' | 'completed' | 'error';
  created_at: string;
  session_type?: 'project' | 'chat';
  workflow_progress?: WorkflowProgress;
  file_progress?: FileProgress;
  current_step?: string;
}

export interface WorkflowProgress {
  current_step: string;
  total_steps: number;
  completed_steps: number;
  status: string;
}

export interface FileProgress {
  files: FileInfo[];
  total: number;
}

export interface FileInfo {
  path: string;
  name: string;
  size: number;
  modified: string;
}

export interface LLMConfig {
  provider: string;
  model: string;
  api_key?: string;
  base_url?: string;
  temperature?: number;
  temperature_enabled?: boolean;
  max_tokens?: number;
}

export interface DeepResearchAgentConfig {
  model?: string;
  api_key?: string;
  base_url?: string;
}

export interface DeepResearchSearchConfig {
  summarizer_model?: string;
  summarizer_api_key?: string;
  summarizer_base_url?: string;
}

export interface DeepResearchConfig {
  researcher: DeepResearchAgentConfig;
  searcher: DeepResearchAgentConfig;
  reporter: DeepResearchAgentConfig;
  search: DeepResearchSearchConfig;
}

export interface MCPServerConfig {
  name: string;
  type: 'stdio' | 'sse';
  command?: string;
  args?: string[];
  url?: string;
  env?: Record<string, string>;
}

export interface ProjectInfo {
  id: string;
  name: string;
  display_name: string;
  description: string;
  type: 'workflow' | 'agent';
  path: string;
  has_readme: boolean;
  supports_workflow_switch: boolean;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  timestamp?: string;
  type?: 'text' | 'tool_call' | 'tool_result' | 'error' | 'log';
  metadata?: any;
}

export interface APIResponse<T = any> {
  success: boolean;
  message?: string;
  data?: T;
  error?: string;
}

// WebSocket Message Types
export type WSMessageType = 
  | 'connected'
  | 'status'
  | 'log'
  | 'tool_call'
  | 'tool_result'
  | 'result'
  | 'error'
  | 'progress'
  | 'stream';

export interface WSMessage {
  type: WSMessageType;
  content?: any;
  timestamp?: string;
  session_id?: string;
  status?: string;
  message?: string;
  level?: string;
  tool_name?: string;
  tool_args?: any;
  tool_call_id?: string;
  result?: any;
  round?: number;
  progress?: number;
  stage?: string;
}
