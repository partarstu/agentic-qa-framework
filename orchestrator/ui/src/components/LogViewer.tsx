import { useEffect, useRef, useState } from 'react';
import { Terminal, Filter } from 'lucide-react';
import type { LogEntry } from '../types/dashboard';

interface LogViewerProps {
  logs: LogEntry[] | undefined;
  isLoading: boolean;
  onLoadMore: () => void;
  hasMore: boolean;
  isLoadingMore: boolean;
}

export function LogViewer({ logs, isLoading, onLoadMore, hasMore, isLoadingMore }: LogViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [levelFilter, setLevelFilter] = useState<string>('');
  const prevScrollHeightRef = useRef<number>(0);
  const prevLogsLengthRef = useRef<number>(0);

  // Handle auto-scroll for new logs (at bottom)
  useEffect(() => {
    if (autoScroll && containerRef.current && logs && logs.length > prevLogsLengthRef.current) {
      // Only auto-scroll if we are not loading history and new logs arrived
      if (!isLoadingMore) {
        containerRef.current.scrollTop = containerRef.current.scrollHeight;
      }
    }
    prevLogsLengthRef.current = logs?.length || 0;
  }, [logs, autoScroll, isLoadingMore]);

  // Maintain scroll position when history loads (at top)
  useEffect(() => {
    if (containerRef.current && prevScrollHeightRef.current > 0) {
      const newScrollHeight = containerRef.current.scrollHeight;
      const diff = newScrollHeight - prevScrollHeightRef.current;
      if (diff > 0) {
        containerRef.current.scrollTop += diff;
      }
      prevScrollHeightRef.current = 0;
    }
  }, [logs]);

  const handleScroll = () => {
    if (!containerRef.current) return;
    
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    
    // Check for scroll to top to load more
    if (scrollTop === 0 && hasMore && !isLoadingMore) {
      prevScrollHeightRef.current = scrollHeight;
      onLoadMore();
    }

    // Check if user scrolled away from bottom to disable auto-scroll
    const isAtBottom = Math.abs(scrollHeight - scrollTop - clientHeight) < 10;
    if (!isAtBottom) {
      setAutoScroll(false);
    } else {
        setAutoScroll(true);
    }
  };

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

  if (isLoading) {
    return (
      <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700 mt-6">
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <Terminal className="w-5 h-5 text-indigo-400" />
          Orchestrator Logs
        </h2>
        <div className="h-64 bg-slate-900 rounded animate-pulse"></div>
      </div>
    );
  }

  return (
    <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700 mt-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <Terminal className="w-5 h-5 text-indigo-400" />
          Orchestrator Logs ({filteredLogs?.length || 0})
        </h2>
        
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
      
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="h-80 bg-slate-900 rounded-lg overflow-auto font-mono text-xs p-4"
      >
        {isLoadingMore && (
            <div className="flex justify-center py-2">
                <div className="w-4 h-4 border-2 border-indigo-500/30 border-t-indigo-500 rounded-full animate-spin" />
            </div>
        )}
        {!filteredLogs || filteredLogs.length === 0 ? (
          <p className="text-slate-500 text-center py-8">No logs available</p>
        ) : (
          <div className="space-y-1">
            {filteredLogs.map((log, index) => (
              <div key={index} className="flex gap-2 hover:bg-slate-800/50 px-1 rounded">
                <span className="text-slate-500 flex-shrink-0">
                  {new Date(log.timestamp).toLocaleTimeString()}
                </span>
                <span className={`flex-shrink-0 w-16 ${getLevelClass(log.level)}`}>
                  [{log.level}]
                </span>
                <span className="text-slate-400 flex-shrink-0 w-32 truncate">
                  {log.logger}
                </span>
                <span className="text-slate-200 break-all">{log.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
