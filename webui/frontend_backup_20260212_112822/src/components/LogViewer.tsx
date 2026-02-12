import React, { useRef, useEffect, useState } from 'react';
import {
  Box,
  Typography,
  IconButton,
  TextField,
  InputAdornment,
  useTheme,
  alpha,
  Chip,
  Tooltip,
} from '@mui/material';
import {
  Clear as ClearIcon,
  Search as SearchIcon,
  Download as DownloadIcon,
} from '@mui/icons-material';
import { motion, AnimatePresence } from 'framer-motion';
import { LogEntry } from '../context/SessionContext';

interface LogViewerProps {
  logs: LogEntry[];
  onClear?: () => void;
}

const LogViewer: React.FC<LogViewerProps> = ({ logs, onClear }) => {
  const theme = useTheme();
  const logsEndRef = useRef<HTMLDivElement>(null);
  const [filter, setFilter] = useState('');
  const [levelFilter, setLevelFilter] = useState<string | null>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const filteredLogs = logs.filter((log) => {
    const matchesSearch = !filter || log.message.toLowerCase().includes(filter.toLowerCase());
    const matchesLevel = !levelFilter || log.level === levelFilter;
    return matchesSearch && matchesLevel;
  });

  const getLevelColor = (level: LogEntry['level']) => {
    switch (level) {
      case 'error': return theme.palette.error.main;
      case 'warning': return theme.palette.warning.main;
      case 'debug': return theme.palette.info.main;
      default: return theme.palette.text.secondary;
    }
  };

  const handleDownload = () => {
    const content = logs.map((log) =>
      `[${log.timestamp}] [${log.level.toUpperCase()}] ${log.message}`
    ).join('\n');

    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ms-agent-logs-${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Box
      sx={{
        width: 400,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        maxHeight: '100%',
        backgroundColor: alpha(theme.palette.background.paper, 0.5),
        borderLeft: `1px solid ${theme.palette.divider}`,
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <Box
        sx={{
          p: 1.5,
          borderBottom: `1px solid ${theme.palette.divider}`,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
        }}
      >
        <Typography variant="subtitle2" sx={{ flex: 1, fontWeight: 600 }}>
          Logs
        </Typography>

        <Tooltip title="Download Logs">
          <IconButton size="small" onClick={handleDownload}>
            <DownloadIcon fontSize="small" />
          </IconButton>
        </Tooltip>

        {onClear && (
          <Tooltip title="Clear Logs">
            <IconButton size="small" onClick={onClear}>
              <ClearIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
      </Box>

      {/* Filters */}
      <Box sx={{ p: 1.5, borderBottom: `1px solid ${theme.palette.divider}` }}>
        <TextField
          size="small"
          fullWidth
          placeholder="Search logs..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          sx={{ mb: 1 }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
        />

        <Box sx={{ display: 'flex', gap: 0.5 }}>
          {['info', 'warning', 'error', 'debug'].map((level) => (
            <Chip
              key={level}
              label={level}
              size="small"
              onClick={() => setLevelFilter(levelFilter === level ? null : level)}
              sx={{
                height: 22,
                fontSize: '0.65rem',
                textTransform: 'uppercase',
                backgroundColor: levelFilter === level
                  ? alpha(getLevelColor(level as LogEntry['level']), 0.2)
                  : 'transparent',
                border: `1px solid ${alpha(getLevelColor(level as LogEntry['level']), 0.3)}`,
                color: getLevelColor(level as LogEntry['level']),
              }}
            />
          ))}
        </Box>
      </Box>

      {/* Log List - Scrollable Container */}
      <Box
        sx={{
          flex: 1,
          overflowY: 'auto',
          overflowX: 'hidden',
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: '0.75rem',
          p: 1,
          minHeight: 0, // Important for flex scrolling
          maxHeight: '100%', // Ensure it doesn't exceed parent
          '&::-webkit-scrollbar': {
            width: 6,
          },
          '&::-webkit-scrollbar-track': {
            backgroundColor: 'transparent',
          },
          '&::-webkit-scrollbar-thumb': {
            backgroundColor: alpha(theme.palette.primary.main, 0.2),
            borderRadius: 3,
            '&:hover': {
              backgroundColor: alpha(theme.palette.primary.main, 0.3),
            },
          },
        }}
      >
        <AnimatePresence>
          {filteredLogs.map((log, index) => (
            <motion.div
              key={`${log.timestamp}-${index}`}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              <Box
                sx={{
                  py: 0.5,
                  px: 1,
                  borderRadius: 1,
                  mb: 0.5,
                  '&:hover': {
                    backgroundColor: alpha(theme.palette.action.hover, 0.5),
                  },
                }}
              >
                <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
                  <Typography
                    component="span"
                    sx={{
                      color: getLevelColor(log.level),
                      fontSize: '0.65rem',
                      fontWeight: 600,
                      textTransform: 'uppercase',
                      minWidth: 45,
                    }}
                  >
                    [{log.level}]
                  </Typography>
                  <Typography
                    component="span"
                    sx={{
                      color: theme.palette.text.primary,
                      wordBreak: 'break-word',
                      flex: 1,
                    }}
                  >
                    {log.message}
                  </Typography>
                </Box>
                <Typography
                  variant="caption"
                  sx={{
                    color: theme.palette.text.secondary,
                    fontSize: '0.6rem',
                    opacity: 0.7,
                  }}
                >
                  {new Date(log.timestamp).toLocaleTimeString()}
                </Typography>
              </Box>
            </motion.div>
          ))}
        </AnimatePresence>
        <div ref={logsEndRef} />
      </Box>
    </Box>
  );
};

export default LogViewer;
