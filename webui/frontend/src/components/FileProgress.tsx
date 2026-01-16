import React from 'react';
import { Box, Typography, Chip, useTheme, alpha, CircularProgress } from '@mui/material';
import { CheckCircle as CheckIcon } from '@mui/icons-material';
import { motion } from 'framer-motion';
import { FileProgress as FileProgressType } from '../context/SessionContext';

interface FileProgressProps {
  progress: FileProgressType;
}

const FileProgress: React.FC<FileProgressProps> = ({ progress }) => {
  const theme = useTheme();
  const { file, status } = progress;
  const isWriting = status === 'writing';

  // Extract filename from path
  const filename = file.split('/').pop() || file;

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 10 }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="caption" color="text.secondary">
          File:
        </Typography>
        <Chip
          size="small"
          icon={isWriting ? <CircularProgress size={12} /> : <CheckIcon fontSize="small" />}
          label={filename}
          sx={{
            height: 24,
            fontSize: '0.7rem',
            maxWidth: 200,
            backgroundColor: isWriting
              ? alpha(theme.palette.warning.main, 0.1)
              : alpha(theme.palette.success.main, 0.1),
            color: isWriting
              ? theme.palette.warning.main
              : theme.palette.success.main,
            '& .MuiChip-icon': {
              color: 'inherit',
            },
            '& .MuiChip-label': {
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            },
          }}
        />
      </Box>
    </motion.div>
  );
};

export default FileProgress;
