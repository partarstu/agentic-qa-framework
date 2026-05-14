import { useState } from 'react';
import { Server, Wifi, WifiOff, Loader2, RefreshCw } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { dashboardApi } from '../api/dashboardApi';
import { LogModal } from './LogModal';
import type { AgentInfo } from '../types/dashboard';

interface AgentGridProps {
  agents: AgentInfo[] | undefined;
  isLoading: boolean;
}

export function AgentGrid({ agents, isLoading }: AgentGridProps) {
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const queryClient = useQueryClient();

  const handleDiscoverAgents = async () => {
    setIsDiscovering(true);
    try {
      await dashboardApi.triggerDiscovery();
      // Invalidate agents query to refresh the list
      await queryClient.invalidateQueries({ queryKey: ['agents'] });
      // We can use a simple alert/toast here or rely on the query refresh
    } catch (error) {
      console.error('Discovery failed:', error);
    } finally {
      setIsDiscovering(false);
    }
  };

  if (isLoading) {
    return (
      <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold flex items-center gap-2">
            <Server className="w-5 h-5 text-indigo-400" />
            Agents
          </h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="bg-slate-700/50 rounded-lg p-4 animate-pulse">
              <div className="h-4 bg-slate-600 rounded w-3/4 mb-3"></div>
              <div className="h-3 bg-slate-600 rounded w-1/2"></div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'AVAILABLE':
        return 'bg-emerald-500';
      case 'BUSY':
        return 'bg-amber-500';
      case 'BROKEN':
        return 'bg-red-500';
      default:
        return 'bg-slate-500';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'AVAILABLE':
        return <Wifi className="w-4 h-4 text-emerald-400" />;
      case 'BUSY':
        return <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />;
      case 'BROKEN':
        return <WifiOff className="w-4 h-4 text-red-400" />;
      default:
        return null;
    }
  };

  return (
    <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <Server className="w-5 h-5 text-indigo-400" />
          Agents ({agents?.length || 0})
        </h2>
        
        <button
          onClick={handleDiscoverAgents}
          disabled={isDiscovering}
          className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-slate-300 bg-slate-700 hover:bg-slate-600 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          title="Discover Agents"
        >
          <RefreshCw className={`w-4 h-4 ${isDiscovering ? 'animate-spin' : ''}`} />
          <span>{isDiscovering ? 'Discovering...' : 'Discover'}</span>
        </button>
      </div>

      {(!agents || agents.length === 0) ? (
        <p className="text-slate-400 text-center py-8">No agents registered</p>
      ) : (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {agents.map((agent) => (
          <div
            key={agent.id}
            onClick={() => setSelectedAgent(agent.id)}
            className={`bg-slate-700/30 rounded-lg p-4 border border-slate-600/50 transition-all hover:border-slate-500 cursor-pointer ${
              agent.status === 'AVAILABLE' ? 'status-available' : agent.status === 'BUSY' ? 'status-busy' : ''
            }`}
          >
            <div className="flex items-start justify-between mb-2">
              <div className="flex items-center gap-2">
                <div className={`w-2.5 h-2.5 rounded-full ${getStatusColor(agent.status)}`}></div>
                <h3 className="font-medium text-slate-100 truncate">{agent.name}</h3>
              </div>
              {getStatusIcon(agent.status)}
            </div>
            
            <p className="text-xs text-slate-400 truncate mb-2" title={agent.url}>
              {agent.url}
            </p>

            {agent.current_task && (
              <div className="mt-3 p-2 bg-amber-500/10 rounded border border-amber-500/20">
                <p className="text-xs text-amber-300 font-medium">Current Task:</p>
                <p className="text-xs text-slate-300 truncate">{agent.current_task.description}</p>
              </div>
            )}

            {agent.status === 'BROKEN' && agent.broken_reason && (
              <div className="mt-3 p-2 bg-red-500/10 rounded border border-red-500/20">
                <p className="text-xs text-red-300">
                  {agent.broken_reason === 'OFFLINE' ? 'Agent is offline' : 'Task stuck'}
                </p>
              </div>
            )}
          </div>
        ))}
      </div>
      )}

      {selectedAgent && (
        <LogModal
          isOpen={true}
          onClose={() => setSelectedAgent(null)}
          agentId={selectedAgent}
          title="Agent Execution Logs"
        />
      )}
    </div>
  );
}
