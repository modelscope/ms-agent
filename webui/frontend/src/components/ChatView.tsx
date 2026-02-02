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
} from '@mui/material';
import {
  Send as SendIcon,
  Stop as StopIcon,
  Chat as ChatIcon,
  PlayArrow as RunningIcon,
} from '@mui/icons-material';
import { motion, AnimatePresence } from 'framer-motion';
import { useSession, Message } from '../context/SessionContext';
import MessageContent from './MessageContent';

export const ChatView: React.FC = () => {
  const theme = useTheme();
  const {
    currentSession,
    messages,
    streamingContent,
    isStreaming,
    isLoading,
    sendMessage,
    stopAgent,
    createChatSession,
    ws,
  } = useSession();

  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Check if agent is waiting for input
  const isWaitingForInput = messages.some(m => m.type === 'waiting_input');
  const inputEnabled = !isLoading || isWaitingForInput;

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSend = useCallback(async () => {
    if (!input.trim()) return;

    // If no session exists, create a chat session first
    if (!currentSession) {
      await createChatSession(input.trim());
      setInput('');
      return;
    }

    // If waiting for input, send input to existing agent
    if (isWaitingForInput && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        action: 'send_input',
        input: input.trim(),
      }));
      setInput('');
      return;
    }

    // Otherwise, send message to existing session
    if (!isLoading || isWaitingForInput) {
      sendMessage(input);
      setInput('');
    }
  }, [input, currentSession, isLoading, isWaitingForInput, sendMessage, createChatSession, ws]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
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
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Chip
            icon={<ChatIcon sx={{ fontSize: 16 }} />}
            label="Chat Assistant"
            size="small"
            sx={{
              backgroundColor: alpha(theme.palette.primary.main, 0.1),
              color: theme.palette.primary.main,
              fontWeight: 600,
              borderRadius: '8px',
            }}
          />
          {currentSession && (
            <Chip
              icon={currentSession.status === 'running' ? <RunningIcon sx={{ fontSize: 14 }} /> : undefined}
              label={currentSession.status}
              size="small"
              color={
                currentSession.status === 'running' ? 'info' :
                currentSession.status === 'completed' ? 'success' :
                currentSession.status === 'error' ? 'error' : 'default'
              }
              sx={{
                textTransform: 'capitalize',
                borderRadius: '8px',
                '& .MuiChip-icon': { ml: 0.5 },
              }}
            />
          )}
        </Box>
      </Box>

      {/* Messages Area */}
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
        {/* Empty State */}
        {messages.length === 0 && !streamingContent && (
          <Box
            sx={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              color: theme.palette.text.secondary,
            }}
          >
            <ChatIcon sx={{ fontSize: 64, mb: 2, opacity: 0.3 }} />
            <Typography variant="h6" sx={{ fontWeight: 500, mb: 1 }}>
              Start a Conversation
            </Typography>
            <Typography variant="body2" sx={{ opacity: 0.7 }}>
              Type your message below to begin chatting
            </Typography>
          </Box>
        )}

        <AnimatePresence>
          {messages.map((message) => (
            <ChatMessageBubble key={message.id} message={message} />
          ))}
        </AnimatePresence>

        {/* Streaming Content */}
        {streamingContent && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
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
                  boxShadow: 'none',
                }}
              >
                <MessageContent content={streamingContent} />
                <Box
                  component="span"
                  sx={{
                    display: 'inline-block',
                    width: 8,
                    height: 16,
                    ml: 0.5,
                    backgroundColor: theme.palette.primary.main,
                    animation: 'blink 1s infinite',
                    '@keyframes blink': {
                      '0%, 100%': { opacity: 1 },
                      '50%': { opacity: 0 },
                    },
                  }}
                />
              </Paper>
            </Box>
          </motion.div>
        )}

        {/* Loading Indicator */}
        {isLoading && !streamingContent && !isStreaming && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
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
                    Thinking...
                  </Typography>
                </Box>
              </Paper>
            </Box>
          </motion.div>
        )}

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
          inputRef={inputRef}
          fullWidth
          multiline
          maxRows={4}
          placeholder={isWaitingForInput ? "Please provide your response..." : "Type your message..."}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading && !isWaitingForInput}
          sx={{
            '& .MuiOutlinedInput-root': {
              borderRadius: '12px',
              backgroundColor: theme.palette.background.paper,
              ...(isWaitingForInput && {
                border: `2px solid ${alpha(theme.palette.info.main, 0.5)}`,
                boxShadow: `0 0 0 3px ${alpha(theme.palette.info.main, 0.1)}`,
              }),
            },
          }}
          InputProps={{
            endAdornment: (
              <InputAdornment position="end">
                {isLoading && !isWaitingForInput ? (
                  <IconButton onClick={stopAgent} color="error">
                    <StopIcon />
                  </IconButton>
                ) : (
                  <IconButton
                    onClick={handleSend}
                    disabled={!input.trim() || (isLoading && !isWaitingForInput)}
                    sx={{
                      backgroundColor: input.trim() && inputEnabled
                        ? theme.palette.primary.main
                        : 'transparent',
                      color: input.trim() && inputEnabled
                        ? theme.palette.primary.contrastText
                        : theme.palette.text.secondary,
                      '&:hover': {
                        backgroundColor: input.trim() && inputEnabled
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
  );
};

interface ChatMessageBubbleProps {
  message: Message;
}

const ChatMessageBubble: React.FC<ChatMessageBubbleProps> = ({ message }) => {
  const theme = useTheme();
  const isUser = message.role === 'user';
  const isError = message.type === 'error';

  // Skip empty messages
  if (!message.content?.trim()) return null;

  // Skip tool calls and other non-display message types
  if (message.type === 'tool_call' || message.type === 'tool_result') return null;
  if (message.type === 'step_start' || message.type === 'step_complete') return null;
  if (message.type === 'file_output' || message.type === 'deployment_url') return null;

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
        <Paper
          elevation={0}
          sx={{
            maxWidth: '75%',
            minWidth: 60,
            px: 2,
            py: 1.25,
            borderRadius: isUser ? '20px 20px 4px 20px' : '20px 20px 20px 4px',
            backgroundColor: isUser
              ? theme.palette.primary.main
              : isError
                ? alpha(theme.palette.error.main, 0.1)
                : theme.palette.background.paper,
            color: isUser
              ? theme.palette.primary.contrastText
              : isError
                ? theme.palette.error.main
                : theme.palette.text.primary,
            border: 'none',
            boxShadow: 'none',
          }}
        >
          <MessageContent content={message.content} />
        </Paper>
      </Box>
    </motion.div>
  );
};

export default ChatView;
