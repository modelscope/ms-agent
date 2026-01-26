import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Box,
  TextField,
  IconButton,
  Typography,
  Paper,
  InputAdornment,
  useTheme,
  alpha,
  Chip,
  Divider,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  CircularProgress,
} from '@mui/material';
import {
  Send as SendIcon,
  Stop as StopIcon,
  PlayArrow as RunningIcon,
  InsertDriveFile as FileIcon,
  Code as CodeIcon,
  Description as DocIcon,
  Image as ImageIcon,
  Close as CloseIcon,
  ContentCopy as CopyIcon,
  Folder as FolderIcon,
  FolderOpen as FolderOpenIcon,
  ChevronRight as ChevronRightIcon,
  ExpandMore as ExpandMoreIcon,
  CheckCircle as CheckCircleIcon,
  AccountTree as WorkflowIcon,
} from '@mui/icons-material';
import { motion, AnimatePresence } from 'framer-motion';
import { useSession, Message } from '../context/SessionContext';
import WorkflowProgress from './WorkflowProgress';
import FileProgress from './FileProgress';
import LogViewer from './LogViewer';
import MessageContent from './MessageContent';

interface ConversationViewProps {
  showLogs: boolean;
}

const ConversationView: React.FC<ConversationViewProps> = ({ showLogs }) => {
  const theme = useTheme();
  const {
    currentSession,
    messages,
    streamingContent,
    isStreaming,
    isLoading,
    sendMessage,
    stopAgent,
    logs,
  } = useSession();

  const [input, setInput] = useState('');
  const [outputFilesOpen, setOutputFilesOpen] = useState(false);
  const [workflowOpen, setWorkflowOpen] = useState(false);
  const [workflowData, setWorkflowData] = useState<Record<string, any> | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [outputTree, setOutputTree] = useState<any>({folders: {}, files: []});
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSend = useCallback(() => {
    if (!input.trim() || isLoading) return;
    sendMessage(input);
    setInput('');
  }, [input, isLoading, sendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const loadOutputFiles = async () => {
    try {
      const response = await fetch('/api/files/list');
      if (response.ok) {
        const data = await response.json();
        setOutputTree(data.tree || {folders: {}, files: []});
        // Expand root level by default
        setExpandedFolders(new Set(['']));
      }
    } catch (err) {
      console.error('Failed to load output files:', err);
    }
  };

  const toggleFolder = (folder: string) => {
    setExpandedFolders(prev => {
      const next = new Set(prev);
      if (next.has(folder)) {
        next.delete(folder);
      } else {
        next.add(folder);
      }
      return next;
    });
  };

  const handleOpenOutputFiles = () => {
    loadOutputFiles();
    setOutputFilesOpen(true);
    setSelectedFile(null);
    setFileContent(null);
  };

  const handleViewFile = async (path: string) => {
    setSelectedFile(path);
    setFileLoading(true);
    try {
      const response = await fetch('/api/files/read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      if (response.ok) {
        const data = await response.json();
        setFileContent(data.content);
      }
    } catch (err) {
      console.error('Failed to load file:', err);
    } finally {
      setFileLoading(false);
    }
  };

  const loadWorkflow = async () => {
    if (!currentSession?.project_id) return;

    setWorkflowLoading(true);
    try {
      const response = await fetch(`/api/projects/${currentSession.project_id}/workflow`);
      if (response.ok) {
        const data = await response.json();
        setWorkflowData(data.workflow || {});
      }
    } catch (err) {
      console.error('Failed to load workflow:', err);
    } finally {
      setWorkflowLoading(false);
    }
  };

  const handleOpenWorkflow = () => {
    loadWorkflow();
    setWorkflowOpen(true);
  };

  return (
    <Box
      component={motion.div}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      sx={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
      }}
    >
      {/* Session Header */}
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
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Chip
            label={currentSession?.project_name?.replace(/_/g, ' ')}
            size="small"
            sx={{
              backgroundColor: alpha(theme.palette.primary.main, 0.1),
              color: theme.palette.primary.main,
              fontWeight: 600,
              textTransform: 'capitalize',
              borderRadius: '8px',
            }}
          />
          {currentSession?.project_id && (
            <Tooltip title="View workflow">
              <Chip
                icon={<WorkflowIcon sx={{ fontSize: 16 }} />}
                label="Workflow"
                size="small"
                onClick={handleOpenWorkflow}
                sx={{
                  backgroundColor: alpha(theme.palette.secondary.main, 0.1),
                  color: theme.palette.secondary.main,
                  cursor: 'pointer',
                  '&:hover': {
                    backgroundColor: alpha(theme.palette.secondary.main, 0.2),
                  },
                }}
              />
            </Tooltip>
          )}
          <Chip
            icon={currentSession?.status === 'running' ? <RunningIcon sx={{ fontSize: 14 }} /> : undefined}
            label={currentSession?.status}
            size="small"
            color={
              currentSession?.status === 'running' ? 'info' :
              currentSession?.status === 'completed' ? 'success' :
              currentSession?.status === 'error' ? 'error' : 'default'
            }
            sx={{
              textTransform: 'capitalize',
              borderRadius: '8px',
              '& .MuiChip-icon': { ml: 0.5 },
            }}
          />
        </Box>

        {/* Workflow Progress */}
        {currentSession?.workflow_progress && (
          <Box sx={{ flex: 1, minWidth: 200 }}>
            <WorkflowProgress progress={currentSession.workflow_progress} />
          </Box>
        )}

        {/* File Progress */}
        {currentSession?.file_progress && (
          <FileProgress progress={currentSession.file_progress} />
        )}

        {/* View Output Files Button */}
        <Tooltip title="View generated files">
          <Chip
            icon={<FolderIcon sx={{ fontSize: 16 }} />}
            label="Output Files"
            size="small"
            onClick={handleOpenOutputFiles}
            sx={{
              backgroundColor: alpha(theme.palette.warning.main, 0.1),
              color: theme.palette.warning.main,
              cursor: 'pointer',
              '&:hover': {
                backgroundColor: alpha(theme.palette.warning.main, 0.2),
              },
            }}
          />
        </Tooltip>
      </Box>

      {/* Output Files Dialog */}
      <Dialog
        open={outputFilesOpen}
        onClose={() => setOutputFilesOpen(false)}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: { backgroundColor: theme.palette.background.paper, minHeight: '60vh' }
        }}
      >
        <DialogTitle sx={{ borderBottom: `1px solid ${theme.palette.divider}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <FolderIcon color="warning" />
            <Typography variant="h6">Output Files</Typography>
          </Box>
          <IconButton size="small" onClick={() => setOutputFilesOpen(false)}>
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent sx={{ p: 0, display: 'flex' }}>
          {/* File Tree */}
          <Box sx={{ width: 280, borderRight: `1px solid ${theme.palette.divider}`, overflowY: 'auto', maxHeight: '60vh' }}>
            <FileTreeView
              tree={outputTree}
              path=""
              expandedFolders={expandedFolders}
              toggleFolder={toggleFolder}
              selectedFile={selectedFile}
              onSelectFile={handleViewFile}
            />
          </Box>
          {/* File Content */}
          <Box sx={{ flex: 1, overflow: 'auto', p: 0 }}>
            {fileLoading ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
                <CircularProgress size={32} />
              </Box>
            ) : fileContent ? (
              <Box
                component="pre"
                sx={{
                  m: 0,
                  p: 2,
                  fontFamily: 'monospace',
                  fontSize: '0.85rem',
                  lineHeight: 1.6,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                <code>{fileContent}</code>
              </Box>
            ) : (
              <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
                <Typography color="text.secondary">Select a file to view</Typography>
              </Box>
            )}
          </Box>
        </DialogContent>
      </Dialog>

      {/* Workflow Dialog */}
      <Dialog
        open={workflowOpen}
        onClose={() => setWorkflowOpen(false)}
        maxWidth={false}
        fullWidth
        PaperProps={{
          sx: {
            backgroundColor: theme.palette.background.paper,
            maxWidth: '95vw',
            width: '95vw',
            height: '85vh',
            display: 'flex',
            flexDirection: 'column',
          }
        }}
      >
        <DialogTitle sx={{ borderBottom: `1px solid ${theme.palette.divider}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <WorkflowIcon color="secondary" />
            <Typography variant="h6">Workflow</Typography>
          </Box>
          <IconButton size="small" onClick={() => setWorkflowOpen(false)}>
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent sx={{ p: 2, flex: 1, overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {workflowLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 8 }}>
              <CircularProgress size={32} />
            </Box>
          ) : workflowData ? (
            <WorkflowView workflow={workflowData} currentStep={currentSession?.current_step} />
          ) : (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 8 }}>
              <Typography color="text.secondary">No workflow data available</Typography>
            </Box>
          )}
        </DialogContent>
      </Dialog>

      {/* Main Content Area */}
      <Box sx={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Messages Area */}
        <Box
          sx={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          {/* Messages List */}
          <Box
            sx={{
              flex: 1,
              overflowY: 'auto',
              px: 2,
              py: 2,
              display: 'flex',
              flexDirection: 'column',
              gap: 1,
              '&::-webkit-scrollbar': {
                width: 6,
              },
              '&::-webkit-scrollbar-track': {
                backgroundColor: 'transparent',
              },
              '&::-webkit-scrollbar-thumb': {
                backgroundColor: alpha(theme.palette.primary.main, 0.2),
                borderRadius: 3,
              },
            }}
          >
            <AnimatePresence>
              {messages.map((message) => (
                <MessageBubble
                  key={message.id}
                  message={message}
                />
              ))}

              {/* Streaming Content */}
              {isStreaming && streamingContent && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                >
                  <MessageBubble
                    message={{
                      id: 'streaming',
                      role: 'assistant',
                      content: streamingContent,
                      type: 'text',
                      timestamp: new Date().toISOString(),
                    }}
                    isStreaming
                  />
                </motion.div>
              )}

              {/* Loading Indicator - Shows current step in progress */}
              {isLoading && !isStreaming && messages.length > 0 && (() => {
                // Find current running step (step_start without corresponding step_complete)
                const runningSteps = messages.filter(m => m.type === 'step_start');
                const completedStepsSet = new Set(
                  messages.filter(m => m.type === 'step_complete').map(m => m.content)
                );

                // Find the last step_start that hasn't been completed yet
                const currentRunningStep = runningSteps
                  .slice()
                  .reverse()
                  .find(step => !completedStepsSet.has(step.content));

                const currentStepName = currentRunningStep?.content?.replace(/_/g, ' ') || null;

                if (!currentStepName) {
                  return null; // No step in progress, don't show indicator
                }

                return (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                  >
                    <Box
                      sx={{
                        display: 'flex',
                        alignItems: 'flex-start',
                        justifyContent: 'flex-start',
                        mb: 1.5,
                        px: 2,
                      }}
                    >
                      <Paper
                        elevation={0}
                        sx={{
                          px: 2,
                          py: 1.25,
                          borderRadius: '20px',
                          backgroundColor: theme.palette.background.paper,
                          border: 'none',
                          boxShadow: 'none',
                        }}
                      >
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Box sx={{ display: 'flex', gap: 0.5 }}>
                            {[0, 1, 2].map((i) => (
                              <motion.div
                                key={i}
                                animate={{
                                  y: [0, -4, 0],
                                  opacity: [0.4, 1, 0.4],
                                }}
                                transition={{
                                  duration: 0.8,
                                  repeat: Infinity,
                                  delay: i * 0.15,
                                }}
                              >
                                <Box
                                  sx={{
                                    width: 6,
                                    height: 6,
                                    borderRadius: '50%',
                                    backgroundColor: theme.palette.primary.main,
                                  }}
                                />
                              </motion.div>
                            ))}
                          </Box>
                          <Typography variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                            <Box component="span" sx={{ textTransform: 'capitalize' }}>
                              {currentStepName}
                            </Box>
                            <Box component="span" sx={{ opacity: 0.7 }}> in progress...</Box>
                          </Typography>
                        </Box>
                      </Paper>
                    </Box>
                  </motion.div>
                );
              })()}
            </AnimatePresence>
            <div ref={messagesEndRef} />
          </Box>

          {/* Input Area */}
          <Box
            sx={{
              p: 2,
              borderTop: `1px solid ${theme.palette.divider}`,
              backgroundColor: alpha(theme.palette.background.paper, 0.5),
              backdropFilter: 'blur(10px)',
            }}
          >
            <TextField
              ref={inputRef}
              fullWidth
              multiline
              maxRows={4}
              placeholder="Type your message..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
              sx={{
                '& .MuiOutlinedInput-root': {
                  borderRadius: '12px',
                  backgroundColor: theme.palette.background.paper,
                },
              }}
              InputProps={{
                endAdornment: (
                  <InputAdornment position="end">
                    {isLoading ? (
                      <IconButton onClick={stopAgent} color="error">
                        <StopIcon />
                      </IconButton>
                    ) : (
                      <IconButton
                        onClick={handleSend}
                        disabled={!input.trim()}
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

        {/* Logs Panel */}
        {showLogs && (
          <>
            <Divider orientation="vertical" flexItem />
            <LogViewer logs={logs} />
          </>
        )}
      </Box>
    </Box>
  );
};

interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
}

const MessageBubble: React.FC<MessageBubbleProps> = ({ message, isStreaming }) => {
  const theme = useTheme();
  const isUser = message.role === 'user';
  const isError = message.type === 'error';
  const isSystem = message.role === 'system';
  const isFileOutput = message.type === 'file_output';
  const isStepStart = message.type === 'step_start';
  const isStepComplete = message.type === 'step_complete';
  const isToolCall = message.type === 'tool_call';

  // Skip empty messages
  if (!message.content?.trim()) return null;

  // Skip old format system messages
  if (isSystem && message.content.startsWith('Starting step:')) return null;
  if (isSystem && message.content.startsWith('Completed step:')) return null;

  // Hide step_start messages (they're shown in Loading Indicator instead)
  if (isStepStart) {
    return null;
  }

  // Convert step_complete to regular assistant message bubble with checkmark
  if (isStepComplete) {
    const stepName = message.content.replace(/_/g, ' ');
    const completedText = `${stepName.charAt(0).toUpperCase() + stepName.slice(1)} completed`;

    // Render as regular assistant message with checkmark icon
    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'flex-start',
            mb: 1.5,
            px: 2,
          }}
        >
          <Paper
            elevation={0}
            sx={{
              maxWidth: '75%',
              minWidth: 60,
              px: 2,
              py: 1.25,
              borderRadius: '20px',
              backgroundColor: theme.palette.background.paper,
              border: 'none',
              position: 'relative',
              boxShadow: 'none',
              display: 'flex',
              alignItems: 'flex-start',
              gap: 1.5,
            }}
          >
            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{
                type: 'spring',
                stiffness: 200,
                damping: 15,
                delay: 0.1
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                marginTop: '2px', // 微调对齐，与文字第一行对齐
              }}
            >
              <CheckCircleIcon
                sx={{
                  color: theme.palette.success.main,
                  fontSize: 22,
                  filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.1))',
                }}
              />
            </motion.div>
            <Box sx={{ flex: 1, lineHeight: 1.5 }}>
              <MessageContent content={completedText} />
            </Box>
          </Paper>
        </Box>
      </motion.div>
    );
  }

  // Tool call - skip display (we show step progress instead)
  if (isToolCall) {
    return null;
  }

  // File output display as compact chip
  if (isFileOutput) {
    return <FileOutputChip filename={message.content} />;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: isUser ? 'flex-end' : 'flex-start',
          mb: 1.5,
          px: 2,
        }}
      >
        {/* Message Content - 简洁的椭圆形对话框 */}
        <Paper
          elevation={0}
          sx={{
            maxWidth: '75%',
            minWidth: 60,
            px: 2,
            py: 1.25,
            borderRadius: '20px', // 完全椭圆形
            backgroundColor: isUser
              ? alpha(theme.palette.grey[400], 0.2) // 用户消息：浅灰色椭圆形
              : isError
              ? alpha(theme.palette.error.main, 0.08)
              : theme.palette.background.paper, // AI消息：白色背景
            border: 'none',
            position: 'relative',
            boxShadow: 'none',
          }}
        >
          <MessageContent content={message.content} />

          {isStreaming && (
            <Box
              component="span"
              sx={{
                display: 'inline-block',
                width: 2,
                height: 18,
                backgroundColor: theme.palette.primary.main,
                animation: 'blink 1s infinite',
                ml: 0.5,
                verticalAlign: 'middle',
                '@keyframes blink': {
                  '0%, 100%': { opacity: 1 },
                  '50%': { opacity: 0 },
                },
              }}
            />
          )}
        </Paper>
      </Box>
    </motion.div>
  );
};

export default ConversationView;

// Workflow View Component
interface WorkflowViewProps {
  workflow: Record<string, any>;
  currentStep?: string;
}

const WorkflowView: React.FC<WorkflowViewProps> = ({ workflow, currentStep }) => {
  const theme = useTheme();
  const containerRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // Node positions state
  const [nodePositions, setNodePositions] = useState<Record<string, { x: number; y: number }>>({});
  const [nodeHeights, setNodeHeights] = useState<Record<string, number>>({});
  const [draggingNode, setDraggingNode] = useState<string | null>(null);
  const [dragOffset, setDragOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  // Build workflow graph structure
  const buildWorkflowGraph = () => {
    const nodes: Array<{ id: string; name: string; config: string }> = [];
    const edges: Array<{ from: string; to: string }> = [];
    const hasIncoming = new Set<string>();

    Object.entries(workflow).forEach(([key, value]: [string, any]) => {
      nodes.push({
        id: key,
        name: key.replace(/_/g, ' '),
        config: value.agent_config || '',
      });

      if (value.next) {
        const nextSteps = Array.isArray(value.next) ? value.next : [value.next];
        nextSteps.forEach((next: string) => {
          hasIncoming.add(next);
          edges.push({ from: key, to: next });
        });
      }
    });

    return { nodes, edges };
  };

  const { nodes, edges } = buildWorkflowGraph();

  // Initialize node positions in a horizontal flow layout
  useEffect(() => {
    if (Object.keys(nodePositions).length === 0 && nodes.length > 0) {
      const positions: Record<string, { x: number; y: number }> = {};
      const visited = new Set<string>();

      // Find root nodes
      const hasIncoming = new Set<string>();
      edges.forEach(e => hasIncoming.add(e.to));
      const rootNodes = nodes.filter(n => !hasIncoming.has(n.id));

      // BFS to assign positions
      const queue: Array<{ id: string; level: number }> = [];
      rootNodes.forEach((node) => {
        queue.push({ id: node.id, level: 0 });
      });

      const levelNodes: Record<number, string[]> = {};

      while (queue.length > 0) {
        const { id, level } = queue.shift()!;
        if (visited.has(id)) continue;
        visited.add(id);

        if (!levelNodes[level]) levelNodes[level] = [];
        levelNodes[level].push(id);

        const outgoing = edges.filter(e => e.from === id);
        outgoing.forEach(edge => {
          if (!visited.has(edge.to)) {
            const nextLevel = level + 1;
            queue.push({ id: edge.to, level: nextLevel });
          }
        });
      }

      // Calculate positions
      const horizontalSpacing = 200;
      const verticalSpacing = 100;

      Object.entries(levelNodes).forEach(([levelStr, nodeIds]) => {
        const level = parseInt(levelStr);
        const startX = 100 + level * horizontalSpacing;
        const totalHeight = nodeIds.length * verticalSpacing;
        const startY = 100 - totalHeight / 2 + verticalSpacing / 2;

        nodeIds.forEach((nodeId, idx) => {
          positions[nodeId] = {
            x: startX,
            y: startY + idx * verticalSpacing,
          };
        });
      });

      setNodePositions(positions);
    }
  }, [nodes, edges, nodePositions]);

  // Handle drag start
  const handleMouseDown = (e: React.MouseEvent, nodeId: string) => {
    if (!containerRef.current) return;

    const rect = containerRef.current.getBoundingClientRect();
    const nodePos = nodePositions[nodeId];
    if (!nodePos) return;

    setDraggingNode(nodeId);
    setDragOffset({
      x: e.clientX - rect.left - nodePos.x,
      y: e.clientY - rect.top - nodePos.y,
    });
  };

  // Handle drag
  useEffect(() => {
    if (!draggingNode || !containerRef.current) return;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = containerRef.current!.getBoundingClientRect();
      const newX = e.clientX - rect.left - dragOffset.x;
      const newY = e.clientY - rect.top - dragOffset.y;

      setNodePositions(prev => ({
        ...prev,
        [draggingNode]: { x: newX, y: newY },
      }));
    };

    const handleMouseUp = () => {
      setDraggingNode(null);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [draggingNode, dragOffset]);

  // Update node heights when they mount or resize
  useEffect(() => {
    const updateHeights = () => {
      const heights: Record<string, number> = {};
      Object.entries(nodeRefs.current).forEach(([nodeId, ref]) => {
        if (ref) {
          heights[nodeId] = ref.offsetHeight;
        }
      });
      setNodeHeights(heights);
    };

    updateHeights();
    const resizeObserver = new ResizeObserver(updateHeights);
    Object.values(nodeRefs.current).forEach(ref => {
      if (ref) resizeObserver.observe(ref);
    });

    return () => resizeObserver.disconnect();
  }, [nodes]);

  // Calculate curve path for edge - connecting from right edge to left edge, vertically centered
  const getCurvePath = (fromId: string, toId: string): string => {
    const fromPos = nodePositions[fromId];
    const toPos = nodePositions[toId];

    if (!fromPos || !toPos) return '';

    const NODE_WIDTH = 110;
    // Use actual node height or fallback to estimated height
    const fromHeight = nodeHeights[fromId] || 50;
    const toHeight = nodeHeights[toId] || 50;

    // Connect from right edge of source to left edge of target, vertically centered
    const x1 = fromPos.x + NODE_WIDTH;
    const y1 = fromPos.y + fromHeight / 2;
    const x2 = toPos.x;
    const y2 = toPos.y + toHeight / 2;

    // Calculate direction
    const dx = x2 - x1;

    // Control points for smooth curve
    // Use a smooth S-curve for horizontal connections
    const controlOffset = Math.max(60, Math.abs(dx) * 0.4);

    // For horizontal connections, create a smooth S-curve
    const cp1x = x1 + controlOffset;
    const cp1y = y1;
    const cp2x = x2 - controlOffset;
    const cp2y = y2;

    return `M ${x1} ${y1} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${x2} ${y2}`;
  };


  return (
    <Box
      ref={containerRef}
      sx={{
        width: '100%',
        height: '100%',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* SVG for drawing curves */}
      <svg
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          pointerEvents: 'none',
          zIndex: 0,
        }}
      >
        {edges.map((edge, idx) => {
          const path = getCurvePath(edge.from, edge.to);
          if (!path) return null;

          return (
            <g key={`${edge.from}-${edge.to}-${idx}`}>
              <path
                d={path}
                fill="none"
                stroke={theme.palette.primary.main}
                strokeWidth="2.5"
                opacity={0.5}
                markerEnd={`url(#arrowhead-${idx})`}
              />
              <defs>
                <marker
                  id={`arrowhead-${idx}`}
                  markerWidth="8"
                  markerHeight="8"
                  refX="7"
                  refY="4"
                  orient="auto"
                  markerUnits="strokeWidth"
                >
                  <path
                    d="M 0 0 L 7 4 L 0 8 Z"
                    fill={theme.palette.primary.main}
                    opacity={0.6}
                    stroke="none"
                  />
                </marker>
              </defs>
            </g>
          );
        })}
      </svg>

      {/* Nodes */}
      <Box
        sx={{
          position: 'relative',
          width: '100%',
          height: '100%',
          zIndex: 1,
        }}
      >
        {nodes.map((node) => {
          const isCurrent = currentStep === node.id;
          const pos = nodePositions[node.id] || { x: 0, y: 0 };
          const isDragging = draggingNode === node.id;

          return (
            <Paper
              key={node.id}
              ref={(el) => {
                nodeRefs.current[node.id] = el;
              }}
              elevation={isCurrent ? 4 : isDragging ? 6 : 1}
              onMouseDown={(e) => handleMouseDown(e, node.id)}
              sx={{
                position: 'absolute',
                left: pos.x,
                top: pos.y,
                p: 1,
                width: 110,
                borderRadius: 1.5,
                border: isCurrent ? `2px solid ${theme.palette.primary.main}` : `1px solid ${alpha(theme.palette.divider, 0.5)}`,
                backgroundColor: isCurrent
                  ? alpha(theme.palette.primary.main, 0.1)
                  : theme.palette.background.paper,
                cursor: isDragging ? 'grabbing' : 'grab',
                transition: isDragging ? 'none' : 'all 0.2s ease',
                userSelect: 'none',
                zIndex: isDragging ? 10 : 1,
                '&:hover': {
                  transform: isDragging ? 'none' : 'translateY(-2px)',
                  boxShadow: theme.shadows[4],
                },
              }}
            >
              <Typography
                variant="body2"
                sx={{
                  fontWeight: 600,
                  textTransform: 'capitalize',
                  color: isCurrent ? theme.palette.primary.main : theme.palette.text.primary,
                  mb: 0.25,
                  textAlign: 'center',
                  fontSize: '0.75rem',
                  lineHeight: 1.2,
                }}
              >
                {node.name}
              </Typography>
              {node.config && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{
                    display: 'block',
                    textAlign: 'center',
                    fontSize: '0.6rem',
                    lineHeight: 1.1,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {node.config}
                </Typography>
              )}
              {isCurrent && (
                <Box
                  sx={{
                    position: 'absolute',
                    top: 8,
                    right: 8,
                    width: 10,
                    height: 10,
                    borderRadius: '50%',
                    backgroundColor: theme.palette.primary.main,
                    animation: 'pulse 2s infinite',
                    '@keyframes pulse': {
                      '0%, 100%': { opacity: 1, transform: 'scale(1)' },
                      '50%': { opacity: 0.7, transform: 'scale(1.2)' },
                    },
                  }}
                />
              )}
            </Paper>
          );
        })}
      </Box>
    </Box>
  );
};

// Recursive FileTreeView component
interface TreeNode {
  folders: Record<string, TreeNode>;
  files: Array<{name: string; path: string; size: number; modified: number}>;
}

interface FileTreeViewProps {
  tree: TreeNode;
  path: string;
  expandedFolders: Set<string>;
  toggleFolder: (path: string) => void;
  selectedFile: string | null;
  onSelectFile: (path: string) => void;
  depth?: number;
}

const FileTreeView: React.FC<FileTreeViewProps> = ({
  tree, path, expandedFolders, toggleFolder, selectedFile, onSelectFile, depth = 0
}) => {
  const theme = useTheme();
  const stripProgrammerPrefix = (name: string) => {
    if (!name.startsWith('programmer-')) return name;
    const stripped = name.slice('programmer-'.length);
    return stripped.length > 0 ? stripped : name;
  };
  const hasContent = Object.keys(tree.folders).length > 0 || tree.files.length > 0;

  if (!hasContent && depth === 0) {
    return (
      <Box sx={{ p: 3, textAlign: 'center' }}>
        <Typography color="text.secondary">No files yet</Typography>
      </Box>
    );
  }

  return (
    <>
      {/* Folders */}
      {Object.entries(tree.folders).map(([folderName, subtree]) => {
        const folderPath = path ? `${path}/${folderName}` : folderName;
        const isExpanded = expandedFolders.has(folderPath);

        return (
          <Box key={folderPath}>
            <Box
              onClick={() => toggleFolder(folderPath)}
              sx={{
                py: 0.5,
                pl: depth * 2 + 1,
                pr: 1,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 0.5,
                '&:hover': { backgroundColor: alpha(theme.palette.primary.main, 0.05) },
              }}
            >
              {isExpanded ? (
                <ExpandMoreIcon sx={{ fontSize: 18, color: 'text.secondary' }} />
              ) : (
                <ChevronRightIcon sx={{ fontSize: 18, color: 'text.secondary' }} />
              )}
              {isExpanded ? (
                <FolderOpenIcon sx={{ fontSize: 18 }} color="warning" />
              ) : (
                <FolderIcon sx={{ fontSize: 18 }} color="warning" />
              )}
              <Typography variant="body2" sx={{ fontSize: '0.85rem' }}>
                {folderName}
              </Typography>
            </Box>
            {isExpanded && (
              <FileTreeView
                tree={subtree as TreeNode}
                path={folderPath}
                expandedFolders={expandedFolders}
                toggleFolder={toggleFolder}
                selectedFile={selectedFile}
                onSelectFile={onSelectFile}
                depth={depth + 1}
              />
            )}
          </Box>
        );
      })}

      {/* Files */}
      {tree.files.map((file) => (
        <Box
          key={file.path}
          onClick={() => onSelectFile(file.path)}
          sx={{
            py: 0.5,
            pl: depth * 2 + 3.5,
            pr: 1,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 0.5,
            backgroundColor: selectedFile === file.path ? alpha(theme.palette.primary.main, 0.1) : 'transparent',
            '&:hover': { backgroundColor: alpha(theme.palette.primary.main, 0.05) },
          }}
        >
          <FileIcon sx={{ fontSize: 16 }} color="action" />
          <Typography variant="body2" noWrap sx={{ fontSize: '0.85rem' }}>
            {stripProgrammerPrefix(file.name)}
          </Typography>
        </Box>
      ))}
    </>
  );
};

// Separate component for file output with dialog
const FileOutputChip: React.FC<{ filename: string }> = ({ filename }) => {
  const theme = useTheme();
  const shortName = filename.split('/').pop() || filename;
  const displayName = shortName.startsWith('programmer-') ? shortName.slice('programmer-'.length) : shortName;
  const [dialogOpen, setDialogOpen] = useState(false);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [fileLang, setFileLang] = useState('text');

  const getFileIcon = (fname: string) => {
    const ext = fname.split('.').pop()?.toLowerCase();
    if (['js', 'ts', 'tsx', 'jsx', 'py', 'java', 'cpp', 'c', 'go', 'rs'].includes(ext || '')) {
      return <CodeIcon fontSize="small" />;
    }
    if (['md', 'txt', 'json', 'yaml', 'yml', 'xml', 'html', 'css'].includes(ext || '')) {
      return <DocIcon fontSize="small" />;
    }
    if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext || '')) {
      return <ImageIcon fontSize="small" />;
    }
    return <FileIcon fontSize="small" />;
  };

  const handleViewFile = async () => {
    setDialogOpen(true);
    setFileLoading(true);
    setFileError(null);

    try {
      const response = await fetch('/api/files/read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: filename }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to load file');
      }

      const data = await response.json();
      setFileContent(data.content);
      setFileLang(data.language || 'text');
    } catch (err) {
      setFileError(err instanceof Error ? err.message : 'Failed to load file');
    } finally {
      setFileLoading(false);
    }
  };

  const handleCopy = () => {
    if (fileContent) {
      navigator.clipboard.writeText(fileContent);
    }
  };

  return (
    <>
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, ml: 6, py: 0.5 }}>
          <Chip
            icon={getFileIcon(filename)}
            label={displayName || shortName}
            size="small"
            onClick={handleViewFile}
            sx={{
              backgroundColor: alpha(theme.palette.success.main, 0.1),
              color: theme.palette.success.main,
              border: `1px solid ${alpha(theme.palette.success.main, 0.3)}`,
              '& .MuiChip-icon': {
                color: theme.palette.success.main,
              },
              cursor: 'pointer',
              '&:hover': {
                backgroundColor: alpha(theme.palette.success.main, 0.15),
              },
            }}
          />
          <Typography variant="caption" color="text.secondary">
            Click to view
          </Typography>
        </Box>
      </motion.div>

      {/* File Viewer Dialog */}
      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        maxWidth="md"
        fullWidth
        PaperProps={{
          sx: {
            backgroundColor: theme.palette.background.paper,
            backgroundImage: 'none',
          }
        }}
      >
        <DialogTitle
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: `1px solid ${theme.palette.divider}`,
            py: 1.5,
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {getFileIcon(filename)}
            <Typography variant="subtitle1" sx={{ fontFamily: 'monospace' }}>
              {shortName}
            </Typography>
            <Chip label={fileLang} size="small" variant="outlined" sx={{ fontSize: '0.7rem', height: 20 }} />
          </Box>
          <Box>
            <Tooltip title="Copy to clipboard">
              <IconButton size="small" onClick={handleCopy} disabled={!fileContent}>
                <CopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <IconButton size="small" onClick={() => setDialogOpen(false)}>
              <CloseIcon fontSize="small" />
            </IconButton>
          </Box>
        </DialogTitle>
        <DialogContent sx={{ p: 0 }}>
          {fileLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 8 }}>
              <CircularProgress size={32} />
            </Box>
          ) : fileError ? (
            <Box sx={{ p: 3, textAlign: 'center' }}>
              <Typography color="error">{fileError}</Typography>
            </Box>
          ) : (
            <Box
              component="pre"
              sx={{
                m: 0,
                p: 2,
                overflow: 'auto',
                maxHeight: '60vh',
                fontFamily: 'monospace',
                fontSize: '0.85rem',
                lineHeight: 1.6,
                backgroundColor: alpha(theme.palette.background.default, 0.5),
                '&::-webkit-scrollbar': { width: 8, height: 8 },
                '&::-webkit-scrollbar-thumb': {
                  backgroundColor: alpha(theme.palette.primary.main, 0.2),
                  borderRadius: 4,
                },
              }}
            >
              <code>{fileContent}</code>
            </Box>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
};
