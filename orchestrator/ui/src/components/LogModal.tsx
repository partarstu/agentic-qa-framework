import { useRef, useEffect, useState } from 'react';
import { X, Terminal, Filter, Loader2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '../api/dashboardApi';
import { getStreamToken, clearStreamToken } from '../api/streamToken';
import { notifyAuthHandlers } from '../api/client';
import type { LogBatchPayload, TaskDonePayload } from '../types/dashboard';

interface LogModalProps {
  isOpen: boolean;
  onClose: () => void;
  taskId?: string;
  agentId?: string;
  /** When true and agentId is provided, opens the per-agent SSE for live logs. */
  isRunning?: boolean;
  title: string;
}

export function LogModal({ isOpen, onClose, taskId, agentId, isRunning, title }: LogModalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [levelFilter, setLevelFilter] = useState<string>('');

  // Live streaming state
  const streamedSetRef = useRef<Set<string>>(new Set());
  const [streamedLines, setStreamedLines] = useState<string[]>([]);
  const [sseActive, setSseActive] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setAutoScroll(true);
    }
  }, [isOpen]);

  const { data: logs, isLoading } = useQuery({
    queryKey: ['logs', taskId, agentId],
    queryFn: () => dashboardApi.getLogs(100, 0, undefined, taskId, agentId),
    enabled: isOpen,
    refetchInterval: 2000,
  });

  // Auto-scroll when either polled logs or streamed lines update
  useEffect(() => {
    if (autoScroll && containerRef.current && (logs || streamedLines.length > 0)) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs, streamedLines, autoScroll]);

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  // Per-agent SSE for live logs — only active when agentId is present and task is running
  useEffect(() => {
    if (!agentId || !isRunning || !isOpen) {
      setSseActive(false);
      return;
    }

    streamedSetRef.current = new Set();
    setStreamedLines([]);

    let es: EventSource | null = null;
    let cancelled = false;

    async function connect(): Promise<void> {
      if (cancelled) return;
      try {
        const token = await getStreamToken();
        if (cancelled) return;

        es = new EventSource(
          `/api/dashboard/agents/${agentId}/stream?stream_token=${encodeURIComponent(token)}`,
        );

        if (!cancelled) setSseActive(true);

        es.addEventListener('log_batch', (e: MessageEvent) => {
          if (cancelled) return;
          try {
            const data = JSON.parse(e.data) as LogBatchPayload;
            setStreamedLines((prev) => {
              const seen = streamedSetRef.current;
              const fresh = data.lines.filter((line) => !seen.has(line));
              for (const line of fresh) seen.add(line);
              return fresh.length > 0 ? [...prev, ...fresh] : prev;
            });
          } catch { /* ignore */ }
        });

        es.addEventListener('task_done', (e: MessageEvent) => {
          if (cancelled) return;
          try {
            const data = JSON.parse(e.data) as TaskDonePayload;
            if (!taskId || data.task_id === taskId) {
              es?.close();
              if (!cancelled) setSseActive(false);
            }
          } catch { /* ignore */ }
        });

        es.addEventListener('auth-error', () => {
          clearStreamToken();
          notifyAuthHandlers(false);
          es?.close();
          cancelled = true;
          setSseActive(false);
        });

        es.onerror = () => {
          es?.close();
          if (!cancelled) {
            setSseActive(false);
            setTimeout(() => void connect(), 2_000);
          }
        };
      } catch {
        if (!cancelled) {
          setTimeout(() => void connect(), 2_000);
        }
      }
    }

    void connect();
    return () => {
      cancelled = true;
      es?.close();
      setSseActive(false);
    };
  }, [agentId, isRunning, isOpen, taskId]);

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

  const totalEntries = (filteredLogs?.length ?? 0) + (sseActive ? streamedLines.length : 0);

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
                {sseActive && (
                  <span className="flex items-center gap-1 text-indigo-400">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    Streaming
                  </span>
                )}
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
            {totalEntries} entries found
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
          ) : (
            <div className="space-y-1">
              {/* Polled structured logs */}
              {filteredLogs && filteredLogs.length > 0 ? (
                filteredLogs.map((log, index) => (
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
                ))
              ) : !sseActive ? (
                <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-2">
                  <Terminal className="w-8 h-8 opacity-50" />
                  <p>No logs available yet</p>
                  <p className="text-xs text-slate-600">Agent logs appear after task completion</p>
                </div>
              ) : null}

              {/* Live streamed lines (raw text from the Python formatter) */}
              {sseActive && streamedLines.length > 0 && (
                <>
                  {filteredLogs && filteredLogs.length > 0 && (
                    <div className="h-px bg-slate-700 my-2" />
                  )}
                  <div className="flex items-center gap-1 text-xs text-indigo-400 mb-1">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    <span>Live stream</span>
                  </div>
                  {streamedLines.map((line, i) => (
                    <div
                      key={`live-${i}`}
                      className="flex gap-2 hover:bg-slate-800/50 px-1 rounded py-0.5"
                    >
                      <span className="text-indigo-400/60 flex-shrink-0">[live]</span>
                      <span className="text-slate-300 break-all whitespace-pre-wrap">{line}</span>
                    </div>
                  ))}
                </>
              )}

              {sseActive && streamedLines.length === 0 && (!filteredLogs || filteredLogs.length === 0) && (
                <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-2">
                  <Loader2 className="w-8 h-8 opacity-50 animate-spin" />
                  <p>Waiting for live logs...</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
