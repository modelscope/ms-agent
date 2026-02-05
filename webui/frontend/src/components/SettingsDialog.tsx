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
  Autocomplete,
  Switch,
  FormControlLabel,
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
  temperature?: number | null;
  temperature_enabled?: boolean;
  max_tokens?: number | null;
}

interface EditFileConfig {
  api_key: string;
  base_url: string;
  diff_model: string;
}

interface EdgeOnePagesConfig {
  api_token: string;
  project_name?: string;
}

interface SearchKeysConfig {
  exa_api_key: string;
  serpapi_api_key: string;
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
    temperature: null,
    temperature_enabled: false,
    max_tokens: null,
  });
  const [temperatureEnabled, setTemperatureEnabled] = useState(false);
  const [editFileConfig, setEditFileConfig] = useState<EditFileConfig>({
    api_key: '',
    base_url: 'https://api.morphllm.com/v1',
    diff_model: 'morph-v3-fast',
  });
  const [edgeOnePagesConfig, setEdgeOnePagesConfig] = useState<EdgeOnePagesConfig>({
    api_token: '',
    project_name: '',
  });
  const [searchKeysConfig, setSearchKeysConfig] = useState<SearchKeysConfig>({
    exa_api_key: '',
    serpapi_api_key: '',
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
      const [llmRes, mcpRes, editFileRes, edgeOnePagesRes, searchKeysRes] = await Promise.all([
        fetch('/api/config/llm'),
        fetch('/api/config/mcp'),
        fetch('/api/config/edit_file'),
        fetch('/api/config/edgeone_pages'),
        fetch('/api/config/search_keys'),
      ]);

      if (llmRes.ok) {
        const data = await llmRes.json();
        const enabled = Boolean(data.temperature_enabled);
        setTemperatureEnabled(enabled);
        // Ensure temperature is between 0 and 1 when provided
        if (typeof data.temperature === 'number') {
          data.temperature = Math.max(0, Math.min(1, data.temperature));
        }
        setLlmConfig(data);
      }

      if (mcpRes.ok) {
        const data = await mcpRes.json();
        setMcpServers(data.mcpServers || {});
      }

      if (editFileRes.ok) {
        const data = await editFileRes.json();
        setEditFileConfig(data);
      }

      if (edgeOnePagesRes.ok) {
        const data = await edgeOnePagesRes.json();
        setEdgeOnePagesConfig(data);
      }

      if (searchKeysRes.ok) {
        const data = await searchKeysRes.json();
        setSearchKeysConfig(data);
      }
    } catch (error) {
      console.error('Failed to load config:', error);
    }
  };

  const handleSave = async () => {
    setSaveStatus('saving');
    try {
      const llmPayload = {
        ...llmConfig,
        temperature_enabled: temperatureEnabled,
        temperature: temperatureEnabled
          ? (typeof llmConfig.temperature === 'number' ? llmConfig.temperature : 0.7)
          : null,
      };
      const llmRes = await fetch('/api/config/llm', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(llmPayload),
      });

      const mcpRes = await fetch('/api/config/mcp', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mcpServers: mcpServers }),
      });

      const editFileRes = await fetch('/api/config/edit_file', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editFileConfig),
      });

      const edgeOnePagesRes = await fetch('/api/config/edgeone_pages', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(edgeOnePagesConfig),
      });

      const searchKeysRes = await fetch('/api/config/search_keys', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(searchKeysConfig),
      });

      if (llmRes.ok && mcpRes.ok && editFileRes.ok && edgeOnePagesRes.ok && searchKeysRes.ok) {
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
          <Tab label="Search Keys" />
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

            <Autocomplete
              freeSolo
              options={models[llmConfig.provider] || []}
              value={llmConfig.model}
              onInputChange={(_, newValue, reason) => {
                // 只在用户输入时更新（不是选择时）
                if (reason === 'input') {
                  setLlmConfig((prev) => ({ ...prev, model: newValue }));
                }
              }}
              onChange={(_, newValue) => {
                // 处理从下拉列表选择的情况
                const modelValue = typeof newValue === 'string' ? newValue : (newValue || '');
                setLlmConfig((prev) => ({ ...prev, model: modelValue }));
              }}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Model"
                  placeholder="选择或输入模型名称"
                  helperText="可以从列表中选择，也可以直接输入自定义模型名称"
                />
              )}
            />

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
              <FormControlLabel
                control={
                  <Switch
                    checked={temperatureEnabled}
                    onChange={(event) => {
                      const next = event.target.checked;
                      setTemperatureEnabled(next);
                      setLlmConfig((prev) => {
                        if (!next) {
                          return { ...prev, temperature: null };
                        }
                        if (prev.temperature == null) {
                          return { ...prev, temperature: 0.7 };
                        }
                        return prev;
                      });
                    }}
                  />
                }
                label="Enable temperature"
              />
              <Typography gutterBottom color={temperatureEnabled ? 'text.primary' : 'text.secondary'}>
                Temperature: {(typeof llmConfig.temperature === 'number' ? llmConfig.temperature : 0.7).toFixed(1)}
              </Typography>
              <Slider
                value={typeof llmConfig.temperature === 'number' ? llmConfig.temperature : 0.7}
                onChange={(_, v) => {
                  const tempValue = v as number;
                  // Ensure temperature is between 0 and 1
                  const clampedValue = Math.max(0, Math.min(1, tempValue));
                  setLlmConfig((prev) => ({ ...prev, temperature: clampedValue }));
                }}
                min={0}
                max={1}
                step={0.1}
                disabled={!temperatureEnabled}
                marks={[
                  { value: 0, label: '0' },
                  { value: 0.5, label: '0.5' },
                  { value: 1, label: '1' },
                ]}
              />
              {!temperatureEnabled && (
                <Typography variant="caption" color="text.secondary">
                  Temperature is disabled; project config will control it.
                </Typography>
              )}
            </Box>

            <TextField
              fullWidth
              label="Max Tokens"
              type="number"
              value={llmConfig.max_tokens || ''}
              onChange={(e) => {
                const value = e.target.value;
                if (value === '') {
                  setLlmConfig((prev) => ({ ...prev, max_tokens: null }));
                } else {
                  const numValue = parseInt(value, 10);
                  if (!isNaN(numValue) && numValue >= 0) {
                    setLlmConfig((prev) => ({ ...prev, max_tokens: numValue }));
                  }
                }
              }}
              onBlur={(e) => {
                if (e.target.value === '' || parseInt(e.target.value, 10) === 0) {
                  setLlmConfig((prev) => ({ ...prev, max_tokens: null }));
                }
              }}
            />

            {/* Edit File Config Section */}
            <Divider sx={{ my: 2 }} />
            <Typography variant="h6" sx={{ mb: 2, fontWeight: 600 }}>
              Edit File Configuration
            </Typography>
            <Alert severity="info" sx={{ mb: 2 }}>
              Configure the API for the edit_file tool. If no API key is provided, the edit_file tool will be disabled.
            </Alert>

            <TextField
              fullWidth
              label="API Key"
              type="password"
              value={editFileConfig.api_key}
              onChange={(e) => setEditFileConfig((prev) => ({ ...prev, api_key: e.target.value }))}
              helperText="API key for MorphLLM service (required to enable edit_file tool)"
            />

            <TextField
              fullWidth
              label="Base URL"
              value={editFileConfig.base_url}
              onChange={(e) => setEditFileConfig((prev) => ({ ...prev, base_url: e.target.value }))}
              helperText="Base URL for MorphLLM API"
            />

            <TextField
              fullWidth
              label="Diff Model"
              value={editFileConfig.diff_model}
              onChange={(e) => setEditFileConfig((prev) => ({ ...prev, diff_model: e.target.value }))}
              helperText="Model name for code diff generation (e.g., morph-v3-fast)"
            />

            {/* EdgeOne Pages Config Section */}
            <Divider sx={{ my: 2 }} />
            <Typography variant="h6" sx={{ mb: 2, fontWeight: 600 }}>
              EdgeOne Pages Configuration
            </Typography>
            <Alert severity="info" sx={{ mb: 2 }}>
              Configure EdgeOne Pages for automatic deployment. If no API token is provided, the deployment feature will be disabled.
            </Alert>

            <TextField
              fullWidth
              label="API Token"
              type="password"
              value={edgeOnePagesConfig.api_token}
              onChange={(e) => setEdgeOnePagesConfig((prev) => ({ ...prev, api_token: e.target.value }))}
              helperText="Get your API token from https://edgeone.ai/"
            />

            <TextField
              fullWidth
              label="Project Name"
              value={edgeOnePagesConfig.project_name || ''}
              onChange={(e) => setEdgeOnePagesConfig((prev) => ({ ...prev, project_name: e.target.value }))}
              helperText="Optional: Specify a custom project name for EdgeOne Pages deployment"
              sx={{ mt: 2 }}
            />
          </Box>
        </TabPanel>

        {/* Search Keys Tab */}
        <TabPanel value={tabValue} index={1}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Alert severity="info">
              Configure EXA and SerpApi keys for Deep Research search tools.
            </Alert>
            <TextField
              fullWidth
              label="EXA API Key"
              type="password"
              value={searchKeysConfig.exa_api_key}
              onChange={(e) => setSearchKeysConfig((prev) => ({ ...prev, exa_api_key: e.target.value }))}
            />
            <TextField
              fullWidth
              label="SerpApi API Key"
              type="password"
              value={searchKeysConfig.serpapi_api_key}
              onChange={(e) => setSearchKeysConfig((prev) => ({ ...prev, serpapi_api_key: e.target.value }))}
            />
          </Box>
        </TabPanel>

        {/* MCP Servers Tab */}
        <TabPanel value={tabValue} index={2}>
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
