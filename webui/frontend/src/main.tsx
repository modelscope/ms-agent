import React from 'react'
import ReactDOM from 'react-dom/client'
import { ThemeProvider as MuiThemeProvider, CssBaseline } from '@mui/material'
import App from './App'
import { ThemeProvider, useThemeContext } from './context/ThemeContext'
import { SessionProvider } from './context/SessionContext'

const ThemedApp: React.FC = () => {
  const { theme } = useThemeContext();
  
  return (
    <MuiThemeProvider theme={theme}>
      <CssBaseline />
      <SessionProvider>
        <App />
      </SessionProvider>
    </MuiThemeProvider>
  );
};

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <ThemedApp />
    </ThemeProvider>
  </React.StrictMode>,
)
