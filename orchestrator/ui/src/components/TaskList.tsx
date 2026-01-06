import { ClipboardList, CheckCircle, XCircle, Clock, Loader2 } from 'lucide-react';
import type { TaskInfo } from '../types/dashboard';

interface TaskListProps {
  tasks: TaskInfo[] | undefined;
  isLoading: boolean;
}

export function TaskList({ tasks, isLoading }: TaskListProps) {
  const formatDuration = (ms: number | null) => {
    if (ms === null) return '-';
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  };

  const formatTime = (isoString: string) => {
    return new Date(isoString).toLocaleTimeString();
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
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {tasks.map((task) => (
                <tr key={task.task_id} className="hover:bg-slate-700/30 transition-colors">
                  <td className="py-3">
                    <div className="flex items-center gap-2">
                      {getStatusIcon(task.status)}
                      <span className={`px-2 py-0.5 text-xs rounded border ${getStatusBadgeClass(task.status)}`}>
                        {task.status}
                      </span>
                    </div>
                  </td>
                  <td className="py-3 max-w-xs truncate text-slate-200" title={task.description}>
                    {task.description}
                  </td>
                  <td className="py-3 text-slate-300">{task.agent_name}</td>
                  <td className="py-3 text-slate-400">{formatTime(task.start_time)}</td>
                  <td className="py-3 text-slate-400">{formatDuration(task.duration_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
