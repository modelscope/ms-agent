import React, { useState, useCallback } from 'react';
import {
  Box,
  TextField,
  Typography,
  Card,
  CardContent,
  Chip,
  InputAdornment,
  IconButton,
  useTheme,
  alpha,
  Grid,
  Tooltip,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import {
  Search as SearchIcon,
  ArrowForward as ArrowForwardIcon,
  Code as CodeIcon,
  Psychology as PsychologyIcon,
  Science as ScienceIcon,
  Description as DescriptionIcon,
  Movie as MovieIcon,
  AccountTree as WorkflowIcon,
} from '@mui/icons-material';
import { motion, AnimatePresence } from 'framer-motion';
import { useSession, Project } from '../context/SessionContext';

const projectIcons: Record<string, React.ReactElement> = {
  code_genesis: <CodeIcon />,
  agent_skills: <PsychologyIcon />,
  deep_research: <ScienceIcon />,
  doc_research: <DescriptionIcon />,
  fin_research: <ScienceIcon />,
  singularity_cinema: <MovieIcon />,
};

const SearchView: React.FC = () => {
  const theme = useTheme();
  const { projects, createSession, createChatSession, selectSession } = useSession();
  const [query, setQuery] = useState('');
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [workflowType, setWorkflowType] = useState<'standard' | 'simple'>('standard');

  const handleProjectSelect = (project: Project) => {
    setSelectedProject(project);
    // Reset workflow type when switching projects
    if (project.supports_workflow_switch) {
      setWorkflowType('standard');
    }
  };

  const handleSubmit = useCallback(async () => {
    if (!query.trim()) return;

    setIsSubmitting(true);
    try {
      // If no project selected, start a chat session
      if (!selectedProject) {
        console.log('[SearchView] No project selected, starting chat session');
        await createChatSession(query);
      } else {
        // If project selected, create project session
        console.log('[SearchView] Submitting with project:', selectedProject.id, 'query:', query, 'workflow_type:', workflowType);
        const session = await createSession(
          selectedProject.id,
          selectedProject.supports_workflow_switch ? workflowType : 'standard'
        );
        console.log('[SearchView] Session created:', session);
        if (session) {
          // Pass the session object directly to avoid race condition
          selectSession(session.id, query, session);
        }
      }
    } catch (error) {
      console.error('[SearchView] Error creating session:', error);
    } finally {
      setIsSubmitting(false);
    }
  }, [selectedProject, query, workflowType, createSession, createChatSession, selectSession]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <Box
      component={motion.div}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.4 }}
      sx={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        px: 3,
        py: 6,
        minHeight: 'calc(100vh - 180px)',
      }}
    >
      {/* Hero Section */}
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.1 }}
      >
        <Typography
          variant="h2"
          sx={{
            textAlign: 'center',
            mb: 1,
            fontWeight: 600,
            background: theme.palette.mode === 'dark'
              ? `linear-gradient(135deg, ${theme.palette.text.primary} 0%, ${theme.palette.primary.main} 100%)`
              : `linear-gradient(135deg, ${theme.palette.text.primary} 0%, ${theme.palette.primary.dark} 100%)`,
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}
        >
          Intelligent Agent Platform
        </Typography>
        <Typography
          variant="h6"
          sx={{
            textAlign: 'center',
            mb: 5,
            color: theme.palette.text.secondary,
            fontWeight: 400,
            maxWidth: 600,
            mx: 'auto',
          }}
        >
          Harness the power of AI agents for research, coding, and creative tasks
        </Typography>
      </motion.div>

      {/* Search Input */}
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.2 }}
        style={{ width: '100%', maxWidth: 700 }}
      >
        <Box sx={{ mb: 4 }}>
          <TextField
            fullWidth
            multiline
            maxRows={4}
            placeholder={selectedProject ? "What would you like to accomplish today?" : "Chat directly or select a project below..."}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            sx={{
              '& .MuiOutlinedInput-root': {
                borderRadius: '16px',
                backgroundColor: alpha(theme.palette.background.paper, 0.8),
                backdropFilter: 'blur(10px)',
                border: `2px solid ${alpha(theme.palette.primary.main, selectedProject ? 0.3 : 0.1)}`,
                transition: 'all 0.3s ease',
                '&:hover': {
                  border: `2px solid ${alpha(theme.palette.primary.main, 0.5)}`,
                },
                '&.Mui-focused': {
                  border: `2px solid ${theme.palette.primary.main}`,
                  boxShadow: `0 0 20px ${alpha(theme.palette.primary.main, 0.15)}`,
                },
              },
              '& .MuiOutlinedInput-notchedOutline': {
                border: 'none',
              },
            }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon sx={{ color: theme.palette.text.secondary }} />
                </InputAdornment>
              ),
              endAdornment: (
                <InputAdornment position="end">
                  <Tooltip title={selectedProject ? 'Start with project' : (query.trim() ? 'Start chat' : 'Type a message')}>
                    <span>
                      <IconButton
                        onClick={handleSubmit}
                        disabled={!query.trim() || isSubmitting}
                        sx={{
                          backgroundColor: theme.palette.primary.main,
                          color: theme.palette.primary.contrastText,
                          '&:hover': {
                            backgroundColor: theme.palette.primary.dark,
                          },
                          '&.Mui-disabled': {
                            backgroundColor: alpha(theme.palette.primary.main, 0.3),
                          },
                        }}
                      >
                        <ArrowForwardIcon />
                      </IconButton>
                    </span>
                  </Tooltip>
                </InputAdornment>
              ),
            }}
          />

          {/* Selected Project Badge and Workflow Selector */}
          <AnimatePresence>
            {selectedProject && (
              <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
              >
                <Box sx={{ mt: 2, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                  <Chip
                    icon={projectIcons[selectedProject.id] ?? <WorkflowIcon />}
                    label={selectedProject.display_name}
                    onDelete={() => setSelectedProject(null)}
                    sx={{
                      backgroundColor: alpha(theme.palette.primary.main, 0.15),
                      borderColor: theme.palette.primary.main,
                      '& .MuiChip-icon': {
                        color: theme.palette.primary.main,
                      },
                    }}
                    variant="outlined"
                  />

                  {/* Workflow Type Selector for code_genesis */}
                  {selectedProject.supports_workflow_switch && (
                    <Box
                      sx={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        gap: 1,
                        p: 2,
                        borderRadius: 2,
                        backgroundColor: alpha(theme.palette.background.paper, 0.6),
                        border: `1px solid ${alpha(theme.palette.primary.main, 0.2)}`,
                      }}
                    >
                      <Typography
                        variant="caption"
                        sx={{
                          color: theme.palette.text.secondary,
                          fontWeight: 500,
                          textTransform: 'uppercase',
                          letterSpacing: '0.05em',
                          fontSize: '0.7rem',
                        }}
                      >
                        Select Workflow Type
                      </Typography>
                      <ToggleButtonGroup
                        value={workflowType}
                        exclusive
                        onChange={(_, newValue) => {
                          if (newValue !== null) {
                            setWorkflowType(newValue);
                          }
                        }}
                        size="small"
                        sx={{
                          '& .MuiToggleButton-root': {
                            px: 2,
                            py: 0.5,
                            fontSize: '0.75rem',
                            borderColor: alpha(theme.palette.primary.main, 0.3),
                            '&.Mui-selected': {
                              backgroundColor: theme.palette.primary.main,
                              color: theme.palette.primary.contrastText,
                              '&:hover': {
                                backgroundColor: theme.palette.primary.dark,
                              },
                            },
                          },
                        }}
                      >
                        <ToggleButton value="standard">
                          Standard Workflow
                        </ToggleButton>
                        <ToggleButton value="simple">
                          Simple Workflow
                        </ToggleButton>
                      </ToggleButtonGroup>
                      <Typography
                        variant="caption"
                        sx={{
                          color: theme.palette.text.secondary,
                          fontSize: '0.65rem',
                          textAlign: 'center',
                          maxWidth: 300,
                        }}
                      >
                        {workflowType === 'standard'
                          ? 'Full design process: user story, architecture, file design, etc.'
                          : 'Simplified process: directly proceed to coding'}
                      </Typography>
                    </Box>
                  )}
                </Box>
              </motion.div>
            )}
          </AnimatePresence>
        </Box>
      </motion.div>

      {/* Project Cards */}
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.3 }}
        style={{ width: '100%', maxWidth: 900 }}
      >
        <Typography
          variant="subtitle2"
          sx={{
            mb: 2,
            color: theme.palette.text.secondary,
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            textAlign: 'center',
          }}
        >
          Or Select a Project for Specific Tasks
        </Typography>

        <Grid container spacing={2} justifyContent="center">
          {projects.map((project, index) => (
            <Grid item xs={12} sm={6} md={4} key={project.id}>
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.1 * index }}
              >
                <Card
                  onClick={() => handleProjectSelect(project)}
                  sx={{
                    cursor: 'pointer',
                    position: 'relative',
                    overflow: 'hidden',
                    border: selectedProject?.id === project.id
                      ? `2px solid ${theme.palette.primary.main}`
                      : `1px solid ${theme.palette.divider}`,
                    transition: 'all 0.3s ease',
                    '&:hover': {
                      transform: 'translateY(-4px)',
                      boxShadow: `0 12px 24px ${alpha(theme.palette.common.black, 0.15)}`,
                      border: `2px solid ${alpha(theme.palette.primary.main, 0.5)}`,
                    },
                    '&::before': {
                      content: '""',
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      right: 0,
                      height: 3,
                      background: selectedProject?.id === project.id
                        ? `linear-gradient(90deg, ${theme.palette.primary.main}, ${theme.palette.primary.light})`
                        : 'transparent',
                    },
                  }}
                >
                  <CardContent sx={{ p: 2.5 }}>
                    <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5, mb: 1.5 }}>
                      <Box
                        sx={{
                          p: 1,
                          borderRadius: '10px',
                          backgroundColor: alpha(theme.palette.primary.main, 0.1),
                          color: theme.palette.primary.main,
                        }}
                      >
                        {projectIcons[project.id] || <WorkflowIcon />}
                      </Box>
                      <Box sx={{ flex: 1 }}>
                        <Typography
                          variant="subtitle1"
                          sx={{
                            fontWeight: 600,
                            color: theme.palette.text.primary,
                            mb: 0.25,
                          }}
                        >
                          {project.display_name}
                        </Typography>
                        <Chip
                          label={project.type}
                          size="small"
                          sx={{
                            height: 20,
                            fontSize: '0.65rem',
                            backgroundColor: alpha(
                              project.type === 'workflow'
                                ? theme.palette.info.main
                                : theme.palette.success.main,
                              0.1
                            ),
                            color: project.type === 'workflow'
                              ? theme.palette.info.main
                              : theme.palette.success.main,
                          }}
                        />
                      </Box>
                    </Box>
                    <Typography
                      component="div"
                    >
                      <Tooltip
                        title={project.description || 'No description available'}
                        arrow
                        placement="top"
                      >
                        <Typography
                          variant="body2"
                          sx={{
                            color: theme.palette.text.secondary,
                            display: '-webkit-box',
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: 'vertical',
                            overflow: 'hidden',
                            lineHeight: 1.5,
                          }}
                        >
                          {project.description || 'No description available'}
                        </Typography>
                      </Tooltip>
                    </Typography>
                  </CardContent>
                </Card>
              </motion.div>
            </Grid>
          ))}
        </Grid>
      </motion.div>
    </Box>
  );
};

export default SearchView;
