'use client';

import { useState, useEffect, useRef } from 'react';
import { Send, Loader2, Bot, User, Plus, ChevronDown } from 'lucide-react';
import { useGlobal } from '@/context/GlobalContext';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

export default function HomePage() {
  const { agentState, setAgentState, createSession, sendMessage, newSession, projects } = useGlobal();
  const [inputMessage, setInputMessage] = useState('');
  const [showProjectSelector, setShowProjectSelector] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  
  const hasMessages = agentState.messages.length > 0;
  
  // Auto-scroll to bottom
  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [agentState.messages]);
  
  const handleSend = async () => {
    if (!inputMessage.trim() || agentState.isLoading) return;
    
    // Create session if not exists
    if (!agentState.sessionId) {
      const projectId = agentState.selectedProject || 'chat';
      await createSession(projectId, inputMessage);
    }
    
    sendMessage(inputMessage);
    setInputMessage('');
  };
  
  const handleNewChat = () => {
    newSession();
    setInputMessage('');
  };
  
  const handleProjectSelect = async (projectId: string) => {
    setAgentState(prev => ({ ...prev, selectedProject: projectId }));
    setShowProjectSelector(false);
    
    // Create new session with selected project
    if (agentState.messages.length === 0) {
      await createSession(projectId);
    }
  };
  
  return (
    <div className="h-screen flex flex-col animate-fade-in">
      {/* Empty State */}
      {!hasMessages && (
        <div className="flex-1 flex flex-col items-center justify-center px-6">
          <div className="text-center max-w-2xl mx-auto mb-8">
            <div className="flex items-center justify-center gap-4 mb-3">
              <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white font-bold text-2xl shadow-lg">
                MS
              </div>
              <h1 className="text-4xl font-bold text-slate-900 dark:text-slate-100 tracking-tight">
                Welcome to MS-Agent
              </h1>
            </div>
            <p className="text-lg text-slate-500 dark:text-slate-400">
              Multi-Agent Framework for Complex Tasks
            </p>
          </div>
          
          {/* Input Box */}
          <div className="w-full max-w-2xl mx-auto">
            {/* Project Selector */}
            <div className="mb-3 px-1">
              <div className="relative">
                <button
                  onClick={() => setShowProjectSelector(!showProjectSelector)}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                >
                  <span>
                    Project: {agentState.selectedProject || 'Chat'}
                  </span>
                  <ChevronDown className="w-3.5 h-3.5" />
                </button>
                
                {showProjectSelector && (
                  <div className="absolute top-full left-0 mt-2 w-64 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-xl shadow-slate-200/50 dark:shadow-slate-900/50 z-50 max-h-80 overflow-y-auto">
                    <div className="p-2">
                      <button
                        onClick={() => handleProjectSelect('chat')}
                        className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 text-sm"
                      >
                        <div className="font-medium text-slate-900 dark:text-slate-100">Chat</div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">Simple chat mode</div>
                      </button>
                      {projects.map((project) => (
                        <button
                          key={project.id}
                          onClick={() => handleProjectSelect(project.id)}
                          className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 text-sm"
                        >
                          <div className="font-medium text-slate-900 dark:text-slate-100">{project.display_name}</div>
                          <div className="text-xs text-slate-500 dark:text-slate-400">{project.description}</div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
            
            {/* Input Field */}
            <div className="relative">
              <input
                ref={inputRef}
                type="text"
                className="w-full px-5 py-4 pr-14 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all placeholder:text-slate-400 dark:placeholder:text-slate-500 text-slate-700 dark:text-slate-200 shadow-lg shadow-slate-200/50 dark:shadow-slate-900/50"
                placeholder="Ask anything..."
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                disabled={agentState.isLoading}
              />
              <button
                onClick={handleSend}
                disabled={agentState.isLoading || !inputMessage.trim()}
                className="absolute right-2 top-2 bottom-2 aspect-square bg-blue-600 text-white rounded-xl flex items-center justify-center hover:bg-blue-700 disabled:opacity-50 disabled:hover:bg-blue-600 transition-all shadow-md shadow-blue-500/20"
              >
                {agentState.isLoading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <Send className="w-5 h-5" />
                )}
              </button>
            </div>
          </div>
        </div>
      )}
      
      {/* Chat Interface */}
      {hasMessages && (
        <>
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-3 border-b border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-800/80 backdrop-blur-sm">
            <div className="flex items-center gap-3">
              <div className="text-sm font-medium text-slate-600 dark:text-slate-400">
                Project: {agentState.selectedProject || 'Chat'}
              </div>
            </div>
            
            <button
              onClick={handleNewChat}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-500 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded-lg transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              New Chat
            </button>
          </div>
          
          {/* Messages Area */}
          <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
            {agentState.messages.map((msg, idx) => (
              <div
                key={idx}
                className="flex gap-4 w-full max-w-4xl mx-auto animate-in fade-in slide-in-from-bottom-2"
              >
                {msg.role === 'user' ? (
                  <>
                    <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center shrink-0">
                      <User className="w-4 h-4 text-slate-500 dark:text-slate-400" />
                    </div>
                    <div className="flex-1 bg-slate-100 dark:bg-slate-700 px-4 py-3 rounded-2xl rounded-tl-none text-slate-800 dark:text-slate-200">
                      {msg.content}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shrink-0 shadow-lg shadow-blue-500/30">
                      <Bot className="w-4 h-4 text-white" />
                    </div>
                    <div className="flex-1 space-y-3">
                      <div className="bg-white dark:bg-slate-800 px-5 py-4 rounded-2xl rounded-tl-none border border-slate-200 dark:border-slate-700 shadow-sm">
                        <div className="prose prose-slate dark:prose-invert prose-sm max-w-none">
                          <ReactMarkdown
                            remarkPlugins={[remarkMath]}
                            rehypePlugins={[rehypeKatex]}
                          >
                            {msg.content}
                          </ReactMarkdown>
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </div>
            ))}
            
            {/* Loading indicator */}
            {agentState.isLoading && agentState.currentStage && (
              <div className="flex gap-4 w-full max-w-4xl mx-auto">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shrink-0">
                  <Loader2 className="w-4 h-4 text-white animate-spin" />
                </div>
                <div className="flex-1 bg-slate-100 dark:bg-slate-800 px-4 py-3 rounded-2xl rounded-tl-none">
                  <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300 text-sm">
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
                    </span>
                    {agentState.currentStage}
                  </div>
                </div>
              </div>
            )}
            
            <div ref={chatEndRef} />
          </div>
          
          {/* Input Area */}
          <div className="border-t border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-6 py-4">
            <div className="max-w-4xl mx-auto relative">
              <input
                ref={inputRef}
                type="text"
                className="w-full px-5 py-3.5 pr-14 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all placeholder:text-slate-400 dark:placeholder:text-slate-500 text-slate-700 dark:text-slate-200"
                placeholder="Type your message..."
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                disabled={agentState.isLoading}
              />
              <button
                onClick={handleSend}
                disabled={agentState.isLoading || !inputMessage.trim()}
                className="absolute right-2 top-2 bottom-2 aspect-square bg-blue-600 text-white rounded-lg flex items-center justify-center hover:bg-blue-700 disabled:opacity-50 disabled:hover:bg-blue-600 transition-all"
              >
                {agentState.isLoading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <Send className="w-5 h-5" />
                )}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
