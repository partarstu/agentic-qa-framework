// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from 'react';
import { ClipboardList, CheckCircle, XCircle, Clock, Loader2 } from 'lucide-react';
import { LogModal } from './LogModal';
import type { TaskInfo, TaskLiveState } from '../types/dashboard';

interface TaskListProps {
  tasks: TaskInfo[] | undefined;
  isLoading: boolean;
  liveTaskStates?: Record<string, TaskLiveState>;
}

export function TaskList({ tasks, isLoading, liveTaskStates }: TaskListProps) {
  const [selectedTask, setSelectedTask] = useState<string | null>(null);

  const formatDuration = (ms: number | null) => {
    if (ms === null) return '-';
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  };

  const formatTime = (isoString: string) => {
    return new Date(isoString).toLocaleTimeString();
  };

  const formatTokens = (tokens: number) => {
    if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(2)}M`;
    if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}k`;
    return `${tokens}`;
  };

  const formatCost = (cost: number | null | undefined) => {
    if (cost === null || cost === undefined) return '-';
    return `$${cost.toFixed(4)}`;
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'COMPLETED':
        return <CheckCircle className="w-4 h-4 text-emerald-400" />;
      case 'FAILED':
        return <XCircle className="w-4 h-4 text-red-400" />;
      case 'RUNNING':
        return <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />;
      default:
        return <Clock className="w-4 h-4 text-slate-400" />;
    }
  };

  const getStatusBadgeClass = (status: string) => {
    switch (status) {
      case 'COMPLETED':
        return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
      case 'FAILED':
        return 'bg-red-500/20 text-red-400 border-red-500/30';
      case 'RUNNING':
        return 'bg-amber-500/20 text-amber-400 border-amber-500/30';
      default:
        return 'bg-slate-500/20 text-slate-400 border-slate-500/30';
    }
  };

  if (isLoading) {
    return (
      <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700 mt-6">
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <ClipboardList className="w-5 h-5 text-indigo-400" />
          Recent Tasks
        </h2>
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-12 bg-slate-700/50 rounded animate-pulse"></div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700 mt-6">
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <ClipboardList className="w-5 h-5 text-indigo-400" />
          Recent Tasks ({tasks?.length || 0})
        </h2>
        
        {!tasks || tasks.length === 0 ? (
          <p className="text-slate-400 text-center py-8">No tasks recorded yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-left border-b border-slate-700">
                  <th className="pb-3 font-medium">Status</th>
                  <th className="pb-3 font-medium">Description</th>
                  <th className="pb-3 font-medium">Agent</th>
                  <th className="pb-3 font-medium">Started</th>
                  <th className="pb-3 font-medium">Duration</th>
                  <th className="pb-3 font-medium">Tokens</th>
                  <th className="pb-3 font-medium">Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/50">
                {tasks.map((task) => (
                  <tr 
                    key={task.task_id} 
                    className="hover:bg-slate-700/30 transition-colors cursor-pointer"
                    onClick={() => setSelectedTask(task.task_id)}
                  >
                    <td className="py-3">
                      <div className="flex items-center gap-2">
                        {getStatusIcon(task.status)}
                        <span className={`px-2 py-0.5 text-xs rounded border ${getStatusBadgeClass(task.status)}`}>
                          {task.status}
                        </span>
                      </div>
                    </td>
                    <td className="py-3 max-w-xs text-slate-200" title={task.description}>
                      <div className="truncate">{task.description}</div>
                      {task.status === 'RUNNING' && liveTaskStates?.[task.task_id]?.current_activity && (
                        <div className="text-xs text-indigo-300 flex items-center gap-1 mt-0.5">
                          <Loader2 className="w-3 h-3 animate-spin flex-shrink-0" />
                          <span className="truncate">{liveTaskStates[task.task_id].current_activity}</span>
                        </div>
                      )}
                    </td>
                    <td className="py-3 text-slate-300">{task.agent_name}</td>
                    <td className="py-3 text-slate-400">{formatTime(task.start_time)}</td>
                    <td className="py-3 text-slate-400">{formatDuration(task.duration_ms)}</td>
                    <td className="py-3 text-slate-400">
                      {task.token_usage ? formatTokens(task.token_usage.total_tokens) : '-'}
                    </td>
                    <td className="py-3 text-teal-400">{formatCost(task.token_usage?.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {selectedTask && (
        <LogModal
          isOpen={true}
          onClose={() => setSelectedTask(null)}
          taskId={selectedTask}
          agentId={tasks?.find((t) => t.task_id === selectedTask)?.agent_id}
          isRunning={tasks?.find((t) => t.task_id === selectedTask)?.status === 'RUNNING'}
          title="Task Execution Logs"
        />
      )}
    </>
  );
}
