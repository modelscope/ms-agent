import React, { createContext, useContext, useState, useMemo, ReactNode } from 'react';
import { createTheme, Theme, PaletteMode } from '@mui/material';

// Luxury color palettes
const darkPalette = {
  primary: {
    main: '#C9A962',  // Gold accent
    light: '#E5D4A1',
    dark: '#A08840',
    contrastText: '#0A0A0A',
  },
  secondary: {
    main: '#6B7280',
    light: '#9CA3AF',
    dark: '#4B5563',
    contrastText: '#FFFFFF',
  },
  background: {
    default: '#0A0A0A',
    paper: '#141414',
  },
  text: {
    primary: '#F5F5F5',
    secondary: '#A0A0A0',
  },
  divider: 'rgba(201, 169, 98, 0.12)',
  error: {
    main: '#EF4444',
    light: '#F87171',
    dark: '#DC2626',
  },
  success: {
    main: '#10B981',
    light: '#34D399',
    dark: '#059669',
  },
  warning: {
    main: '#F59E0B',
    light: '#FBBF24',
    dark: '#D97706',
  },
  info: {
    main: '#3B82F6',
    light: '#60A5FA',
    dark: '#2563EB',
  },
};

const lightPalette = {
  primary: {
    main: '#1A1A1A',
    light: '#404040',
    dark: '#0A0A0A',
    contrastText: '#FFFFFF',
  },
  secondary: {
    main: '#C9A962',
    light: '#E5D4A1',
    dark: '#A08840',
    contrastText: '#0A0A0A',
  },
  background: {
    default: '#FAFAFA',
    paper: '#FFFFFF',
  },
  text: {
    primary: '#1A1A1A',
    secondary: '#6B7280',
  },
  divider: 'rgba(0, 0, 0, 0.08)',
  error: {
    main: '#DC2626',
    light: '#EF4444',
    dark: '#B91C1C',
  },
  success: {
    main: '#059669',
    light: '#10B981',
    dark: '#047857',
  },
  warning: {
    main: '#D97706',
    light: '#F59E0B',
    dark: '#B45309',
  },
  info: {
    main: '#2563EB',
    light: '#3B82F6',
    dark: '#1D4ED8',
  },
};

const createAppTheme = (mode: PaletteMode): Theme => {
  const palette = mode === 'dark' ? darkPalette : lightPalette;
  
  return createTheme({
    palette: {
      mode,
      ...palette,
    },
    typography: {
      fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
      h1: {
        fontSize: '3rem',
        fontWeight: 600,
        letterSpacing: '-0.02em',
      },
      h2: {
        fontSize: '2.25rem',
        fontWeight: 600,
        letterSpacing: '-0.02em',
      },
      h3: {
        fontSize: '1.875rem',
        fontWeight: 600,
        letterSpacing: '-0.01em',
      },
      h4: {
        fontSize: '1.5rem',
        fontWeight: 600,
      },
      h5: {
        fontSize: '1.25rem',
        fontWeight: 500,
      },
      h6: {
        fontSize: '1rem',
        fontWeight: 500,
      },
      body1: {
        fontSize: '1rem',
        lineHeight: 1.6,
      },
      body2: {
        fontSize: '0.875rem',
        lineHeight: 1.5,
      },
      button: {
        textTransform: 'none',
        fontWeight: 500,
      },
    },
    shape: {
      borderRadius: 12,
    },
    components: {
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            padding: '10px 24px',
            fontSize: '0.875rem',
            fontWeight: 500,
            boxShadow: 'none',
            '&:hover': {
              boxShadow: 'none',
            },
          },
          contained: {
            '&:hover': {
              transform: 'translateY(-1px)',
              transition: 'transform 0.2s ease',
            },
          },
          outlined: {
            borderWidth: 1.5,
            '&:hover': {
              borderWidth: 1.5,
            },
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
          },
          elevation1: {
            boxShadow: mode === 'dark' 
              ? '0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)'
              : '0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04)',
          },
          elevation2: {
            boxShadow: mode === 'dark'
              ? '0 4px 6px rgba(0,0,0,0.3), 0 2px 4px rgba(0,0,0,0.2)'
              : '0 4px 6px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.04)',
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 16,
            border: `1px solid ${palette.divider}`,
          },
        },
      },
      MuiTextField: {
        styleOverrides: {
          root: {
            '& .MuiOutlinedInput-root': {
              borderRadius: 10,
              '&:hover .MuiOutlinedInput-notchedOutline': {
                borderColor: palette.primary.main,
              },
            },
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: {
            borderRadius: 6,
            fontWeight: 500,
          },
        },
      },
      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            backgroundColor: mode === 'dark' ? '#2D2D2D' : '#1A1A1A',
            fontSize: '0.75rem',
            padding: '8px 12px',
            borderRadius: 6,
          },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: {
            borderRadius: 20,
          },
        },
      },
      MuiDrawer: {
        styleOverrides: {
          paper: {
            borderRight: `1px solid ${palette.divider}`,
          },
        },
      },
    },
  });
};

interface ThemeContextType {
  mode: PaletteMode;
  theme: Theme;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export const ThemeProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [mode, setMode] = useState<PaletteMode>(() => {
    const stored = localStorage.getItem('theme-mode');
    return (stored as PaletteMode) || 'dark';
  });
  
  const theme = useMemo(() => createAppTheme(mode), [mode]);
  
  const toggleTheme = () => {
    const newMode = mode === 'dark' ? 'light' : 'dark';
    setMode(newMode);
    localStorage.setItem('theme-mode', newMode);
  };
  
  return (
    <ThemeContext.Provider value={{ mode, theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useThemeContext = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useThemeContext must be used within a ThemeProvider');
  }
  return context;
};
