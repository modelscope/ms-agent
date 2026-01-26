import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Refresh as RetryIcon,
} from '@mui/icons-material';
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
  Avatar,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  CircularProgress,
} from '@mui/material';
import {
  Send as SendIcon,
  Stop as StopIcon,
  Person as PersonIcon,
  AutoAwesome as BotIcon,
  PlayArrow as RunningIcon,
  InsertDriveFile as FileIcon,
  Code as CodeIcon,
  Description as DocIcon,
  Image as ImageIcon,
  CheckCircle as CompleteIcon,
  HourglassTop as StartIcon,
  Close as CloseIcon,
  ContentCopy as CopyIcon,
  Folder as FolderIcon,
  FolderOpen as FolderOpenIcon,
  ChevronRight as ChevronRightIcon,
  ExpandMore as ExpandMoreIcon,
} from '@mui/icons-material';
import { motion, AnimatePresence } from 'framer-motion';
import { useSession, Message, Session } from '../context/SessionContext';
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

  const lastUserMessageId = React.useMemo(() => {
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].role === 'user') return messages[i].id;
      }
      return null;
    }, [messages]);

  const completedSteps = React.useMemo(() => {
    const set = new Set<string>();
    for (const m of messages) {
      if (m.type === 'step_complete' && m.content) set.add(m.content);
    }
    return set;
  }, [messages]);

  const [input, setInput] = useState('');
  const [outputFilesOpen, setOutputFilesOpen] = useState(false);
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

    const loadOutputFiles = async (outputDir: string) => {
      try {
        if (!currentSession?.id) return;

        const url = new URL('/api/files/list', window.location.origin);
        url.searchParams.set('output_dir', outputDir);
        url.searchParams.set('session_id', currentSession.id);

        const response = await fetch(url.toString());
        if (response.ok) {
          const data = await response.json();
          setOutputTree(data.tree || { folders: {}, files: [] });
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
    loadOutputFiles('output');
    setOutputFilesOpen(true);
    setSelectedFile(null);
    setFileContent(null);
  };

    const handleViewFile = async (path: string) => {
      if (!currentSession?.id) return;

      setSelectedFile(path);
      setFileLoading(true);
      try {
        const response = await fetch('/api/files/read', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path, session_id: currentSession.id }),
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
              px: 3,
              py: 3,
              display: 'flex',
              flexDirection: 'column',
              gap: 2.5,
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
                  sessionStatus={currentSession?.status}
                  completedSteps={completedSteps}

                 showRetry={
                  message.role === 'user' &&
                  message.id === lastUserMessageId &&
                  !isLoading && !isStreaming
                 }
                 onRetry={(content) => sendMessage(content, { reuseMessageId: message.id })}
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
                      sessionStatus={currentSession?.status}
                      completedSteps={completedSteps}
                  />
                </motion.div>
              )}

              {/* Loading Indicator */}
              {isLoading && !isStreaming && messages.length > 0 && (() => {
                // Find current running step
                const runningSteps = messages.filter(m => m.type === 'step_start');
                const completedSteps = messages.filter(m => m.type === 'step_complete');
                const currentStep = runningSteps.length > completedSteps.length
                  ? runningSteps[runningSteps.length - 1]?.content?.replace(/_/g, ' ')
                  : null;

                return (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                  >
                    <Box
                      sx={{
                        display: 'flex',
                        gap: 1.5,
                        alignItems: 'flex-start',
                      }}
                    >
                      <Avatar
                        sx={{
                          width: 36,
                          height: 36,
                          backgroundColor: alpha(theme.palette.primary.main, 0.1),
                          color: theme.palette.primary.main,
                        }}
                      >
                        <BotIcon fontSize="small" />
                      </Avatar>
                      <Paper
                        elevation={0}
                        sx={{
                          px: 2.5,
                          py: 1.5,
                          borderRadius: '18px 18px 18px 4px',
                          backgroundColor: alpha(theme.palette.background.paper, 0.8),
                          border: `1px solid ${alpha(theme.palette.divider, 0.5)}`,
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
                            {currentStep ? (
                              <>
                                <Box component="span" sx={{ textTransform: 'capitalize' }}>
                                  {currentStep}
                                </Box>
                                <Box component="span" sx={{ opacity: 0.7 }}> in progress...</Box>
                              </>
                            ) : 'Processing...'}
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
  sessionStatus?: Session['status'];
  completedSteps?: Set<string>;

  showRetry?: boolean;
  onRetry?: (content: string) => void;
}

const MessageBubble: React.FC<MessageBubbleProps> = ({
  message, isStreaming, sessionStatus, completedSteps,
  showRetry, onRetry
}) => {
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

  // Step start/complete display
  if (isStepStart || isStepComplete) {
    // If a step has a completion record, hide the earlier start record to avoid duplicates.
    if (isStepStart && completedSteps?.has(message.content)) {
      return null;
    }

    const stepName = message.content.replace(/_/g, ' ');
    const isComplete = isStepComplete || (isStepStart && !!completedSteps?.has(message.content));
    const isStopped = isStepStart && !isComplete && sessionStatus === 'stopped';
    const accentColor = isComplete
      ? theme.palette.success.main
      : isStopped
      ? theme.palette.warning.main
      : theme.palette.info.main;

    return (
      <motion.div
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.3 }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1.5,
            py: 1,
            px: 2,
            ml: 5,
            borderLeft: `3px solid ${accentColor}`,
            backgroundColor: alpha(
              accentColor,
              0.05
            ),
            borderRadius: '0 8px 8px 0',
          }}
        >
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 28,
              height: 28,
              borderRadius: '50%',
              backgroundColor: alpha(
                accentColor,
                0.15
              ),
              color: accentColor,
            }}
          >
            {isComplete ? <CompleteIcon fontSize="small" /> : <StartIcon fontSize="small" />}
          </Box>
          <Box>
            <Typography
              variant="body2"
              sx={{
                fontWeight: 500,
                color: accentColor,
                textTransform: 'capitalize',
              }}
            >
              {stepName}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {isComplete ? 'Completed' : isStopped ? 'Stopped' : 'Running...'}
            </Typography>
          </Box>
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
          gap: 1.5,
          alignItems: 'flex-start',
          flexDirection: isUser ? 'row-reverse' : 'row',
          mb: 0.5,
        }}
      >
        {/* Avatar */}
        <Tooltip title={isUser ? 'You' : 'Assistant'} placement={isUser ? 'left' : 'right'}>
          <Avatar
            sx={{
              width: 36,
              height: 36,
              backgroundColor: isUser
                ? alpha(theme.palette.primary.main, 0.15)
                : isError
                ? alpha(theme.palette.error.main, 0.15)
                : alpha(theme.palette.primary.main, 0.1),
              color: isUser
                ? theme.palette.primary.main
                : isError
                ? theme.palette.error.main
                : theme.palette.primary.main,
              border: `2px solid ${isUser
                ? alpha(theme.palette.primary.main, 0.3)
                : isError
                ? alpha(theme.palette.error.main, 0.3)
                : alpha(theme.palette.primary.main, 0.2)}`,
            }}
          >
            {isUser ? <PersonIcon fontSize="small" /> : <BotIcon fontSize="small" />}
          </Avatar>
        </Tooltip>

        {/* Message Content */}
        <Paper
          elevation={0}
          sx={{
            maxWidth: '75%',
            minWidth: 60,
            px: 2.5,
            py: 1.5,
            borderRadius: isUser ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
            backgroundColor: isUser
              ? alpha(theme.palette.primary.main, 0.12)
              : isError
              ? alpha(theme.palette.error.main, 0.08)
              : alpha(theme.palette.background.paper, 0.8),
            border: `1px solid ${isUser
              ? alpha(theme.palette.primary.main, 0.25)
              : isError
              ? alpha(theme.palette.error.main, 0.3)
              : alpha(theme.palette.divider, 0.5)}`,
            backdropFilter: 'blur(8px)',
            position: 'relative',
          }}
        >
          <MessageContent content={message.content} />
            {showRetry && (
                <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 1 }}>
                  <Tooltip title="Retry">
                    <IconButton
                      size="small"
                      onClick={() => onRetry?.(message.content)}
                      sx={{ opacity: 0.75, '&:hover': { opacity: 1 } }}
                    >
                      <RetryIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </Box>
              )}
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
  const { currentSession } = useSession();
    const [fileUrl, setFileUrl] = useState<string | null>(null);
    const [fileKind, setFileKind] = useState<'text' | 'image' | 'video'>('text');

    const getFileKind = (fname: string): 'text' | 'image' | 'video' => {
      const ext = fname.split('.').pop()?.toLowerCase() || '';
      if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)) return 'image';
      if (['mp4', 'webm', 'ogg', 'mov', 'm4v'].includes(ext)) return 'video';
      return 'text';
    };

    useEffect(() => {
      if (!dialogOpen) {
        setFileContent(null);
        setFileUrl(null);
        setFileLang('text');
      }
    }, [dialogOpen]);

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

      const kind = getFileKind(filename);
      setFileKind(kind);

      try {
        if (kind === 'text') {
          const response = await fetch('/api/files/read', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: filename, session_id: currentSession?.id }),
          });

          if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to load file');
          }

          const data = await response.json();
          setFileContent(data.content);
          setFileLang(data.language || 'text');
          setFileUrl(null);
          return;
        }

        const sid = currentSession?.id;
        const streamUrl =
          `/api/files/stream?path=${encodeURIComponent(filename)}&session_id=${encodeURIComponent(sid || '')}`;
        setFileUrl(streamUrl);
        setFileContent(null);
        setFileLang(kind);
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
              <IconButton size="small" onClick={handleCopy} disabled={!fileContent || fileKind !== 'text'}>
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
          ) : fileKind === 'image' && fileUrl ? (
              <Box sx={{ p: 2, display: 'flex', justifyContent: 'center' }}>
                <Box
                  component="img"
                  src={fileUrl}
                  alt={shortName}
                  sx={{ maxWidth: '100%', maxHeight: '60vh', objectFit: 'contain' }}
                />
              </Box>
            ) : fileKind === 'video' && fileUrl ? (
              <Box sx={{ p: 2 }}>
                <Box component="video" src={fileUrl} controls sx={{ width: '100%', maxHeight: '60vh' }} />
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
