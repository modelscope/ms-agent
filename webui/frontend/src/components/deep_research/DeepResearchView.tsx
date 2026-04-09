import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  Box,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  InputAdornment,
  Paper,
  Tab,
  Tabs,
  TextField,
  Typography,
  useTheme,
  alpha,
  Collapse,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Tooltip,
} from '@mui/material';
import {
  Send as SendIcon,
  Stop as StopIcon,
  Search as SearchIcon,
  Article as ArticleIcon,
  SmartToy as SmartToyIcon,
  Build as BuildIcon,
  CheckCircle as CheckCircleIcon,
  ListAlt as ListAltIcon,
  Description as DescriptionIcon,
  InsertDriveFile as FileIcon,
  Close as CloseIcon,
  ExpandMore as ExpandMoreIcon,
  OpenInNew as OpenInNewIcon,
  Download as DownloadIcon,
} from '@mui/icons-material';
import { useSession } from '../../context/SessionContext';
import MessageContent from '../MessageContent';

type DrRole = 'user' | 'assistant' | 'system' | 'tool';

interface DrChatMessage {
  id: string;
  role: DrRole;
  content: string;
  completed?: boolean;
}

interface ToolCallState {
  callId: string;
  toolName: string;
  args: any;
  result?: string;
  status: 'running' | 'completed';
  category: 'normal' | 'subagent';
  sourceMessageId?: string;
}

interface SubagentCardState {
  cardId: string;
  toolName: string;
  title: string;
  status: 'running' | 'completed';
  streaming: string;
  summary?: string;
  sourceMessageId?: string;
}

interface TodoItem {
  id: string;
  content: string;
  status: 'pending' | 'in_progress' | 'completed' | 'cancelled';
  priority?: string;
}

interface ArtifactFile {
  path: string;
  relative_path?: string;
  size: number;
  modified: number;
}

const DeepResearchView: React.FC = () => {
  const theme = useTheme();
  const { currentSession, isLoading, sendMessage, stopAgent, registerEventHandler } = useSession();

  const [input, setInput] = useState('');
  const [chatMessages, setChatMessages] = useState<DrChatMessage[]>([]);
  const [toolCalls, setToolCalls] = useState<Record<string, ToolCallState>>({});
  const [toolCallsByMessage, setToolCallsByMessage] = useState<Record<string, string[]>>({});
  const [subagentCards, setSubagentCards] = useState<Record<string, SubagentCardState>>({});
  const [subagentMessages, setSubagentMessages] = useState<Record<string, DrChatMessage[]>>({});
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [todoByCallId, setTodoByCallId] = useState<Record<string, TodoItem[]>>({});
  const [artifacts, setArtifacts] = useState<ArtifactFile[]>([]);
  const [activeCardId, setActiveCardId] = useState<string | null>(null);
  const [rightTab, setRightTab] = useState(0);
  const [rightPanelOpen, setRightPanelOpen] = useState(false);
  const [subagentToolCalls, setSubagentToolCalls] = useState<Record<string, Record<string, ToolCallState>>>({});
  const [subagentCardsByMessage, setSubagentCardsByMessage] = useState<Record<string, string[]>>({});
  const [orphanSubagentIds, setOrphanSubagentIds] = useState<string[]>([]);
  const [subagentToolCallsByMessage, setSubagentToolCallsByMessage] = useState<Record<string, Record<string, string[]>>>({});
  const [selectedFile, setSelectedFile] = useState<ArtifactFile | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [reportFile, setReportFile] = useState<ArtifactFile | null>(null);
  const [reportPreview, setReportPreview] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportReloadKey, setReportReloadKey] = useState(0);

  const [leftAutoScroll, setLeftAutoScroll] = useState(true);
  const [leftHasNew, setLeftHasNew] = useState(false);
  const [rightAutoScroll, setRightAutoScroll] = useState(true);
  const [rightHasNew, setRightHasNew] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const detailEndRef = useRef<HTMLDivElement>(null);
  const leftScrollRef = useRef<HTMLDivElement>(null);
  const rightScrollRef = useRef<HTMLDivElement>(null);
  const lastEventIdRef = useRef(0);
  const isReplayingRef = useRef(false);
  const queuedEventsRef = useRef<Record<string, unknown>[]>([]);

  const activeMessages = useMemo(() => {
    if (!activeCardId) return [];
    return subagentMessages[activeCardId] || [];
  }, [activeCardId, subagentMessages]);

  const visibleActiveMessages = useMemo(
    () => activeMessages.filter((msg) => msg.role !== 'tool'),
    [activeMessages],
  );

  const isNearBottom = useCallback((el: HTMLDivElement | null) => {
    if (!el) return true;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    return distance < 120;
  }, []);

  const scrollLeftToBottom = useCallback(() => {
    setLeftAutoScroll(true);
    setLeftHasNew(false);
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  const scrollRightToBottom = useCallback(() => {
    setRightAutoScroll(true);
    setRightHasNew(false);
    detailEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useLayoutEffect(() => {
    if (!leftAutoScroll) {
      setLeftHasNew(true);
      return;
    }
    const handle = requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    });
    return () => cancelAnimationFrame(handle);
  }, [chatMessages, toolCalls, subagentCards, orphanSubagentIds, todoByCallId, leftAutoScroll]);

  useLayoutEffect(() => {
    if (!rightPanelOpen || !activeCardId) return;
    if (!rightAutoScroll) {
      setRightHasNew(true);
      return;
    }
    const handle = requestAnimationFrame(() => {
      detailEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    });
    return () => cancelAnimationFrame(handle);
  }, [rightPanelOpen, activeCardId, visibleActiveMessages, subagentToolCalls, rightAutoScroll]);

  useEffect(() => {
    setChatMessages([]);
    setToolCalls({});
    setToolCallsByMessage({});
    setSubagentCards({});
    setSubagentMessages({});
    setSubagentCardsByMessage({});
    setOrphanSubagentIds([]);
    setSubagentToolCallsByMessage({});
    setTodos([]);
    setTodoByCallId({});
    setArtifacts([]);
    setActiveCardId(null);
    setRightPanelOpen(false);
    setSubagentToolCalls({});
    setSelectedFile(null);
    setFileContent(null);
    setLeftAutoScroll(true);
    setLeftHasNew(false);
    setRightAutoScroll(true);
    setRightHasNew(false);
    lastEventIdRef.current = 0;
    setReportFile(null);
    setReportPreview(null);
    setReportLoading(false);
    setReportReloadKey(0);
    isReplayingRef.current = false;
    queuedEventsRef.current = [];
  }, [currentSession?.id]);

  useEffect(() => {
    if (!rightPanelOpen || !activeCardId) return;
    setRightAutoScroll(true);
    setRightHasNew(false);
  }, [rightPanelOpen, activeCardId]);

  const isReportPath = useCallback((rawPath: string) => {
    const path = (rawPath || '').toLowerCase();
    const normalized = path.replace(/^\.\/+/, '');
    return (
      normalized === 'final_report.md'
      || normalized === 'final_reports.md'
      || normalized === 'report.md'
    );
  }, []);

  const getRootReportName = useCallback((rawPath: string) => {
    if (!rawPath) return null;
    const normalized = rawPath.replace(/\\/g, '/');
    if (normalized.includes('/reports/')) return null;
    const trimmed = normalized.replace(/^\.\/+/, '');
    const name = trimmed.split('/').pop() || '';
    if (isReportPath(name)) return name;
    if (isReportPath(trimmed)) return trimmed;
    return null;
  }, [isReportPath]);

  const isReportArtifact = useCallback((file: ArtifactFile) => {
    const path = file.relative_path || file.path || '';
    return isReportPath(path);
  }, [isReportPath]);

  const setReportFromPath = useCallback((path: string) => {
    const rootName = getRootReportName(path);
    if (!rootName) return;
    if (reportFile?.path === rootName || reportFile?.relative_path === rootName) return;
    setReportFile({
      path: rootName,
      relative_path: rootName,
      size: 0,
      modified: 0,
    });
    setReportPreview(null);
  }, [getRootReportName, reportFile?.path, reportFile?.relative_path]);

  const extractReportPathFromText = useCallback((text: string) => {
    if (!text) return null;
    const normalized = text.replace(/\\/g, '/').toLowerCase();
    if (normalized.includes('final_report.md')) return 'final_report.md';
    if (normalized.includes('final_reports.md')) return 'final_reports.md';
    if (normalized.includes('report.md') && !normalized.includes('reports/report.md')) {
      return 'report.md';
    }
    return null;
  }, []);

  useEffect(() => {
    const candidate = artifacts.find(isReportArtifact) || null;
    if (!candidate) return;
    if (!reportFile || candidate.path !== reportFile.path) {
      setReportFile(candidate);
      setReportPreview(null);
    }
  }, [artifacts, isReportArtifact, reportFile?.path]);

  useEffect(() => {
    if (!currentSession?.id || !reportFile) return;
    let cancelled = false;
    const loadPreview = async () => {
      setReportLoading(true);
      try {
        const path = reportFile.relative_path || reportFile.path;
        const response = await fetch('/api/files/read', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: currentSession.id,
            path,
          }),
        });
        if (!response.ok) return;
        const data = await response.json();
        if (cancelled) return;
        const content = String(data.content || '');
        setReportPreview(content);
      } catch (err) {
        // ignore preview errors
      } finally {
        if (!cancelled) {
          setReportLoading(false);
        }
      }
    };
    loadPreview();
    return () => {
      cancelled = true;
    };
  }, [currentSession?.id, reportFile?.path, reportFile?.relative_path, reportReloadKey]);

  const handleOpenReport = useCallback(() => {
    if (!reportFile) return;
    setRightTab(1);
    setRightPanelOpen(true);
    handleSelectFile(reportFile);
  }, [reportFile]);

  const handleDownloadReport = useCallback(async () => {
    if (!currentSession?.id || !reportFile) return;
    setReportLoading(true);
    try {
      const path = reportFile.relative_path || reportFile.path;
      const response = await fetch('/api/files/read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: currentSession.id,
          path,
        }),
      });
      if (!response.ok) return;
      const data = await response.json();
      const content = String(data.content || '');
      const filename = path.split('/').pop() || 'report.md';
      const blob = new Blob([content], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } finally {
      setReportLoading(false);
    }
  }, [currentSession?.id, reportFile?.path, reportFile?.relative_path]);

  const applyDrEvent = useCallback((data: Record<string, unknown>) => {
    const eventId = typeof data.event_id === 'number' ? data.event_id : undefined;
    if (eventId !== undefined) {
      if (eventId <= lastEventIdRef.current) {
        return;
      }
      lastEventIdRef.current = eventId;
    }
    const type = data.type as string;
    const payload = (data.payload || {}) as any;

    if (type === 'dr.chat.message') {
      setChatMessages(prev => [
        ...prev,
        {
          id: payload.message_id,
          role: payload.role as DrRole,
          content: payload.content || '',
        },
      ]);
      return;
    }

    if (type === 'dr.chat.message.delta') {
      const messageId = payload.message_id as string;
      const delta = payload.delta as string || '';
      const full = payload.full as string | undefined;
      setChatMessages(prev => {
        const idx = prev.findIndex(m => m.id === messageId);
        if (idx === -1) {
          return [...prev, { id: messageId, role: 'assistant', content: full || delta }];
        }
        const next = [...prev];
        next[idx] = {
          ...next[idx],
          content: full || (next[idx].content + delta),
        };
        return next;
      });
      return;
    }

    if (type === 'dr.chat.message.completed') {
      const messageId = payload.message_id as string;
      setChatMessages(prev => {
        const idx = prev.findIndex(m => m.id === messageId);
        if (idx === -1) return prev;
        const next = [...prev];
        next[idx] = {
          ...next[idx],
          content: payload.content || next[idx].content,
          completed: true,
        };
        return next;
      });
      return;
    }

    if (type === 'dr.tool.call') {
      const callId = payload.call_id as string;
      const toolArgs = payload.tool?.arguments ?? payload.arguments ?? payload.tool_args;
      const toolName = payload.tool?.name || payload.tool_name || '';
      if (toolName.includes('file_system---write_file') || toolName.includes('file_system---append_file')) {
        let candidatePath = toolArgs?.path;
        if (typeof candidatePath !== 'string' && typeof toolArgs === 'string') {
          try {
            const parsed = JSON.parse(toolArgs);
            candidatePath = parsed?.path;
          } catch (err) {
            candidatePath = undefined;
          }
        }
        if (typeof candidatePath === 'string') {
          setReportFromPath(candidatePath);
        }
      }
      setToolCalls(prev => ({
        ...prev,
        [callId]: {
          callId,
          toolName,
          args: toolArgs,
          status: 'running',
          category: payload.category || 'normal',
          sourceMessageId: payload.source_message_id,
        },
      }));
      if (payload.source_message_id) {
        setToolCallsByMessage(prev => {
          const existing = prev[payload.source_message_id] || [];
          if (existing.includes(callId)) return prev;
          return {
            ...prev,
            [payload.source_message_id]: [...existing, callId],
          };
        });
      }
      return;
    }

    if (type === 'dr.tool.result') {
      const callId = payload.call_id as string;
      const toolArgs = payload.tool?.arguments ?? payload.arguments ?? payload.tool_args;
      const toolName = payload.tool?.name || payload.tool_name || '';
      if (toolName.includes('file_system---write_file') || toolName.includes('file_system---append_file')) {
        let candidatePath = toolArgs?.path;
        if (typeof candidatePath !== 'string' && typeof toolArgs === 'string') {
          try {
            const parsed = JSON.parse(toolArgs);
            candidatePath = parsed?.path;
          } catch (err) {
            candidatePath = undefined;
          }
        }
        if (typeof candidatePath === 'string') {
          setReportFromPath(candidatePath);
          setReportReloadKey((v) => v + 1);
        } else if (typeof payload.result_text === 'string') {
          const fromText = extractReportPathFromText(payload.result_text);
          if (fromText) {
            setReportFromPath(fromText);
            setReportReloadKey((v) => v + 1);
          }
        }
      }
      setToolCalls(prev => {
        const existing = prev[callId];
        if (!existing) {
          return {
            ...prev,
            [callId]: {
              callId,
              toolName,
              args: toolArgs,
              result: payload.result_text || '',
              status: 'completed',
              category: 'normal',
              sourceMessageId: payload.source_message_id,
            },
          };
        }
        return {
          ...prev,
          [callId]: {
            ...existing,
            result: payload.result_text || '',
            status: 'completed',
          },
        };
      });
      return;
    }

    if (type === 'dr.subagent.card.start') {
      const cardId = payload.card_id as string;
      const sourceMessageId = payload.source_message_id as string | undefined;
      setSubagentCards(prev => ({
        ...prev,
        [cardId]: {
          cardId,
          toolName: payload.tool_name || '',
          title: payload.title || 'Sub Agent',
          status: 'running',
          streaming: '',
          sourceMessageId,
        },
      }));
      if (sourceMessageId) {
        setSubagentCardsByMessage(prev => {
          const existing = prev[sourceMessageId] || [];
          if (existing.includes(cardId)) return prev;
          return { ...prev, [sourceMessageId]: [...existing, cardId] };
        });
      } else {
        setOrphanSubagentIds(prev => (prev.includes(cardId) ? prev : [...prev, cardId]));
      }
      return;
    }

    if (type === 'dr.subagent.tool.call') {
      const cardId = payload.card_id as string;
      const callId = payload.call_id as string;
      const sourceMessageId = payload.source_message_id as string | undefined;
      const toolArgs = payload.tool?.arguments ?? payload.arguments ?? payload.tool_args;
      const toolName = payload.tool?.name || payload.tool_name || '';
      if (toolName.includes('file_system---write_file') || toolName.includes('file_system---append_file')) {
        let candidatePath = toolArgs?.path;
        if (typeof candidatePath !== 'string' && typeof toolArgs === 'string') {
          try {
            const parsed = JSON.parse(toolArgs);
            candidatePath = parsed?.path;
          } catch (err) {
            candidatePath = undefined;
          }
        }
        if (typeof candidatePath === 'string') {
          setReportFromPath(candidatePath);
        }
      }
      setSubagentToolCalls(prev => ({
        ...prev,
        [cardId]: {
          ...(prev[cardId] || {}),
          [callId]: {
            callId,
            toolName,
            args: toolArgs,
            status: 'running',
            category: 'normal',
            sourceMessageId,
          },
        },
      }));
      if (sourceMessageId) {
        setSubagentToolCallsByMessage(prev => {
          const cardMap = prev[cardId] || {};
          const existing = cardMap[sourceMessageId] || [];
          if (existing.includes(callId)) return prev;
          return {
            ...prev,
            [cardId]: {
              ...cardMap,
              [sourceMessageId]: [...existing, callId],
            },
          };
        });
      }
      return;
    }

    if (type === 'dr.subagent.tool.result') {
      const cardId = payload.card_id as string;
      const callId = payload.call_id as string;
      const toolArgs = payload.tool?.arguments ?? payload.arguments ?? payload.tool_args;
      const toolName = payload.tool?.name || payload.tool_name || '';
      if (toolName.includes('file_system---write_file') || toolName.includes('file_system---append_file')) {
        let candidatePath = toolArgs?.path;
        if (typeof candidatePath !== 'string' && typeof toolArgs === 'string') {
          try {
            const parsed = JSON.parse(toolArgs);
            candidatePath = parsed?.path;
          } catch (err) {
            candidatePath = undefined;
          }
        }
        if (typeof candidatePath === 'string') {
          setReportFromPath(candidatePath);
          setReportReloadKey((v) => v + 1);
        } else if (typeof payload.result_text === 'string') {
          const fromText = extractReportPathFromText(payload.result_text);
          if (fromText) {
            setReportFromPath(fromText);
            setReportReloadKey((v) => v + 1);
          }
        }
      }
      setSubagentToolCalls(prev => {
        const existing = prev[cardId]?.[callId];
        if (!existing) {
          return {
            ...prev,
            [cardId]: {
              ...(prev[cardId] || {}),
              [callId]: {
                callId,
                toolName,
                args: toolArgs,
                status: 'completed',
                category: 'normal',
                result: payload.result_text || '',
              },
            },
          };
        }
        return {
          ...prev,
          [cardId]: {
            ...prev[cardId],
            [callId]: {
              ...existing,
              result: payload.result_text || '',
              status: 'completed',
            },
          },
        };
      });
      return;
    }

    if (type === 'dr.subagent.message') {
      const cardId = payload.card_id as string;
      setSubagentMessages(prev => {
        const list = prev[cardId] ? [...prev[cardId]] : [];
        list.push({
          id: payload.message_id,
          role: payload.role as DrRole,
          content: payload.content || '',
        });
        return { ...prev, [cardId]: list };
      });
      return;
    }

    if (type === 'dr.subagent.message.delta') {
      const cardId = payload.card_id as string;
      const messageId = payload.message_id as string;
      const delta = payload.delta as string || '';
      const full = payload.full as string | undefined;
      setSubagentMessages(prev => {
        const list = prev[cardId] ? [...prev[cardId]] : [];
        const idx = list.findIndex(m => m.id === messageId);
        if (idx === -1) {
          list.push({ id: messageId, role: 'assistant', content: full || delta });
        } else {
          list[idx] = {
            ...list[idx],
            content: full || (list[idx].content + delta),
          };
        }
        return { ...prev, [cardId]: list };
      });
      setSubagentCards(prev => {
        const card = prev[cardId];
        if (!card) return prev;
        const nextContent = full || (card.streaming + delta);
        return {
          ...prev,
          [cardId]: {
            ...card,
            streaming: nextContent,
          },
        };
      });
      return;
    }

    if (type === 'dr.subagent.card.completed') {
      const cardId = payload.card_id as string;
      setSubagentCards(prev => {
        const card = prev[cardId];
        if (!card) return prev;
        return {
          ...prev,
          [cardId]: {
            ...card,
            status: 'completed',
            summary: payload.summary,
          },
        };
      });
      return;
    }

    if (type === 'dr.artifact.updated') {
      setArtifacts(payload.files || []);
      return;
    }

    if (type === 'dr.state') {
      if (Array.isArray(payload.todos)) {
        setTodos(payload.todos);
        if (payload.call_id) {
          setTodoByCallId(prev => ({
            ...prev,
            [payload.call_id]: payload.todos,
          }));
        }
      }
      return;
    }

    if (type === 'dr.worker.error') {
      setChatMessages(prev => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: 'system',
          content: payload.error || 'Worker error',
        },
      ]);
    }
  }, [
    extractReportPathFromText,
    isReportPath,
    setReportFromPath,
  ]);

  const handleDrEvent = useCallback((data: Record<string, unknown>) => {
    if (isReplayingRef.current) {
      queuedEventsRef.current.push(data);
      return;
    }
    applyDrEvent(data);
  }, [applyDrEvent]);

  useEffect(() => {
    if (!currentSession?.id || currentSession?.project_id !== 'deep_research_v2') return;
    let cancelled = false;
    const loadHistory = async () => {
      isReplayingRef.current = true;
      queuedEventsRef.current = [];
      try {
        const response = await fetch(`/api/sessions/${currentSession.id}/dr_events`);
        if (!response.ok) return;
        const data = await response.json();
        if (cancelled || !Array.isArray(data.events)) return;
        data.events.forEach((event: Record<string, unknown>) => applyDrEvent(event));
      } catch (err) {
        // Ignore history load failures to avoid blocking live streaming.
      } finally {
        if (cancelled) return;
        isReplayingRef.current = false;
        if (queuedEventsRef.current.length > 0) {
          const pending = [...queuedEventsRef.current];
          queuedEventsRef.current = [];
          pending
            .filter((event) => typeof event.event_id === 'number')
            .sort((a, b) => (a.event_id as number) - (b.event_id as number))
            .forEach((event) => applyDrEvent(event));
        }
      }
    };
    loadHistory();
    return () => {
      cancelled = true;
    };
  }, [currentSession?.id, currentSession?.project_id, applyDrEvent]);

  useEffect(() => {
    if (!registerEventHandler) return;
    const unregister = registerEventHandler('dr.', handleDrEvent);
    return () => unregister();
  }, [registerEventHandler, handleDrEvent]);

  const handleSend = useCallback(() => {
    if (!input.trim() || isLoading) return;
    sendMessage(input.trim());
    setInput('');
  }, [input, isLoading, sendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleLeftScroll = useCallback(() => {
    const atBottom = isNearBottom(leftScrollRef.current);
    setLeftAutoScroll(atBottom);
    if (atBottom) {
      setLeftHasNew(false);
    }
  }, [isNearBottom]);

  const handleRightScroll = useCallback(() => {
    const atBottom = isNearBottom(rightScrollRef.current);
    setRightAutoScroll(atBottom);
    if (atBottom) {
      setRightHasNew(false);
    }
  }, [isNearBottom]);

  const handleSelectFile = async (file: ArtifactFile) => {
    if (!currentSession?.id) return;
    setSelectedFile(file);
    setFileLoading(true);
    setFileContent(null);
    try {
      const path = file.relative_path || file.path;
      const response = await fetch('/api/files/read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: currentSession.id,
          path,
        }),
      });
      if (response.ok) {
        const data = await response.json();
        setFileContent(data.content || '');
      } else {
        setFileContent('Failed to load file.');
      }
    } catch (err) {
      setFileContent('Failed to load file.');
    } finally {
      setFileLoading(false);
    }
  };

  const isRunning = currentSession?.status === 'running';

  return (
    <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Header */}
      <Box
        sx={{
          px: 3,
          py: 1.5,
          borderBottom: `1px solid ${alpha(theme.palette.divider, 0.5)}`,
          display: 'flex',
          alignItems: 'center',
          gap: 2,
          backgroundColor: alpha(theme.palette.background.paper, 0.6),
          backdropFilter: 'blur(12px)',
          flexWrap: 'wrap',
          position: 'sticky',
          top: 0,
          zIndex: 2,
        }}
      >
        <Chip
          label="Deep Research"
          size="small"
          sx={{
            backgroundColor: alpha(theme.palette.primary.main, 0.1),
            color: theme.palette.primary.main,
            fontWeight: 600,
            borderRadius: '8px',
          }}
        />
        <Chip
          label={currentSession?.status || 'idle'}
          size="small"
          color={isRunning ? 'info' : currentSession?.status === 'completed' ? 'success' : currentSession?.status === 'error' ? 'error' : 'default'}
          sx={{ textTransform: 'capitalize', borderRadius: '8px' }}
        />
        <Chip
          icon={<DescriptionIcon sx={{ fontSize: 16 }} />}
          label={artifacts.length > 0 ? `Artifacts (${artifacts.length})` : 'Artifacts'}
          size="small"
          onClick={() => {
            setRightTab(1);
            setRightPanelOpen(true);
          }}
          sx={{
            cursor: 'pointer',
            backgroundColor: alpha(theme.palette.warning.main, 0.1),
            color: theme.palette.warning.main,
            '&:hover': {
              backgroundColor: alpha(theme.palette.warning.main, 0.2),
            },
          }}
        />
        {isRunning && (
          <Chip
            icon={<StopIcon sx={{ fontSize: 16 }} />}
            label="Stop"
            size="small"
            onClick={stopAgent}
            color="error"
            sx={{ cursor: 'pointer' }}
          />
        )}
      </Box>

      <Box sx={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        {/* Left: conversation */}
        <Box
          sx={{
            flex: 1,
            display: 'grid',
            gridTemplateRows: '1fr auto',
            overflow: 'hidden',
            minHeight: 0,
          }}
        >
          <Box
            sx={{
              overflowY: 'auto',
              px: 2,
              py: 2,
              display: 'flex',
              flexDirection: 'column',
              gap: 1,
              minHeight: 0,
              position: 'relative',
              '&::-webkit-scrollbar': { width: 6 },
              '&::-webkit-scrollbar-thumb': {
                backgroundColor: alpha(theme.palette.primary.main, 0.2),
                borderRadius: 3,
              },
            }}
            ref={leftScrollRef}
            onScroll={handleLeftScroll}
          >
            {chatMessages.map((message) => (
              <React.Fragment key={message.id}>
                <MessageBubble message={message} />
                {message.role === 'assistant' && (
                  <Box sx={{ px: 2 }}>
                    {(toolCallsByMessage[message.id] || []).map((callId) => {
                      const tool = toolCalls[callId];
                      if (!tool) return null;
                      if (tool.category === 'subagent') {
                        return null;
                      }
                      return (
                        <React.Fragment key={callId}>
                          <ToolCallCard tool={tool} />
                          {tool.toolName.includes('todo_list---') && (todoByCallId[callId] || todos).length > 0 && (
                            <TodoCard todos={todoByCallId[callId] || todos} compact />
                          )}
                        </React.Fragment>
                      );
                    })}

                    {(subagentCardsByMessage[message.id] || []).map((cardId) => {
                      const card = subagentCards[cardId];
                      if (!card) return null;
                      return (
                        <SubAgentCard
                          key={cardId}
                          card={card}
                          onClick={() => {
                            setActiveCardId(card.cardId);
                            setRightTab(0);
                            setRightPanelOpen(true);
                          }}
                        />
                      );
                    })}
                  </Box>
                )}
              </React.Fragment>
            ))}

            {orphanSubagentIds.length > 0 && (
              <Box sx={{ px: 2 }}>
                {orphanSubagentIds.map((cardId) => {
                  const card = subagentCards[cardId];
                  if (!card) return null;
                  return (
                    <SubAgentCard
                      key={cardId}
                      card={card}
                      onClick={() => {
                        setActiveCardId(card.cardId);
                        setRightTab(0);
                        setRightPanelOpen(true);
                      }}
                    />
                  );
                })}
              </Box>
            )}

            {reportFile && (
              <Box sx={{ px: 2 }}>
                <Paper
                  elevation={0}
                  sx={{
                    width: '100%',
                    p: 2,
                    borderRadius: 3,
                    border: `1px solid ${alpha(theme.palette.primary.main, 0.22)}`,
                    background: `linear-gradient(180deg, ${alpha(theme.palette.primary.main, 0.05)} 0%, ${alpha(theme.palette.background.paper, 0.95)} 100%)`,
                    boxShadow: `0 10px 24px ${alpha(theme.palette.common.black, 0.08)}`,
                  }}
                >
                  <Box sx={{ maxWidth: 920, mx: 'auto' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                        Final Report
                      </Typography>
                      <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                        {reportFile.relative_path || reportFile.path}
                      </Typography>
                      <Box sx={{ flex: 1 }} />
                      <Tooltip title="Open in Artifacts">
                        <IconButton size="small" onClick={handleOpenReport}>
                          <OpenInNewIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Download markdown">
                        <IconButton size="small" onClick={handleDownloadReport}>
                          <DownloadIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                    <Box
                      sx={{
                        p: 1.75,
                        borderRadius: 2,
                        border: `1px solid ${alpha(theme.palette.divider, 0.2)}`,
                        backgroundColor: alpha(theme.palette.background.default, 0.5),
                      }}
                    >
                      {reportLoading ? (
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <CircularProgress size={14} />
                          <Typography variant="caption" color="text.secondary">
                            Loading report...
                          </Typography>
                        </Box>
                      ) : reportPreview ? (
                        <MessageContent content={reportPreview} />
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          Report generated. Open to view full content.
                        </Typography>
                      )}
                    </Box>
                  </Box>
                </Paper>
              </Box>
            )}

            {leftHasNew && (
              <Box
                sx={{
                  position: 'sticky',
                  bottom: 16,
                  display: 'flex',
                  justifyContent: 'center',
                  zIndex: 1,
                  pointerEvents: 'none',
                }}
              >
                <Chip
                  label="Jump to latest"
                  size="small"
                  onClick={scrollLeftToBottom}
                  sx={{
                    pointerEvents: 'auto',
                    backgroundColor: alpha(theme.palette.background.paper, 0.9),
                    border: `1px solid ${alpha(theme.palette.primary.main, 0.3)}`,
                    boxShadow: `0 6px 16px ${alpha(theme.palette.common.black, 0.12)}`,
                  }}
                />
              </Box>
            )}

            <div ref={messagesEndRef} />
          </Box>

          {/* Input */}
          <Box
            sx={{
              p: 2,
              borderTop: `1px solid ${theme.palette.divider}`,
              backgroundColor: alpha(theme.palette.background.paper, 0.5),
            }}
          >
            <TextField
              fullWidth
              multiline
              maxRows={4}
              placeholder="Type your message..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
              InputProps={{
                endAdornment: (
                  <InputAdornment position="end">
                    {isRunning ? (
                      <IconButton onClick={stopAgent} color="error">
                        <StopIcon />
                      </IconButton>
                    ) : (
                      <IconButton
                        onClick={handleSend}
                        disabled={!input.trim() || isLoading}
                        sx={{
                          backgroundColor: input.trim()
                            ? theme.palette.primary.main
                            : 'transparent',
                          color: input.trim()
                            ? theme.palette.primary.contrastText
                            : theme.palette.text.secondary,
                          '&:hover': {
                            backgroundColor: input.trim()
                              ? theme.palette.primary.dark
                              : 'transparent',
                          },
                        }}
                      >
                        <SendIcon />
                      </IconButton>
                    )}
                  </InputAdornment>
                ),
              }}
            />
          </Box>
        </Box>

        {rightPanelOpen && (
          <>
            <Divider orientation="vertical" flexItem />

            {/* Right panel */}
            <Box
              sx={{
                flex: '0 0 35%',
                width: '35%',
                minWidth: 320,
                maxWidth: 520,
                display: 'flex',
                flexDirection: 'column',
                borderLeft: `1px solid ${alpha(theme.palette.divider, 0.4)}`,
                backgroundColor: alpha(theme.palette.background.paper, 0.6),
                overflow: 'hidden',
              }}
            >
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  px: 2,
                  py: 1,
                  borderBottom: `1px solid ${theme.palette.divider}`,
                }}
              >
                <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                  Detail
                </Typography>
                <IconButton size="small" onClick={() => setRightPanelOpen(false)}>
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Box>

              <Tabs
                value={rightTab}
                onChange={(_, v) => setRightTab(v)}
                sx={{ borderBottom: `1px solid ${theme.palette.divider}` }}
              >
                <Tab label="Sub Agent" />
                <Tab label="Artifacts" />
              </Tabs>

              <Box sx={{ flex: 1, overflow: 'hidden' }}>
            {rightTab === 0 && (
              <Box
                sx={{ p: 2.5, height: '100%', overflowY: 'auto', position: 'relative' }}
                ref={rightScrollRef}
                onScroll={handleRightScroll}
              >
                {activeCardId ? (
                  <>
                    <Paper
                      elevation={0}
                      sx={{
                        p: 2,
                        borderRadius: 3,
                        border: `1px solid ${alpha(theme.palette.divider, 0.3)}`,
                        backgroundColor: alpha(theme.palette.background.paper, 0.8),
                        mb: 2,
                      }}
                    >
                      <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 0.5 }}>
                        {subagentCards[activeCardId]?.title || 'Sub Agent'}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {subagentCards[activeCardId]?.status === 'running' ? 'Working...' : 'Completed'}
                      </Typography>
                    </Paper>
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                      {visibleActiveMessages.map((msg) => {
                        const toolIds = (subagentToolCallsByMessage[activeCardId]?.[msg.id] || []);
                        return (
                          <Box key={msg.id}>
                            <Box sx={{ display: 'flex', gap: 1.5 }}>
                              <Box
                                sx={{
                                  width: 10,
                                  minWidth: 10,
                                  height: 10,
                                  borderRadius: '50%',
                                  mt: 0.8,
                                  backgroundColor: msg.role === 'assistant'
                                    ? theme.palette.primary.main
                                    : theme.palette.grey[500],
                                }}
                              />
                              <Paper
                                elevation={0}
                                sx={{
                                  p: 1.5,
                                  borderRadius: 2,
                                  flex: 1,
                                  backgroundColor: msg.role === 'assistant'
                                    ? alpha(theme.palette.primary.main, 0.06)
                                    : alpha(theme.palette.background.default, 0.8),
                                }}
                              >
                                <Typography
                                  variant="caption"
                                  color="text.secondary"
                                  sx={{ textTransform: 'uppercase', letterSpacing: '0.05em' }}
                                >
                                  {msg.role}
                                </Typography>
                                <Typography
                                  variant="body2"
                                  sx={{ whiteSpace: 'pre-wrap', fontSize: '0.82rem', lineHeight: 1.6 }}
                                >
                                  {msg.role === 'assistant'
                                    ? msg.content.replace(/[\r\n]+$/, '')
                                    : msg.content}
                                </Typography>
                              </Paper>
                            </Box>
                            {toolIds.length > 0 && (
                              <Box sx={{ ml: 3.5, mt: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
                                {toolIds.map((callId) => {
                                  const tool = subagentToolCalls[activeCardId]?.[callId];
                                  if (!tool) return null;
                                  return <ToolCallDetailCard key={callId} tool={tool} />;
                                })}
                              </Box>
                            )}
                          </Box>
                        );
                      })}
                      {Object.values(subagentToolCalls[activeCardId] || {})
                        .filter(tool => !tool.sourceMessageId)
                        .map((tool) => (
                          <ToolCallDetailCard key={tool.callId} tool={tool} />
                        ))}
                      {subagentCards[activeCardId]?.status === 'running' && (
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <CircularProgress size={14} />
                          <Typography variant="caption" color="text.secondary">
                            Streaming...
                          </Typography>
                        </Box>
                      )}
                      {visibleActiveMessages.length === 0 && (
                        <Typography variant="caption" color="text.secondary">
                          Waiting for sub-agent output...
                        </Typography>
                      )}
                      {rightHasNew && (
                        <Box
                          sx={{
                            position: 'sticky',
                            bottom: 12,
                            display: 'flex',
                            justifyContent: 'center',
                            zIndex: 1,
                            pointerEvents: 'none',
                          }}
                        >
                          <Chip
                            label="Jump to latest"
                            size="small"
                            onClick={scrollRightToBottom}
                            sx={{
                              pointerEvents: 'auto',
                              backgroundColor: alpha(theme.palette.background.paper, 0.9),
                              border: `1px solid ${alpha(theme.palette.primary.main, 0.3)}`,
                              boxShadow: `0 6px 16px ${alpha(theme.palette.common.black, 0.12)}`,
                            }}
                          />
                        </Box>
                      )}
                      <div ref={detailEndRef} />
                    </Box>
                  </>
                ) : (
                  <Typography color="text.secondary">Select a sub-agent card to view details.</Typography>
                )}
              </Box>
            )}

            {rightTab === 1 && (
              <Box sx={{ display: 'flex', height: '100%' }}>
                <Box sx={{ width: 240, borderRight: `1px solid ${theme.palette.divider}`, overflowY: 'auto' }}>
                  {artifacts.length === 0 ? (
                    <Box sx={{ p: 2 }}>
                      <Typography color="text.secondary">No artifacts yet.</Typography>
                    </Box>
                  ) : (
                    <List dense>
                      {artifacts.map((file) => {
                        const label = file.relative_path || file.path;
                        return (
                          <ListItemButton
                            key={label}
                            selected={selectedFile?.path === file.path}
                            onClick={() => handleSelectFile(file)}
                          >
                            <ListItemIcon>
                              <FileIcon fontSize="small" />
                            </ListItemIcon>
                            <ListItemText
                              primaryTypographyProps={{ fontSize: '0.8rem' }}
                              primary={label}
                            />
                          </ListItemButton>
                        );
                      })}
                    </List>
                  )}
                </Box>
                <Box sx={{ flex: 1, overflow: 'auto' }}>
                  {fileLoading ? (
                    <Box sx={{ p: 2 }}>
                      <CircularProgress size={24} />
                    </Box>
                  ) : fileContent ? (
                    <Box component="pre" sx={{ p: 2, whiteSpace: 'pre-wrap', m: 0, fontSize: '0.8rem', lineHeight: 1.6 }}>
                      {fileContent}
                    </Box>
                  ) : (
                    <Box sx={{ p: 2 }}>
                      <Typography color="text.secondary">Select a file to view.</Typography>
                    </Box>
                  )}
                </Box>
              </Box>
            )}
              </Box>
            </Box>
          </>
        )}
      </Box>
    </Box>
  );
};

const MessageBubble: React.FC<{ message: DrChatMessage }> = ({ message }) => {
  const theme = useTheme();
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';
  const content = message.role === 'assistant'
    ? message.content.replace(/[\r\n]+$/, '')
    : message.content;

  if (!content?.trim()) return null;

  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        px: 2,
      }}
    >
      <Paper
        elevation={0}
        sx={{
          maxWidth: '75%',
          px: 2,
          py: 1.25,
          borderRadius: '20px',
          backgroundColor: isUser
            ? alpha(theme.palette.grey[400], 0.2)
            : isSystem
            ? alpha(theme.palette.warning.main, 0.1)
            : alpha(theme.palette.background.paper, 0.9),
          border: `1px solid ${alpha(theme.palette.divider, isUser ? 0.2 : 0.12)}`,
          boxShadow: isUser ? 'none' : `0 6px 16px ${alpha(theme.palette.common.black, 0.06)}`,
        }}
      >
        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
          {content}
        </Typography>
      </Paper>
    </Box>
  );
};

const ToolCallCard: React.FC<{ tool: ToolCallState }> = ({ tool }) => {
  const theme = useTheme();
  const [open, setOpen] = useState(false);
  const displayName = tool.toolName.split('---').pop() || tool.toolName;
  const hasArgs = tool.args !== undefined && tool.args !== null && JSON.stringify(tool.args) !== '{}';
  const canToggle = hasArgs || Boolean(tool.result);
  const argsText = typeof tool.args === 'string' ? tool.args : JSON.stringify(tool.args ?? {}, null, 2);
  const argsPreview = hasArgs ? argsText.split('\n')[0] : '';
  const resultPreview = tool.result ? tool.result.split('\n')[0] : '';

  return (
    <Paper
      elevation={0}
      sx={{
        mb: 1,
        border: `1px solid ${alpha(theme.palette.divider, 0.3)}`,
        borderRadius: '12px',
        overflow: 'hidden',
        backgroundColor: alpha(theme.palette.background.paper, 0.9),
        transition: 'border-color 0.2s ease',
        '&:hover': {
          borderColor: alpha(theme.palette.primary.main, 0.35),
        },
      }}
    >
      <Box
        onClick={() => canToggle && setOpen(!open)}
        sx={{
          px: 1.5,
          py: 1,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          cursor: canToggle ? 'pointer' : 'default',
        }}
      >
        <BuildIcon fontSize="small" />
        <Chip label={displayName} size="small" />
        {tool.status === 'running' && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <CircularProgress size={12} />
            <Typography variant="caption" color="text.secondary">
              running
            </Typography>
          </Box>
        )}
        <Box sx={{ flex: 1 }} />
        {canToggle && (
          <Typography variant="caption" color="text.secondary">
            {open ? '▲' : '▼'}
          </Typography>
        )}
      </Box>
      <Collapse in={open || tool.status === 'running'}>
        <Box sx={{ px: 1.5, pb: 1.5 }}>
          {hasArgs && (
            <>
              <Typography variant="caption" color="text.secondary">Input</Typography>
              <Box component="pre" sx={{ m: 0, fontSize: '0.75rem', whiteSpace: 'pre-wrap' }}>
                {argsText}
              </Box>
            </>
          )}
          {tool.result && (
            <>
              <Divider sx={{ my: 1 }} />
              <Typography variant="caption" color="text.secondary">Output</Typography>
              <Box component="pre" sx={{ m: 0, fontSize: '0.75rem', whiteSpace: 'pre-wrap' }}>
                {tool.result}
              </Box>
            </>
          )}
        </Box>
      </Collapse>
      {!open && tool.status !== 'running' && (argsPreview || resultPreview) && (
        <Box sx={{ px: 1.5, pb: 1 }}>
          {argsPreview && (
            <Typography variant="caption" color="text.secondary">
              Input: {argsPreview}
            </Typography>
          )}
          {resultPreview && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
              Output: {resultPreview}
            </Typography>
          )}
        </Box>
      )}
    </Paper>
  );
};

const SubAgentCard: React.FC<{ card: SubagentCardState; onClick: () => void }> = ({ card, onClick }) => {
  const theme = useTheme();
  const isSearcher = card.toolName.includes('searcher');
  const isReporter = card.toolName.includes('reporter');
  const previewLines = card.streaming
    ? card.streaming.split('\n').filter(Boolean).slice(-3).join('\n')
    : '';

  return (
    <Paper
      onClick={onClick}
      sx={{
        p: 1.5,
        mb: 1,
        cursor: 'pointer',
        border: `1px solid ${alpha(
          isSearcher ? theme.palette.info.main : isReporter ? theme.palette.success.main : theme.palette.primary.main,
          0.3
        )}`,
        backgroundColor: alpha(
          isSearcher ? theme.palette.info.main : isReporter ? theme.palette.success.main : theme.palette.primary.main,
          0.04
        ),
        transition: 'all 0.2s ease',
        '&:hover': {
          boxShadow: `0 6px 16px ${alpha(theme.palette.common.black, 0.08)}`,
          transform: 'translateY(-1px)',
        },
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        {isSearcher ? <SearchIcon color="info" /> : isReporter ? <ArticleIcon color="success" /> : <SmartToyIcon color="primary" />}
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {card.title}
        </Typography>
        {card.status === 'running' && <CircularProgress size={14} sx={{ ml: 'auto' }} />}
        {card.status === 'completed' && <CheckCircleIcon color="success" fontSize="small" sx={{ ml: 'auto' }} />}
      </Box>
      <Box sx={{ mt: 1 }}>
        {previewLines ? (
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{
              fontSize: '0.8rem',
              lineHeight: 1.5,
              whiteSpace: 'pre-wrap',
              maxHeight: 66,
              overflow: 'hidden',
              display: '-webkit-box',
              WebkitLineClamp: 3,
              WebkitBoxOrient: 'vertical',
            }}
          >
            {previewLines}
          </Typography>
        ) : (
          <Typography variant="caption" color="text.secondary">
            正在处理<LoadingDots />
          </Typography>
        )}
      </Box>
      {card.summary && card.status === 'completed' && (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
          {card.summary}
        </Typography>
      )}
    </Paper>
  );
};

const ToolCallDetailCard: React.FC<{ tool: ToolCallState }> = ({ tool }) => {
  const theme = useTheme();
  const [open, setOpen] = useState(false);
  const displayName = tool.toolName.split('---').pop() || tool.toolName;
  const argsText = typeof tool.args === 'string' ? tool.args : JSON.stringify(tool.args ?? {}, null, 2);

  return (
    <Paper
      elevation={0}
      sx={{
        borderRadius: 2,
        border: `1px solid ${alpha(theme.palette.divider, 0.3)}`,
        overflow: 'hidden',
        backgroundColor: alpha(theme.palette.background.paper, 0.9),
      }}
    >
      <Box
        onClick={() => setOpen(!open)}
        sx={{
          px: 1.5,
          py: 1,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          cursor: 'pointer',
        }}
      >
        <BuildIcon fontSize="small" />
        <Typography variant="caption" sx={{ fontWeight: 600 }}>
          {displayName}
        </Typography>
        {tool.status === 'running' && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, ml: 1 }}>
            <CircularProgress size={10} />
            <Typography variant="caption" color="text.secondary">
              running
            </Typography>
          </Box>
        )}
        <Box sx={{ flex: 1 }} />
        <ExpandMoreIcon
          sx={{
            fontSize: 18,
            transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s ease',
          }}
        />
      </Box>
      <Collapse in={open}>
        <Box sx={{ px: 1.5, pb: 1.5 }}>
          <Typography variant="caption" color="text.secondary">
            Args
          </Typography>
          <Box component="pre" sx={{ m: 0, fontSize: '0.75rem', whiteSpace: 'pre-wrap' }}>
            {argsText}
          </Box>
          {tool.result && (
            <>
              <Divider sx={{ my: 1 }} />
              <Typography variant="caption" color="text.secondary">
                Result
              </Typography>
              <Box component="pre" sx={{ m: 0, fontSize: '0.75rem', whiteSpace: 'pre-wrap' }}>
                {tool.result}
              </Box>
            </>
          )}
        </Box>
      </Collapse>
    </Paper>
  );
};

const TodoCard: React.FC<{ todos: TodoItem[]; compact?: boolean }> = ({ todos, compact = false }) => {
  const theme = useTheme();
  return (
    <Paper
      elevation={0}
      sx={{
        p: compact ? 1.5 : 2,
        mb: 1.5,
        borderRadius: 2,
        border: `1px solid ${alpha(theme.palette.divider, 0.2)}`,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        <ListAltIcon fontSize="small" color="primary" />
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          Research Plan
        </Typography>
      </Box>
      <List dense>
        {todos.map(todo => (
          <ListItem key={todo.id} sx={{ py: 0.25 }}>
            <ListItemIcon sx={{ minWidth: 28 }}>
              {todo.status === 'completed' ? (
                <CheckCircleIcon color="success" fontSize="small" />
              ) : (
                <Box
                  sx={{
                    width: 14,
                    height: 14,
                    borderRadius: 3,
                    border: `1px solid ${alpha(theme.palette.text.secondary, 0.6)}`,
                    backgroundColor: todo.status === 'in_progress'
                      ? alpha(theme.palette.primary.main, 0.2)
                      : 'transparent',
                  }}
                />
              )}
            </ListItemIcon>
            <ListItemText
              primary={todo.content}
              primaryTypographyProps={{ fontSize: compact ? '0.78rem' : '0.85rem', lineHeight: 1.4 }}
            />
          </ListItem>
        ))}
      </List>
    </Paper>
  );
};

const LoadingDots: React.FC = () => (
  <Box component="span" sx={{ display: 'inline-flex', ml: 0.5, gap: 0.3 }}>
    {[0, 1, 2].map((i) => (
      <Box
        key={i}
        component="span"
        sx={{
          width: 4,
          height: 4,
          borderRadius: '50%',
          backgroundColor: 'currentColor',
          opacity: 0.4,
          animation: 'dotPulse 1s infinite',
          animationDelay: `${i * 0.2}s`,
          '@keyframes dotPulse': {
            '0%, 100%': { opacity: 0.3, transform: 'translateY(0)' },
            '50%': { opacity: 0.9, transform: 'translateY(-2px)' },
          },
        }}
      />
    ))}
  </Box>
);


export default DeepResearchView;
