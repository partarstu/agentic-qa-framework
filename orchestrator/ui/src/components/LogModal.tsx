
import { useRef, useEffect, useState } from 'react';
import { X, Terminal, Filter } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '../api/dashboardApi';


interface LogModalProps {
  isOpen: boolean;
  onClose: () => void;
  taskId?: string;
  agentId?: string;
  title: string;
}

export function LogModal({ isOpen, onClose, taskId, agentId, title }: LogModalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [levelFilter, setLevelFilter] = useState<string>('');
  
  // Reset auto-scroll when modal opens
  useEffect(() => {
    if (isOpen) {
      setAutoScroll(true);
    }
  }, [isOpen]);

  const { data: logs, isLoading } = useQuery({
    queryKey: ['logs', taskId, agentId],
    queryFn: () => dashboardApi.getLogs(100, undefined, taskId, agentId),
    enabled: isOpen,
    refetchInterval: 2000, // Poll every 2s while open
  });

  useEffect(() => {
    if (autoScroll && containerRef.current && logs) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  // Handle ESC key
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  if (!isOpen) return null;

  const getLevelClass = (level: string) => {
    switch (level.toUpperCase()) {
      case 'ERROR':
        return 'text-red-400';
      case 'WARNING':
        return 'text-amber-400';
      case 'INFO':
        return 'text-emerald-400';
      case 'DEBUG':
        return 'text-slate-400';
      default:
        return 'text-slate-300';
    }
  };

  const filteredLogs = levelFilter
    ? logs?.filter((log) => log.level.toUpperCase() === levelFilter.toUpperCase())
    : logs;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-slate-800 rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col border border-slate-700">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-slate-700/50 rounded-lg">
              <Terminal className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">{title}</h2>
              <div className="flex gap-2 text-xs text-slate-400">
                {taskId && <span>Task: {taskId.substring(0, 8)}...</span>}
                {agentId && <span>Agent: {agentId.substring(0, 8)}...</span>}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-700 rounded-lg transition-colors text-slate-400 hover:text-white"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Toolbar */}
        <div className="p-4 bg-slate-800/50 border-b border-slate-700 flex items-center justify-between">
           <div className="text-sm text-slate-400">
             {logs?.length || 0} entries found
           </div>
           
           <div className="flex items-center gap-4">
             <div className="flex items-center gap-2">
               <Filter className="w-4 h-4 text-slate-400" />
               <select
                 value={levelFilter}
                 onChange={(e) => setLevelFilter(e.target.value)}
                 className="bg-slate-700 border border-slate-600 rounded px-2 py-1 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
               >
                 <option value="">All Levels</option>
                 <option value="ERROR">Error</option>
                 <option value="WARNING">Warning</option>
                 <option value="INFO">Info</option>
                 <option value="DEBUG">Debug</option>
               </select>
             </div>
             
             <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer">
               <input
                 type="checkbox"
                 checked={autoScroll}
                 onChange={(e) => setAutoScroll(e.target.checked)}
                 className="rounded border-slate-600 bg-slate-700 text-indigo-500 focus:ring-indigo-500"
               />
               Auto-scroll
             </label>
           </div>
        </div>

        {/* Content */}
        <div 
          ref={containerRef}
          className="flex-1 overflow-auto p-4 bg-slate-900 font-mono text-xs"
        >
          {isLoading ? (
            <div className="flex items-center justify-center h-full text-slate-500 animate-pulse">
              Loading logs...
            </div>
          ) : !filteredLogs || filteredLogs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-2">
              <Terminal className="w-8 h-8 opacity-50" />
              <p>No logs available yet</p>
              <p className="text-xs text-slate-600">Agent logs appear after task completion</p>
            </div>
          ) : (
            <div className="space-y-1">
              {filteredLogs.map((log, index) => (
                <div key={index} className="flex gap-2 hover:bg-slate-800/50 px-1 rounded py-0.5">
                  <span className="text-slate-500 flex-shrink-0 w-24">
                    {log.timestamp && !isNaN(new Date(log.timestamp).getTime())
                      ? new Date(log.timestamp).toLocaleTimeString()
                      : '-'}
                  </span>
                  <span className={`flex-shrink-0 w-16 ${getLevelClass(log.level)}`}>
                    [{log.level}]
                  </span>
                  <span className="text-slate-400 flex-shrink-0 w-32 truncate" title={log.logger}>
                    {log.logger}
                  </span>
                  <span className="text-slate-200 break-all whitespace-pre-wrap">{log.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
