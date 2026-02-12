import React, { ReactNode } from 'react';
import {
  Box,
  AppBar,
  Toolbar,
  Typography,
  IconButton,
  Tooltip,
  useTheme,
  alpha,
  GlobalStyles,
} from '@mui/material';
import {
  Settings as SettingsIcon,
  DarkMode as DarkModeIcon,
  LightMode as LightModeIcon,
  Terminal as TerminalIcon,
  GitHub as GitHubIcon,
} from '@mui/icons-material';
import { motion } from 'framer-motion';
import { useThemeContext } from '../context/ThemeContext';
import { useSession } from '../context/SessionContext';

interface LayoutProps {
  children: ReactNode;
  onOpenSettings: () => void;
  onToggleLogs: () => void;
  showLogs: boolean;
}

const Layout: React.FC<LayoutProps> = ({ children, onOpenSettings, onToggleLogs, showLogs }) => {
  const theme = useTheme();
  const { mode, toggleTheme } = useThemeContext();
  const { clearSession, currentSession } = useSession();

  return (
    <>
      <GlobalStyles
        styles={{
          'html, body, #root': {
            height: '100%',
            overflow: 'hidden',
          },
        }}
      />
      <Box
        sx={{
          height: '100vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          background: theme.palette.mode === 'dark'
            ? `linear-gradient(180deg, ${alpha(theme.palette.primary.main, 0.03)} 0%, transparent 100%)`
            : theme.palette.background.default,
        }}
      >
      {/* Header */}
      <AppBar
        position="sticky"
        elevation={0}
        sx={{
          background: alpha(theme.palette.background.paper, 0.8),
          backdropFilter: 'blur(20px)',
          borderBottom: `1px solid ${theme.palette.divider}`,
        }}
      >
        <Toolbar sx={{ justifyContent: 'space-between' }}>
          {/* Logo */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5 }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
              <Box
                onClick={currentSession ? clearSession : undefined}
                sx={{
                  width: 36,
                  height: 36,
                  borderRadius: '10px',
                  background: `linear-gradient(135deg, ${theme.palette.primary.main} 0%, ${theme.palette.primary.dark} 100%)`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  boxShadow: `0 4px 12px ${alpha(theme.palette.primary.main, 0.3)}`,
                  cursor: currentSession ? 'pointer' : 'default',
                  transition: 'transform 0.2s, box-shadow 0.2s',
                  '&:hover': currentSession ? {
                    transform: 'scale(1.05)',
                    boxShadow: `0 6px 16px ${alpha(theme.palette.primary.main, 0.4)}`,
                  } : {},
                }}
              >
                <Typography
                  sx={{
                    color: theme.palette.primary.contrastText,
                    fontWeight: 700,
                    fontSize: '1rem',
                  }}
                >
                  MS
                </Typography>
              </Box>
              <Box>
                <Typography
                  variant="h6"
                  sx={{
                    fontWeight: 600,
                    color: theme.palette.text.primary,
                    letterSpacing: '-0.02em',
                  }}
                >
                  MS-Agent
                </Typography>
                <Typography
                  variant="caption"
                  sx={{
                    color: theme.palette.text.secondary,
                    letterSpacing: '0.05em',
                    textTransform: 'uppercase',
                    fontSize: '0.65rem',
                  }}
                >
                  Intelligent Platform
                </Typography>
              </Box>
            </Box>
          </motion.div>

          {/* Actions */}
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Tooltip title="Toggle Logs">
                <IconButton
                  onClick={onToggleLogs}
                  sx={{
                    color: showLogs ? theme.palette.primary.main : theme.palette.text.secondary,
                    '&:hover': {
                      backgroundColor: alpha(theme.palette.primary.main, 0.1),
                    },
                  }}
                >
                  <TerminalIcon />
                </IconButton>
              </Tooltip>

              <Tooltip title={mode === 'dark' ? 'Light Mode' : 'Dark Mode'}>
                <IconButton
                  onClick={toggleTheme}
                  sx={{
                    color: theme.palette.text.secondary,
                    '&:hover': {
                      backgroundColor: alpha(theme.palette.primary.main, 0.1),
                    },
                  }}
                >
                  {mode === 'dark' ? <LightModeIcon /> : <DarkModeIcon />}
                </IconButton>
              </Tooltip>

              <Tooltip title="Settings">
                <IconButton
                  onClick={onOpenSettings}
                  sx={{
                    color: theme.palette.text.secondary,
                    '&:hover': {
                      backgroundColor: alpha(theme.palette.primary.main, 0.1),
                    },
                  }}
                >
                  <SettingsIcon />
                </IconButton>
              </Tooltip>

              <Tooltip title="GitHub">
                <IconButton
                  component="a"
                  href="https://github.com/modelscope/ms-agent"
                  target="_blank"
                  rel="noopener noreferrer"
                  sx={{
                    color: theme.palette.text.secondary,
                    '&:hover': {
                      backgroundColor: alpha(theme.palette.primary.main, 0.1),
                    },
                  }}
                >
                  <GitHubIcon />
                </IconButton>
              </Tooltip>
            </Box>
          </motion.div>
        </Toolbar>
      </AppBar>

      {/* Main Content */}
      <Box
        component="main"
        sx={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          minHeight: 0,
        }}
      >
        {children}
      </Box>

      {/* Footer */}
      <Box
        component="footer"
        sx={{
          py: 2,
          px: 3,
          borderTop: `1px solid ${theme.palette.divider}`,
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          gap: 2,
        }}
      >
        <Typography
          variant="caption"
          sx={{
            color: theme.palette.text.secondary,
            letterSpacing: '0.02em',
          }}
        >
          Powered by ModelScope
        </Typography>
        <Box
          sx={{
            width: 4,
            height: 4,
            borderRadius: '50%',
            backgroundColor: theme.palette.text.secondary,
            opacity: 0.5,
          }}
        />
        <Typography
          variant="caption"
          sx={{
            color: theme.palette.text.secondary,
          }}
        >
          © 2026 Alibaba Inc.
        </Typography>
      </Box>
      </Box>
    </>
  );
};

export default Layout;
