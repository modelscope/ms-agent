import React, { useMemo } from 'react';
import { Box, Typography, useTheme } from '@mui/material';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';

interface MessageContentProps {
  content: string;
}

const MessageContent: React.FC<MessageContentProps> = ({ content }) => {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';

  const components = useMemo(() => ({
    code({ node, inline, className, children, ...props }: any) {
      const match = /language-(\w+)/.exec(className || '');
      const language = match ? match[1] : '';

      if (!inline && language) {
        return (
          <Box sx={{ my: 1.5, borderRadius: 2, overflow: 'hidden' }}>
            <Box
              sx={{
                px: 2,
                py: 0.5,
                backgroundColor: isDark ? '#1e1e1e' : '#f5f5f5',
                borderBottom: `1px solid ${theme.palette.divider}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <Typography variant="caption" color="text.secondary">
                {language}
              </Typography>
            </Box>
            <SyntaxHighlighter
              style={isDark ? oneDark : oneLight}
              language={language}
              PreTag="div"
              customStyle={{
                margin: 0,
                borderRadius: 0,
                fontSize: '0.85rem',
              }}
              {...props}
            >
              {String(children).replace(/\n$/, '')}
            </SyntaxHighlighter>
          </Box>
        );
      }

      return (
        <Typography
          component="code"
          sx={{
            px: 0.75,
            py: 0.25,
            borderRadius: 1,
            backgroundColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.06)',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '0.85em',
          }}
        >
          {children}
        </Typography>
      );
    },
    p({ children }: any) {
      return (
        <Typography
          component="p"
          sx={{
            mb: 1.5,
            '&:last-child': { mb: 0 },
            lineHeight: 1.7,
          }}
        >
          {children}
        </Typography>
      );
    },
    ul({ children }: any) {
      return (
        <Box
          component="ul"
          sx={{
            pl: 3,
            mb: 1.5,
            '& li': {
              mb: 0.5,
            },
          }}
        >
          {children}
        </Box>
      );
    },
    ol({ children }: any) {
      return (
        <Box
          component="ol"
          sx={{
            pl: 3,
            mb: 1.5,
            '& li': {
              mb: 0.5,
            },
          }}
        >
          {children}
        </Box>
      );
    },
    h1({ children }: any) {
      return (
        <Typography variant="h5" sx={{ mt: 2, mb: 1, fontWeight: 600 }}>
          {children}
        </Typography>
      );
    },
    h2({ children }: any) {
      return (
        <Typography variant="h6" sx={{ mt: 2, mb: 1, fontWeight: 600 }}>
          {children}
        </Typography>
      );
    },
    h3({ children }: any) {
      return (
        <Typography variant="subtitle1" sx={{ mt: 1.5, mb: 1, fontWeight: 600 }}>
          {children}
        </Typography>
      );
    },
    blockquote({ children }: any) {
      return (
        <Box
          component="blockquote"
          sx={{
            pl: 2,
            py: 0.5,
            my: 1.5,
            borderLeft: `3px solid ${theme.palette.primary.main}`,
            backgroundColor: `${theme.palette.primary.main}10`,
            borderRadius: 1,
          }}
        >
          {children}
        </Box>
      );
    },
    a({ href, children }: any) {
      return (
        <Typography
          component="a"
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          sx={{
            color: theme.palette.primary.main,
            textDecoration: 'none',
            '&:hover': {
              textDecoration: 'underline',
            },
          }}
        >
          {children}
        </Typography>
      );
    },
  }), [isDark, theme]);

  return (
    <Box
      sx={{
        '& > *:first-child': { mt: 0 },
        '& > *:last-child': { mb: 0 },
      }}
    >
      <ReactMarkdown components={components}>
        {content}
      </ReactMarkdown>
    </Box>
  );
};

export default MessageContent;
