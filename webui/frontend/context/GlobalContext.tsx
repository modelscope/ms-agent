'use client';

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useRef,
} from 'react';
import { wsUrl } from '@/lib/api';
import {
  initializeTheme,
  setTheme as setThemeLib,
  getStoredTheme,
  type Theme,
} from '@/lib/theme';
import type {
  SessionInfo,
  ProjectInfo,
  ChatMessage,
  WSMessage,
} from '@/types/api';

// Agent State
interface AgentState {
  sessionId: string | null;
  messages: ChatMessage[];
  isLoading: boolean;
  currentStage: string | null;
  selectedProject: string | null;
  workflowType: 'standard' | 'simple';
}

// Global Context Type
interface GlobalContextType {
  // Theme
  theme: Theme;
  setTheme: (theme: Theme) => void;
  
  // Agent State
  agentState: AgentState;
  setAgentState: React.Dispatch<React.SetStateAction<AgentState>>;
  
  // Agent Actions
  createSession: (projectId: string, query?: string) => Promise<string | null>;
  sendMessage: (query: string) => void;
  newSession: () => void;
  
  // Projects
  projects: ProjectInfo[];
  loadProjects: () => Promise<void>;
  
  // Sidebar
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
}

const GlobalContext = createContext<GlobalContextType | undefined>(undefined);

export function GlobalProvider({ children }: { children: React.ReactNode }) {
  // Theme State
  const [theme, setThemeState] = useState<Theme>('light');
  const [isInitialized, setIsInitialized] = useState(false);
  
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const storedTheme = getStoredTheme();
      const finalTheme = storedTheme || initializeTheme();
      setThemeState(finalTheme);
      setIsInitialized(true);
    }
  }, []);
  
  const handleSetTheme = (newTheme: Theme) => {
    setThemeState(newTheme);
    setThemeLib(newTheme);
  };
  
  // Agent State
  const [agentState, setAgentState] = useState<AgentState>({
    sessionId: null,
    messages: [],
    isLoading: false,
    currentStage: null,
    selectedProject: null,
    workflowType: 'standard',
  });
  
  // Projects State
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  
  // WebSocket
  const wsRef = useRef<WebSocket | null>(null);
  
  // Sidebar State
  const [sidebarCollapsed, setSidebarCollapsedState] = useState(false);
  
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('sidebarCollapsed');
      if (stored) {
        setSidebarCollapsedState(stored === 'true');
      }
    }
  }, []);
  
  const setSidebarCollapsed = (collapsed: boolean) => {
    setSidebarCollapsedState(collapsed);
    if (typeof window !== 'undefined') {
      localStorage.setItem('sidebarCollapsed', collapsed.toString());
    }
  };
  
  // Load Projects
  const loadProjects = async () => {
    try {
      const response = await fetch('/api/v1/projects');
      const data = await response.json();
      if (data.success) {
        setProjects(data.data || []);
      }
    } catch (error) {
      console.error('Failed to load projects:', error);
    }
  };
  
  useEffect(() => {
    loadProjects();
  }, []);
  
  // Create Session
  const createSession = async (
    projectId: string,
    query?: string
  ): Promise<string | null> => {
    try {
      const response = await fetch('/api/v1/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          query,
          workflow_type: agentState.workflowType,
          session_type: projectId === 'chat' ? 'chat' : 'project',
        }),
      });
      
      const data = await response.json();
      if (data.success && data.data) {
        const sessionId = data.data.id;
        setAgentState(prev => ({
          ...prev,
          sessionId,
          selectedProject: projectId,
          messages: [],
        }));
        return sessionId;
      }
    } catch (error) {
      console.error('Failed to create session:', error);
    }
    return null;
  };
  
  // Send Message via WebSocket
  const sendMessage = (query: string) => {
    if (!query.trim() || agentState.isLoading) return;
    
    // Add user message
    setAgentState(prev => ({
      ...prev,
      isLoading: true,
      currentStage: 'connecting',
      messages: [
        ...prev.messages,
        { role: 'user', content: query, timestamp: new Date().toISOString() },
      ],
    }));
    
    // Close existing WebSocket
    if (wsRef.current) {
      wsRef.current.close();
    }
    
    // Create WebSocket connection
    const sessionId = agentState.sessionId;
    if (!sessionId) {
      console.error('No session ID');
      return;
    }
    
    const ws = new WebSocket(wsUrl(`/ws/agent/${sessionId}`));
    wsRef.current = ws;
    
    let assistantMessage = '';
    
    ws.onopen = () => {
      ws.send(JSON.stringify({
        type: 'start',
        query,
        project_id: agentState.selectedProject,
        workflow_type: agentState.workflowType,
      }));
    };
    
    ws.onmessage = (event) => {
      const data: WSMessage = JSON.parse(event.data);
      
      switch (data.type) {
        case 'connected':
          setAgentState(prev => ({ ...prev, currentStage: 'running' }));
          break;
          
        case 'status':
          setAgentState(prev => ({ ...prev, currentStage: data.message || data.status || null }));
          break;
          
        case 'log':
          // Optionally handle logs
          console.log('[Agent Log]:', data.message);
          break;
          
        case 'stream':
          assistantMessage += data.content || '';
          setAgentState(prev => {
            const messages = [...prev.messages];
            const lastMessage = messages[messages.length - 1];
            if (lastMessage?.role === 'assistant') {
              messages[messages.length - 1] = {
                ...lastMessage,
                content: assistantMessage,
              };
            } else {
              messages.push({
                role: 'assistant',
                content: assistantMessage,
                timestamp: new Date().toISOString(),
              });
            }
            return { ...prev, messages, currentStage: 'generating' };
          });
          break;
          
        case 'result':
          setAgentState(prev => {
            const messages = [...prev.messages];
            const lastMessage = messages[messages.length - 1];
            if (lastMessage?.role === 'assistant') {
              messages[messages.length - 1] = {
                ...lastMessage,
                content: data.content || lastMessage.content,
              };
            } else {
              messages.push({
                role: 'assistant',
                content: data.content || '',
                timestamp: new Date().toISOString(),
              });
            }
            return {
              ...prev,
              messages,
              isLoading: false,
              currentStage: null,
            };
          });
          ws.close();
          break;
          
        case 'error':
          setAgentState(prev => ({
            ...prev,
            isLoading: false,
            currentStage: null,
            messages: [
              ...prev.messages,
              {
                role: 'assistant',
                content: `Error: ${data.message || 'Unknown error'}`,
                timestamp: new Date().toISOString(),
              },
            ],
          }));
          ws.close();
          break;
      }
    };
    
    ws.onerror = () => {
      setAgentState(prev => ({
        ...prev,
        isLoading: false,
        currentStage: null,
        messages: [
          ...prev.messages,
          {
            role: 'assistant',
            content: 'Connection error. Please try again.',
            timestamp: new Date().toISOString(),
          },
        ],
      }));
    };
    
    ws.onclose = () => {
      if (wsRef.current === ws) {
        wsRef.current = null;
      }
      setAgentState(prev => {
        if (prev.isLoading) {
          return {
            ...prev,
            isLoading: false,
            currentStage: null,
          };
        }
        return prev;
      });
    };
  };
  
  // New Session
  const newSession = () => {
    setAgentState({
      sessionId: null,
      messages: [],
      isLoading: false,
      currentStage: null,
      selectedProject: null,
      workflowType: 'standard',
    });
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  };
  
  return (
    <GlobalContext.Provider
      value={{
        theme,
        setTheme: handleSetTheme,
        agentState,
        setAgentState,
        createSession,
        sendMessage,
        newSession,
        projects,
        loadProjects,
        sidebarCollapsed,
        setSidebarCollapsed,
      }}
    >
      {children}
    </GlobalContext.Provider>
  );
}

export function useGlobal() {
  const context = useContext(GlobalContext);
  if (!context) {
    throw new Error('useGlobal must be used within GlobalProvider');
  }
  return context;
}
