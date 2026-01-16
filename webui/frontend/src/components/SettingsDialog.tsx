import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Box,
  Typography,
  Tabs,
  Tab,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Slider,
  IconButton,
  Divider,
  Paper,
  useTheme,
  Alert,
  Chip,
  Tooltip,
} from '@mui/material';
import {
  Close as CloseIcon,
  Add as AddIcon,
  Delete as DeleteIcon,
  Save as SaveIcon,
} from '@mui/icons-material';

interface SettingsDialogProps {
  open: boolean;
  onClose: () => void;
}

interface LLMConfig {
  provider: string;
  model: string;
  api_key: string;
  base_url: string;
  temperature: number;
  max_tokens: number;
}

interface MCPServer {
  type: 'stdio' | 'sse';
  command?: string;
  args?: string[];
  url?: string;
  env?: Record<string, string>;
}

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

const TabPanel: React.FC<TabPanelProps> = ({ children, value, index }) => (
  <div hidden={value !== index} style={{ paddingTop: 16 }}>
    {value === index && children}
  </div>
);

const SettingsDialog: React.FC<SettingsDialogProps> = ({ open, onClose }) => {
  const theme = useTheme();
  const [tabValue, setTabValue] = useState(0);
  const [llmConfig, setLlmConfig] = useState<LLMConfig>({
    provider: 'modelscope',
    model: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
    api_key: '',
    base_url: 'https://api-inference.modelscope.cn/v1/',
    temperature: 0.7,
    max_tokens: 4096,
  });
  const [mcpServers, setMcpServers] = useState<Record<string, MCPServer>>({});
  const [newServerName, setNewServerName] = useState('');
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  // Load config on mount
  useEffect(() => {
    if (open) {
      loadConfig();
    }
  }, [open]);

  const loadConfig = async () => {
    try {
      const [llmRes, mcpRes] = await Promise.all([
        fetch('/api/config/llm'),
        fetch('/api/config/mcp'),
      ]);
      
      if (llmRes.ok) {
        const data = await llmRes.json();
        setLlmConfig(data);
      }
      
      if (mcpRes.ok) {
        const data = await mcpRes.json();
        setMcpServers(data.mcpServers || {});
      }
    } catch (error) {
      console.error('Failed to load config:', error);
    }
  };

  const handleSave = async () => {
    setSaveStatus('saving');
    try {
      const llmRes = await fetch('/api/config/llm', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(llmConfig),
      });
      
      const mcpRes = await fetch('/api/config/mcp', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mcpServers: mcpServers }),
      });
      
      if (llmRes.ok && mcpRes.ok) {
        setSaveStatus('saved');
        setTimeout(() => setSaveStatus('idle'), 2000);
      } else {
        setSaveStatus('error');
      }
    } catch (error) {
      setSaveStatus('error');
    }
  };

  const handleAddMCPServer = () => {
    if (!newServerName.trim()) return;
    
    setMcpServers((prev) => ({
      ...prev,
      [newServerName]: { type: 'sse', url: '' },
    }));
    setNewServerName('');
  };

  const handleRemoveMCPServer = (name: string) => {
    setMcpServers((prev) => {
      const newServers = { ...prev };
      delete newServers[name];
      return newServers;
    });
  };

  const handleMCPServerChange = (name: string, field: keyof MCPServer, value: any) => {
    setMcpServers((prev) => ({
      ...prev,
      [name]: { ...prev[name], [field]: value },
    }));
  };

  const providers = [
    { value: 'modelscope', label: 'ModelScope', baseUrl: 'https://api-inference.modelscope.cn/v1/' },
    { value: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1/' },
    { value: 'anthropic', label: 'Anthropic', baseUrl: 'https://api.anthropic.com/v1/' },
    { value: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1/' },
    { value: 'custom', label: 'Custom', baseUrl: '' },
  ];

  const models: Record<string, string[]> = {
    modelscope: ['Qwen/Qwen3-235B-A22B-Instruct-2507', 'Qwen/Qwen2.5-72B-Instruct', 'Qwen/Qwen2.5-32B-Instruct'],
    openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'],
    anthropic: ['claude-3-5-sonnet-20241022', 'claude-3-opus-20240229'],
    deepseek: ['deepseek-chat', 'deepseek-coder'],
    custom: [],
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      PaperProps={{
        sx: {
          borderRadius: 3,
          backgroundColor: theme.palette.background.paper,
        },
      }}
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography variant="h6" fontWeight={600}>Settings</Typography>
        <IconButton onClick={onClose} size="small">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      
      <Divider />
      
      <DialogContent sx={{ minHeight: 400 }}>
        <Tabs
          value={tabValue}
          onChange={(_, v) => setTabValue(v)}
          sx={{ borderBottom: 1, borderColor: 'divider' }}
        >
          <Tab label="LLM Configuration" />
          <Tab label="MCP Servers" />
        </Tabs>

        {/* LLM Configuration Tab */}
        <TabPanel value={tabValue} index={0}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <FormControl fullWidth>
              <InputLabel>Provider</InputLabel>
              <Select
                value={llmConfig.provider}
                label="Provider"
                onChange={(e) => {
                  const provider = e.target.value;
                  const providerInfo = providers.find((p) => p.value === provider);
                  setLlmConfig((prev) => ({
                    ...prev,
                    provider,
                    base_url: providerInfo?.baseUrl || '',
                    model: models[provider]?.[0] || '',
                  }));
                }}
              >
                {providers.map((p) => (
                  <MenuItem key={p.value} value={p.value}>{p.label}</MenuItem>
                ))}
              </Select>
            </FormControl>

            <FormControl fullWidth>
              <InputLabel>Model</InputLabel>
              <Select
                value={llmConfig.model}
                label="Model"
                onChange={(e) => setLlmConfig((prev) => ({ ...prev, model: e.target.value }))}
              >
                {models[llmConfig.provider]?.map((m) => (
                  <MenuItem key={m} value={m}>{m}</MenuItem>
                ))}
                {llmConfig.provider === 'custom' && (
                  <MenuItem value={llmConfig.model}>{llmConfig.model || 'Enter custom model'}</MenuItem>
                )}
              </Select>
            </FormControl>

            {llmConfig.provider === 'custom' && (
              <TextField
                fullWidth
                label="Custom Model Name"
                value={llmConfig.model}
                onChange={(e) => setLlmConfig((prev) => ({ ...prev, model: e.target.value }))}
              />
            )}

            <TextField
              fullWidth
              label="API Key"
              type="password"
              value={llmConfig.api_key}
              onChange={(e) => setLlmConfig((prev) => ({ ...prev, api_key: e.target.value }))}
              helperText={
                llmConfig.provider === 'modelscope'
                  ? 'Get your API key from https://modelscope.cn/my/myaccesstoken'
                  : undefined
              }
            />

            <TextField
              fullWidth
              label="Base URL"
              value={llmConfig.base_url}
              onChange={(e) => setLlmConfig((prev) => ({ ...prev, base_url: e.target.value }))}
            />

            <Box>
              <Typography gutterBottom>Temperature: {llmConfig.temperature}</Typography>
              <Slider
                value={llmConfig.temperature}
                onChange={(_, v) => setLlmConfig((prev) => ({ ...prev, temperature: v as number }))}
                min={0}
                max={2}
                step={0.1}
                marks={[
                  { value: 0, label: '0' },
                  { value: 1, label: '1' },
                  { value: 2, label: '2' },
                ]}
              />
            </Box>

            <TextField
              fullWidth
              label="Max Tokens"
              type="number"
              value={llmConfig.max_tokens}
              onChange={(e) => setLlmConfig((prev) => ({ ...prev, max_tokens: parseInt(e.target.value) || 4096 }))}
            />
          </Box>
        </TabPanel>

        {/* MCP Servers Tab */}
        <TabPanel value={tabValue} index={1}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Alert severity="info" sx={{ mb: 1 }}>
              Configure MCP (Model Context Protocol) servers to extend agent capabilities with additional tools.
            </Alert>
            
            {/* Add new server */}
            <Box sx={{ display: 'flex', gap: 1 }}>
              <TextField
                size="small"
                placeholder="Server name"
                value={newServerName}
                onChange={(e) => setNewServerName(e.target.value)}
                sx={{ flex: 1 }}
              />
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                onClick={handleAddMCPServer}
                disabled={!newServerName.trim()}
              >
                Add Server
              </Button>
            </Box>

            {/* Server list */}
            {Object.entries(mcpServers).map(([name, server]) => (
              <Paper
                key={name}
                variant="outlined"
                sx={{ p: 2, borderRadius: 2 }}
              >
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                  <Typography variant="subtitle1" fontWeight={500}>
                    {name}
                  </Typography>
                  <Tooltip title="Remove server">
                    <IconButton
                      size="small"
                      color="error"
                      onClick={() => handleRemoveMCPServer(name)}
                    >
                      <DeleteIcon />
                    </IconButton>
                  </Tooltip>
                </Box>

                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <FormControl size="small">
                    <InputLabel>Type</InputLabel>
                    <Select
                      value={server.type}
                      label="Type"
                      onChange={(e) => handleMCPServerChange(name, 'type', e.target.value)}
                    >
                      <MenuItem value="sse">SSE (Server-Sent Events)</MenuItem>
                      <MenuItem value="stdio">STDIO (Command Line)</MenuItem>
                    </Select>
                  </FormControl>

                  {server.type === 'sse' ? (
                    <TextField
                      size="small"
                      label="URL"
                      placeholder="https://example.com/mcp"
                      value={server.url || ''}
                      onChange={(e) => handleMCPServerChange(name, 'url', e.target.value)}
                    />
                  ) : (
                    <>
                      <TextField
                        size="small"
                        label="Command"
                        placeholder="npx"
                        value={server.command || ''}
                        onChange={(e) => handleMCPServerChange(name, 'command', e.target.value)}
                      />
                      <TextField
                        size="small"
                        label="Arguments (comma-separated)"
                        placeholder="-y, @modelscope/mcp-server"
                        value={(server.args || []).join(', ')}
                        onChange={(e) => handleMCPServerChange(name, 'args', e.target.value.split(',').map((s) => s.trim()))}
                      />
                    </>
                  )}
                </Box>
              </Paper>
            ))}

            {Object.keys(mcpServers).length === 0 && (
              <Box
                sx={{
                  textAlign: 'center',
                  py: 4,
                  color: 'text.secondary',
                }}
              >
                <Typography>No MCP servers configured</Typography>
                <Typography variant="body2">
                  Add a server above to get started
                </Typography>
              </Box>
            )}
          </Box>
        </TabPanel>
      </DialogContent>
      
      <Divider />
      
      <DialogActions sx={{ p: 2, gap: 1 }}>
        {saveStatus === 'saved' && (
          <Chip label="Saved!" color="success" size="small" />
        )}
        {saveStatus === 'error' && (
          <Chip label="Error saving" color="error" size="small" />
        )}
        <Box sx={{ flex: 1 }} />
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          startIcon={<SaveIcon />}
          onClick={handleSave}
          disabled={saveStatus === 'saving'}
        >
          {saveStatus === 'saving' ? 'Saving...' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default SettingsDialog;
