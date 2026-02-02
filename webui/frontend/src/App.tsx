import React, { useState } from 'react';
import { Box } from '@mui/material';
import { AnimatePresence } from 'framer-motion';
import { useSession } from './context/SessionContext';
import SearchView from './components/SearchView';
import ConversationView from './components/ConversationView';
import { ChatView } from './components/ChatView';
import Layout from './components/Layout';

const App: React.FC = () => {
  const { currentSession } = useSession();
  const [showSettings, setShowSettings] = useState(false);
  const [showLogs, setShowLogs] = useState(false);

  return (
    <Layout
      onOpenSettings={() => setShowSettings(true)}
      onToggleLogs={() => setShowLogs(!showLogs)}
      showLogs={showLogs}
    >
      <Box
        sx={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        <AnimatePresence mode="wait">
          {currentSession ? (
            currentSession.session_type === 'chat' ? (
              <ChatView key="chat" />
            ) : (
              <ConversationView
                key="conversation"
                showLogs={showLogs}
              />
            )
          ) : (
            <SearchView key="search" />
          )}
        </AnimatePresence>
      </Box>

      {showSettings && (
        <React.Suspense fallback={null}>
          <SettingsDialogLazy
            open={showSettings}
            onClose={() => setShowSettings(false)}
          />
        </React.Suspense>
      )}
    </Layout>
  );
};

// Lazy load settings dialog
const SettingsDialogLazy = React.lazy(() => import('./components/SettingsDialog'));

export default App;
