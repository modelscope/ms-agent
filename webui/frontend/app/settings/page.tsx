'use client';

import { useState, useEffect } from 'react';
import { Save, Moon, Sun, Loader2 } from 'lucide-react';
import { useGlobal } from '@/context/GlobalContext';
import { configAPI } from '@/lib/api';
import type { LLMConfig } from '@/types/api';

export default function SettingsPage() {
  const { theme, setTheme } = useGlobal();
  const [llmConfig, setLLMConfig] = useState<LLMConfig>({
    provider: 'openai',
    model: 'qwen-plus',
    api_key: '',
    base_url: '',
    temperature: 0.7,
    temperature_enabled: false,
    max_tokens: 4096,
  });
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');
  
  // Load LLM config on mount
  useEffect(() => {
    const loadConfig = async () => {
      const response = await configAPI.getLLM();
      if (response.success && response.data) {
        setLLMConfig(response.data);
      }
    };
    loadConfig();
  }, []);
  
  const handleSave = async () => {
    setIsSaving(true);
    setSaveMessage('');
    
    const response = await configAPI.saveLLM(llmConfig);
    
    if (response.success) {
      setSaveMessage('Configuration saved successfully!');
    } else {
      setSaveMessage(`Error: ${response.error || 'Failed to save configuration'}`);
    }
    
    setIsSaving(false);
    setTimeout(() => setSaveMessage(''), 3000);
  };
  
  return (
    <div className="h-screen overflow-y-auto">
      <div className="max-w-4xl mx-auto px-6 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-2">
            Settings
          </h1>
          <p className="text-slate-500 dark:text-slate-400">
            Configure your MS-Agent platform settings
          </p>
        </div>
        
        {/* Theme Settings */}
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6 mb-6">
          <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100 mb-4">
            Theme
          </h2>
          <div className="flex gap-3">
            <button
              onClick={() => setTheme('light')}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg border-2 transition-all ${
                theme === 'light'
                  ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                  : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
              }`}
            >
              <Sun className="w-4 h-4" />
              Light
            </button>
            <button
              onClick={() => setTheme('dark')}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg border-2 transition-all ${
                theme === 'dark'
                  ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                  : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
              }`}
            >
              <Moon className="w-4 h-4" />
              Dark
            </button>
          </div>
        </div>
        
        {/* LLM Configuration */}
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6 mb-6">
          <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100 mb-4">
            LLM Configuration
          </h2>
          
          <div className="space-y-4">
            {/* Provider */}
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                Provider
              </label>
              <select
                value={llmConfig.provider}
                onChange={(e) => setLLMConfig({ ...llmConfig, provider: e.target.value })}
                className="w-full px-3 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
              >
                <option value="openai">OpenAI</option>
                <option value="dashscope">DashScope</option>
                <option value="anthropic">Anthropic</option>
              </select>
            </div>
            
            {/* Model */}
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                Model
              </label>
              <input
                type="text"
                value={llmConfig.model}
                onChange={(e) => setLLMConfig({ ...llmConfig, model: e.target.value })}
                placeholder="e.g., qwen-plus, gpt-4"
                className="w-full px-3 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
              />
            </div>
            
            {/* API Key */}
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                API Key
              </label>
              <input
                type="password"
                value={llmConfig.api_key || ''}
                onChange={(e) => setLLMConfig({ ...llmConfig, api_key: e.target.value })}
                placeholder="Enter your API key"
                className="w-full px-3 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
              />
            </div>
            
            {/* Base URL */}
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                Base URL (Optional)
              </label>
              <input
                type="text"
                value={llmConfig.base_url || ''}
                onChange={(e) => setLLMConfig({ ...llmConfig, base_url: e.target.value })}
                placeholder="https://api.openai.com/v1"
                className="w-full px-3 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
              />
            </div>
            
            {/* Temperature */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                  Temperature: {llmConfig.temperature}
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={llmConfig.temperature_enabled}
                    onChange={(e) => setLLMConfig({ ...llmConfig, temperature_enabled: e.target.checked })}
                    className="rounded border-slate-300 dark:border-slate-600"
                  />
                  <span className="text-slate-600 dark:text-slate-400">Enable</span>
                </label>
              </div>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={llmConfig.temperature || 0.7}
                onChange={(e) => setLLMConfig({ ...llmConfig, temperature: parseFloat(e.target.value) })}
                disabled={!llmConfig.temperature_enabled}
                className="w-full"
              />
            </div>
            
            {/* Max Tokens */}
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                Max Tokens
              </label>
              <input
                type="number"
                value={llmConfig.max_tokens || 4096}
                onChange={(e) => setLLMConfig({ ...llmConfig, max_tokens: parseInt(e.target.value) })}
                className="w-full px-3 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
              />
            </div>
          </div>
        </div>
        
        {/* Save Button */}
        <div className="flex items-center justify-between">
          <div>
            {saveMessage && (
              <p className={`text-sm ${saveMessage.includes('Error') ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}`}>
                {saveMessage}
              </p>
            )}
          </div>
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="flex items-center gap-2 px-6 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isSaving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {isSaving ? 'Saving...' : 'Save Configuration'}
          </button>
        </div>
      </div>
    </div>
  );
}
