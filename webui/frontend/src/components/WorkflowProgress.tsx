import React from 'react';
import { Box, Typography, Chip, useTheme, alpha, LinearProgress } from '@mui/material';
import { CheckCircle as CheckIcon, RadioButtonUnchecked as PendingIcon } from '@mui/icons-material';
import { motion } from 'framer-motion';
import { WorkflowProgress as WorkflowProgressType } from '../context/SessionContext';

interface WorkflowProgressProps {
  progress: WorkflowProgressType;
}

const WorkflowProgress: React.FC<WorkflowProgressProps> = ({ progress }) => {
  const theme = useTheme();
  const { steps, step_status } = progress;

  // Calculate progress based on completed steps
  const completedCount = steps.filter(s => step_status[s] === 'completed').length;
  const runningCount = steps.filter(s => step_status[s] === 'running').length;
  const progressPercent = steps.length > 0 ? ((completedCount + runningCount * 0.5) / steps.length) * 100 : 0;

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
      <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
        Workflow:
      </Typography>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        {steps.map((step, index) => {
          const status = step_status[step] || 'pending';
          const isCompleted = status === 'completed';
          const isCurrent = status === 'running';

          return (
            <motion.div
              key={step}
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ delay: index * 0.1 }}
            >
              <Chip
                size="small"
                icon={isCompleted ? <CheckIcon fontSize="small" /> : isCurrent ? undefined : <PendingIcon fontSize="small" />}
                label={step.replace(/_/g, ' ')}
                sx={{
                  height: 24,
                  fontSize: '0.7rem',
                  backgroundColor: isCompleted
                    ? alpha(theme.palette.success.main, 0.1)
                    : isCurrent
                    ? alpha(theme.palette.info.main, 0.15)
                    : alpha(theme.palette.action.disabled, 0.1),
                  color: isCompleted
                    ? theme.palette.success.main
                    : isCurrent
                    ? theme.palette.info.main
                    : theme.palette.text.secondary,
                  border: isCurrent ? `1px solid ${theme.palette.info.main}` : 'none',
                  '& .MuiChip-icon': {
                    color: 'inherit',
                  },
                }}
              />
            </motion.div>
          );
        })}
      </Box>

      <Box sx={{ width: 100, ml: 1 }}>
        <LinearProgress
          variant="determinate"
          value={progressPercent}
          sx={{
            height: 4,
            borderRadius: 2,
            backgroundColor: alpha(theme.palette.primary.main, 0.1),
            '& .MuiLinearProgress-bar': {
              borderRadius: 2,
              background: `linear-gradient(90deg, ${theme.palette.primary.main}, ${theme.palette.primary.light})`,
            },
          }}
        />
      </Box>
    </Box>
  );
};

export default WorkflowProgress;
