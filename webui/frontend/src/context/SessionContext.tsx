import React, { createContext, useContext, useState, useEffect, useCallback, useRef, ReactNode } from 'react';

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  type: 'text' | 'tool_call' | 'tool_result' | 'error' | 'log' | 'file_output' | 'step_start' | 'step_complete';
  timestamp: string;
  metadata?: Record<string, unknown>;

  client_request_id?: string;
  retry_of?: string;
  status?: 'sent' | 'running' | 'error' | 'completed'; // 给 UI 用
}

export interface Project {
  id: string;
  name: string;
  display_name: string;
  description: string;
  type: 'workflow' | 'agent' | 'script';
  path: string;
  has_readme: boolean;
}

export interface WorkflowProgress {
  current_step: string;
  steps: string[];
  step_status: Record<string, 'running' | 'completed' | 'pending'>;
}

export interface FileProgress {
  file: string;
  status: 'writing' | 'completed';
}

export interface Session {
  id: string;
  project_id: string;
  project_name: string;
  status: 'idle' | 'running' | 'completed' | 'error' | 'stopped';
  created_at: string;
  workflow_progress?: WorkflowProgress;
  file_progress?: FileProgress;
  current_step?: string;
}

export interface LogEntry {
  level: 'info' | 'warning' | 'error' | 'debug';
  message: string;
  timestamp: string;
  session_id?: string;
}

interface SessionContextType {
  projects: Project[];
  sessions: Session[];
  currentSession: Session | null;
  messages: Message[];
  logs: LogEntry[];
  streamingContent: string;
  isStreaming: boolean;
  isLoading: boolean;
  loadProjects: () => Promise<void>;
  createSession: (projectId: string) => Promise<Session | null>;
  selectSession: (sessionId: string, initialQuery?: string, sessionObj?: Session) => void;
  sendMessage: (content: string, opts?: { reuseMessageId?: string }) => void;
  stopAgent: () => void;
  clearLogs: () => void;
}

const SessionContext = createContext<SessionContextType | undefined>(undefined);

const API_BASE = '/api';
const WS_BASE = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

const PROJECT_DESCRIPTION_OVERRIDES: Record<string, string> = {
  deep_research:
    'This project provides a framework for deep research, enabling agents to autonomously explore and execute complex tasks.',
  code_genesis:
    'This project provides a code generation workflow that helps agents plan, scaffold, and refine software projects end-to-end.',
  agent_skills:
    'This project provides a collection of reusable agent skills and tools to automate tasks and extend agent capabilities.',
  doc_research:
    'This project provides a document research workflow for ingesting, searching, and summarizing documents with agent assistance.',
  fin_research:
    'This project provides a financial research workflow that combines data analysis and information gathering to produce structured reports.',
  singularity_cinema:
    'This project provides a creative workflow for generating stories, scripts, and media ideas with agent collaboration.',
};

export const SessionProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [streamingContent, setStreamingContent] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [ws, setWs] = useState<WebSocket | null>(null);
  const pendingQueryRef = useRef<string | null>(null);

  // Load projects
  const loadProjects = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/projects`);
      if (response.ok) {
        const data = await response.json();
        const projectsWithOverrides: Project[] = (Array.isArray(data) ? data : []).map((project: Project) => {
          const overrideDescription = project?.id ? PROJECT_DESCRIPTION_OVERRIDES[project.id] : undefined;
          if (overrideDescription) {
            return { ...project, description: overrideDescription };
          }
          return project;
        });
        setProjects(projectsWithOverrides);
      }
    } catch (error) {
      console.error('Failed to load projects:', error);
    }
  }, []);

  // Create session
  const createSession = useCallback(async (projectId: string): Promise<Session | null> => {
    try {
      const response = await fetch(`${API_BASE}/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId }),
      });

      if (response.ok) {
        const session = await response.json();
        setSessions(prev => [...prev, session]);
        return session;
      }
    } catch (error) {
      console.error('Failed to create session:', error);
    }
    return null;
  }, []);

  const endRunningState = useCallback((nextStatus: Session['status'], errMsg?: string) => {
    setIsLoading(false);
    setIsStreaming(false);
    setStreamingContent('');

    setCurrentSession(prev => {
      if (!prev) return prev;
      return { ...prev, status: nextStatus, workflow_progress: undefined, file_progress: undefined, current_step: undefined };
    });

    setSessions(prev =>
      prev.map(s => (s.id === currentSession?.id ? { ...s, status: nextStatus } : s))
    );

    if (errMsg) {
      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last && last.type === 'error' && last.content === errMsg) return prev;
        return [...prev, {
          id: Date.now().toString(),
          role: 'system',
          content: errMsg,
          type: 'error',
          timestamp: new Date().toISOString(),
        }];
      });
    }
  }, [currentSession?.id]);

  // Connect WebSocket for session
  const connectWebSocket = useCallback((sessionId: string, initialQuery?: string) => {
    if (ws) {
      ws.close();
    }

    // Store pending query to send after connection
    if (initialQuery) {
      pendingQueryRef.current = initialQuery;
    }

    const socket = new WebSocket(`${WS_BASE}/session/${sessionId}`);

    socket.onopen = () => {
      console.log('WebSocket connected');
      // Send pending query if exists
      if (pendingQueryRef.current && socket.readyState === WebSocket.OPEN) {
        const query = pendingQueryRef.current;
        pendingQueryRef.current = null;

        // Add user message locally
        setMessages(prev => [...prev, {
          id: Date.now().toString(),
          role: 'user',
          content: query,
          type: 'text',
          timestamp: new Date().toISOString(),
        }]);

        socket.send(JSON.stringify({
          action: 'start',
          query: query,
        }));

        setIsLoading(true);
      }
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
      } catch (e) {
        console.error('[WS] Non-JSON message:', event.data, e);

        // Fallback: stop the loading state to avoid being stuck in "Processing".
        endRunningState('error', typeof event.data === 'string'
          ? event.data
          : 'Agent failed with non-JSON output');

        // Don't throw again to avoid a blank screen.
      }
    };

    socket.onclose = () => {
      console.log('WebSocket disconnected');

      // If it's still running and the connection drops: end with an error
      // to avoid the frontend being stuck in "Processing...".
      setWs(null);
      endRunningState('error', 'Connection closed unexpectedly. Please retry.');
    };

    socket.onerror = (error) => {
      console.error('WebSocket error:', error);

      // onerror may sometimes be followed by onclose, but adding a fallback here doesn't hurt.
      endRunningState('error', 'WebSocket error occurred. Please retry.');
    };

    setWs(socket);
  }, [ws, endRunningState]);

  // Handle WebSocket messages
  const handleWebSocketMessage = useCallback((data: Record<string, unknown>) => {
    const type = data.type as string;

    switch (type) {
      case 'message':
        setMessages(prev => [...prev, {
          id: Date.now().toString(),
          role: data.role as Message['role'],
          content: data.content as string,
          type: (data.message_type as Message['type']) || 'text',
          timestamp: new Date().toISOString(),
          metadata: data.metadata as Record<string, unknown>,
        }]);
        break;

      case 'stream':
        setStreamingContent(data.content as string);
        setIsStreaming(!data.done);
        if (data.done) {
          setMessages(prev => [...prev, {
            id: Date.now().toString(),
            role: 'assistant',
            content: data.content as string,
            type: 'text',
            timestamp: new Date().toISOString(),
          }]);
          setStreamingContent('');
        }
        break;

      case 'log':
        setLogs(prev => [...prev, {
          level: data.level as LogEntry['level'],
          message: data.message as string,
          timestamp: data.timestamp as string,
          session_id: currentSession?.id,
        }]);
        break;

      case 'progress':
        setCurrentSession(prev => {
          if (!prev) return prev;

          const progressType =
            (data.progress_type as string | undefined) ??
            (data.progressType as string | undefined) ??
            (data.kind as string | undefined);
          if (progressType === 'workflow') {
            return {
              ...prev,
              workflow_progress: {
                current_step: data.current_step as string,
                steps: data.steps as string[],
                step_status: data.step_status as WorkflowProgress['step_status'],
              },
              current_step: data.current_step as string,
            };
          } else if (progressType === 'file') {
            return {
              ...prev,
              file_progress: {
                file: data.file as string,
                status: data.status as FileProgress['status'],
              },
            };
          }
          return prev;
        });
        break;

      case 'status': {
        const nextStatus =
          (data.status as Session['status'] | undefined) ??
          ((data as any)?.session?.status as Session['status'] | undefined);

        if (!nextStatus) break;

        if (nextStatus === 'running') {
          setCurrentSession(prev => (prev ? { ...prev, status: 'running' } : prev));
          setSessions(prev => prev.map(s => (s.id === currentSession?.id ? { ...s, status: 'running' } : s)));
          setIsLoading(true);
        } else {
          endRunningState(nextStatus);
        }
        break;
      }

      case 'complete':
        setCurrentSession(prev => {
          if (!prev) return prev;
          return { ...prev, status: 'completed' };
        });
        setSessions(prev => prev.map(s => (s.id === currentSession?.id ? { ...s, status: 'completed' } : s)));
        endRunningState('completed');
        break;

      case 'error':
        setCurrentSession(prev => {
          if (!prev) return prev;
          return { ...prev, status: 'error' };
        });
        setSessions(prev => prev.map(s => (s.id === currentSession?.id ? { ...s, status: 'error' } : s)));
        setMessages(prev => [...prev, {
          id: Date.now().toString(),
          role: 'system',
          content: data.message as string,
          type: 'error',
          timestamp: new Date().toISOString(),
        }]);
        endRunningState('error', (data.message as string) || 'Unknown error');
        break;
    }
  }, [currentSession?.id, endRunningState]);

  // Select session (can pass session object directly for newly created sessions)
  const selectSession = useCallback((sessionId: string, initialQuery?: string, sessionObj?: Session) => {
    // Use passed session object or find from sessions array
    const session = sessionObj || sessions.find(s => s.id === sessionId);
    if (session) {
      console.log('[Session] Selecting session:', session.id);
      setCurrentSession(session);
      setMessages([]);
      setLogs([]);
      setStreamingContent('');
      connectWebSocket(sessionId, initialQuery);
    } else {
      console.error('[Session] Session not found:', sessionId);
    }
  }, [sessions, connectWebSocket]);

  // Send message
const sendMessage = useCallback((content: string, opts?: { reuseMessageId?: string }) => {
  if (!currentSession || !ws || ws.readyState !== WebSocket.OPEN) return;

  const clientRequestId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;

  // Reuse mode: update the existing message instead of adding a new one.
  if (opts?.reuseMessageId) {
    setMessages(prev => prev.map(m => {
      if (m.id !== opts.reuseMessageId) return m;
      return {
        ...m,
        content,
        status: 'running',
        client_request_id: clientRequestId,
      };
    }));
  } else {
    // Default: add a new user message.
    setMessages(prev => [...prev, {
      id: Date.now().toString(),
      role: 'user',
      content,
      type: 'text',
      timestamp: new Date().toISOString(),
      status: 'running',
      client_request_id: clientRequestId,
    }]);
  }

  ws.send(JSON.stringify({
    action: 'start',
    query: content,
    client_request_id: clientRequestId, // If the backend can pass it back unchanged, that would be better.
  }));

  setIsStreaming(false);
  setStreamingContent('');
  setIsLoading(true);
}, [currentSession, ws]);

  // Stop agent
  const stopAgent = useCallback(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: 'stop' }));
    }

    // Optimistic UI update: reflect stop immediately without waiting for backend
    setCurrentSession(prev => {
      if (!prev) return prev;
      return { ...prev, status: 'stopped', workflow_progress: undefined, file_progress: undefined, current_step: undefined };
    });
    setSessions(prev => prev.map(s => (s.id === currentSession?.id ? { ...s, status: 'stopped' } : s)));
    setIsLoading(false);
    setIsStreaming(false);
    setStreamingContent('');
  }, [ws, currentSession?.id]);

  // Clear logs
  const clearLogs = useCallback(() => {
    setLogs([]);
  }, []);

  // Initial load
  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  // Cleanup WebSocket on unmount
  useEffect(() => {
    return () => {
      if (ws) {
        ws.close();
      }
    };
  }, [ws]);

  return (
    <SessionContext.Provider
      value={{
        projects,
        sessions,
        currentSession,
        messages,
        logs,
        streamingContent,
        isStreaming,
        isLoading,
        loadProjects,
        createSession,
        selectSession,
        sendMessage,
        stopAgent,
        clearLogs,
      }}
    >
      {children}
    </SessionContext.Provider>
  );
};

export const useSession = () => {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used within a SessionProvider');
  }
  return context;
};
