'use client';

import { useState, useEffect } from 'react';
import { Activity, Clock, CheckCircle, XCircle, RefreshCw } from 'lucide-react';
import { sessionAPI, healthAPI } from '@/lib/api';
import type { SessionInfo } from '@/types/api';

export default function MonitorPage() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [healthStatus, setHealthStatus] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);
  
  const loadData = async () => {
    setIsLoading(true);
    
    // Load sessions
    const sessionsResponse = await sessionAPI.list();
    if (sessionsResponse.success && sessionsResponse.data) {
      setSessions(sessionsResponse.data);
    }
    
    // Load health status
    const healthResponse = await healthAPI.check();
    if (healthResponse.success) {
      setHealthStatus(healthResponse.data);
    }
    
    setIsLoading(false);
  };
  
  useEffect(() => {
    loadData();
    
    // Auto-refresh every 10 seconds
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  }, []);
  
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'text-green-600 dark:text-green-400 bg-green-100 dark:bg-green-900/30';
      case 'running':
        return 'text-blue-600 dark:text-blue-400 bg-blue-100 dark:bg-blue-900/30';
      case 'error':
        return 'text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-900/30';
      default:
        return 'text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-slate-700';
    }
  };
  
  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-4 h-4" />;
      case 'running':
        return <Activity className="w-4 h-4 animate-pulse" />;
      case 'error':
        return <XCircle className="w-4 h-4" />;
      default:
        return <Clock className="w-4 h-4" />;
    }
  };
  
  return (
    <div className="h-screen overflow-y-auto">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-2">
              System Monitor
            </h1>
            <p className="text-slate-500 dark:text-slate-400">
              Monitor system status and session activity
            </p>
          </div>
          <button
            onClick={loadData}
            disabled={isLoading}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
        
        {/* Health Status */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-slate-600 dark:text-slate-400">
                API Status
              </h3>
              <Activity className="w-5 h-5 text-green-600 dark:text-green-400" />
            </div>
            <p className="text-2xl font-bold text-slate-900 dark:text-slate-100">
              {healthStatus?.status === 'healthy' ? 'Healthy' : 'Unknown'}
            </p>
          </div>
          
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-slate-600 dark:text-slate-400">
                Total Sessions
              </h3>
              <Activity className="w-5 h-5 text-blue-600 dark:text-blue-400" />
            </div>
            <p className="text-2xl font-bold text-slate-900 dark:text-slate-100">
              {sessions.length}
            </p>
          </div>
          
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-slate-600 dark:text-slate-400">
                Active Sessions
              </h3>
              <Activity className="w-5 h-5 text-orange-600 dark:text-orange-400" />
            </div>
            <p className="text-2xl font-bold text-slate-900 dark:text-slate-100">
              {sessions.filter(s => s.status === 'running').length}
            </p>
          </div>
        </div>
        
        {/* Sessions List */}
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700">
            <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
              Recent Sessions
            </h2>
          </div>
          
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-50 dark:bg-slate-700/50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                    Session ID
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                    Project
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                {sessions.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-6 py-8 text-center text-slate-500 dark:text-slate-400">
                      No sessions found
                    </td>
                  </tr>
                ) : (
                  sessions.map((session) => (
                    <tr key={session.id} className="hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors">
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-slate-900 dark:text-slate-100">
                        {session.id.slice(0, 8)}...
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600 dark:text-slate-400">
                        {session.project_name}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${getStatusColor(session.status)}`}>
                          {getStatusIcon(session.status)}
                          {session.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600 dark:text-slate-400">
                        {new Date(session.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
