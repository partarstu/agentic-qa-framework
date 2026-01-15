import { useState } from 'react';
import { AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react';
import type { ErrorInfo } from '../types/dashboard';

interface ErrorLogProps {
  errors: ErrorInfo[] | undefined;
  isLoading: boolean;
}

export function ErrorLog({ errors, isLoading }: ErrorLogProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const formatTime = (isoString: string) => {
    return new Date(isoString).toLocaleString();
  };

  if (isLoading) {
    return (
      <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700 mt-6">
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-red-400" />
          Recent Errors
        </h2>
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-16 bg-slate-700/50 rounded animate-pulse"></div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700 mt-6">
      <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
        <AlertTriangle className="w-5 h-5 text-red-400" />
        Recent Errors ({errors?.length || 0})
      </h2>
      
      {!errors || errors.length === 0 ? (
        <p className="text-slate-400 text-center py-8">No errors recorded - great!</p>
      ) : (
        <div className="space-y-3">
          {errors.map((error) => (
            <div
              key={error.error_id}
              className="bg-red-500/5 border border-red-500/20 rounded-lg overflow-hidden"
            >
              <button
                onClick={() => setExpandedId(expandedId === error.error_id ? null : error.error_id)}
                className="w-full p-4 text-left flex items-start justify-between hover:bg-red-500/10 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 text-xs text-slate-400 mb-1">
                    <span>{formatTime(error.timestamp)}</span>
                    {error.module && <span className="text-slate-500">• {error.module}</span>}
                  </div>
                  <p className="text-red-300 truncate">{error.message}</p>
                </div>
                {expandedId === error.error_id ? (
                  <ChevronUp className="w-5 h-5 text-slate-400 flex-shrink-0 ml-4" />
                ) : (
                  <ChevronDown className="w-5 h-5 text-slate-400 flex-shrink-0 ml-4" />
                )}
              </button>
              
              {expandedId === error.error_id && (
                <div className="px-4 pb-4 border-t border-red-500/20">
                  <div className="grid grid-cols-2 gap-4 mt-3 text-sm">
                    {error.task_id && (
                      <div>
                        <span className="text-slate-400">Task ID:</span>
                        <span className="ml-2 text-slate-300 font-mono text-xs">{error.task_id}</span>
                      </div>
                    )}
                    {error.agent_id && (
                      <div>
                        <span className="text-slate-400">Agent ID:</span>
                        <span className="ml-2 text-slate-300 font-mono text-xs">{error.agent_id}</span>
                      </div>
                    )}
                  </div>
                  {error.traceback_snippet && (
                    <div className="mt-3">
                      <p className="text-slate-400 text-xs mb-1">Traceback:</p>
                      <pre className="bg-slate-900 p-3 rounded text-xs text-red-300 overflow-x-auto">
                        {error.traceback_snippet}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
