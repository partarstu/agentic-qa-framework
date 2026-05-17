import { useState, useEffect, useReducer } from 'react';
import { useQuery, useInfiniteQuery, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LogOut, XCircle } from 'lucide-react';
import quaiaLogo from './assets/quaia_logo.png';
import { dashboardApi } from './api/dashboardApi';
import { onConnectionStatusChange, onAuthStatusChange } from './api/client';
import { useSseEvents } from './api/sse';
import type { SseEventType } from './api/sse';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LoginPage } from './components/LoginPage';
import { Toast } from './components/Toast';
import { SummaryCards, TaskSummaryCards } from './components/SummaryCards';
import { AgentGrid } from './components/AgentGrid';
import { TaskList } from './components/TaskList';
import { ErrorLog } from './components/ErrorLog';
import { LogViewer } from './components/LogViewer';
import type {
  TaskLiveState,
  SnapshotPayload,
  AgentActivityPayload,
  TaskDonePayload,
} from './types/dashboard';
import './App.css';

const POLLING_INTERVAL = 3000;
const CANCEL_TOAST_TTL_MS = 5_000;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: POLLING_INTERVAL,
      staleTime: POLLING_INTERVAL - 500,
      retry: 2,
    },
  },
});

// --- Live state store ---

type LiveAction =
  | { type: 'SNAPSHOT'; tasks: TaskLiveState[] }
  | { type: 'AGENT_ACTIVITY'; task_id: string; agent_id: string; text: string }
  | { type: 'TASK_DONE'; task_id: string }
  | { type: 'RECONCILE'; terminal_task_ids: string[] };

function liveReducer(
  state: Record<string, TaskLiveState>,
  action: LiveAction,
): Record<string, TaskLiveState> {
  switch (action.type) {
    case 'SNAPSHOT': {
      const next: Record<string, TaskLiveState> = {};
      for (const t of action.tasks) next[t.task_id] = t;
      return next;
    }
    case 'AGENT_ACTIVITY':
      return {
        ...state,
        [action.task_id]: {
          task_id: action.task_id,
          agent_id: action.agent_id,
          current_activity: action.text,
        },
      };
    case 'TASK_DONE': {
      const next = { ...state };
      delete next[action.task_id];
      return next;
    }
    case 'RECONCILE': {
      if (action.terminal_task_ids.length === 0) return state;
      const next = { ...state };
      for (const id of action.terminal_task_ids) delete next[id];
      return next;
    }
  }
}

// --- Cancellation toasts ---

interface CancelToast {
  id: string;
  message: string;
}

// --- Dashboard ---

function Dashboard() {
  const { logout, username } = useAuth();

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['summary'],
    queryFn: dashboardApi.getSummary,
  });

  const { data: agents, isLoading: agentsLoading } = useQuery({
    queryKey: ['agents'],
    queryFn: dashboardApi.getAgents,
  });

  const { data: tasks, isLoading: tasksLoading } = useQuery({
    queryKey: ['tasks'],
    queryFn: () => dashboardApi.getTasks(50),
  });

  const { data: errors, isLoading: errorsLoading } = useQuery({
    queryKey: ['errors'],
    queryFn: () => dashboardApi.getErrors(20),
  });

  const {
    data: logData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading: logsLoading,
  } = useInfiniteQuery({
    queryKey: ['logs'],
    queryFn: ({ pageParam = 0 }) => dashboardApi.getLogs(100, pageParam),
    getNextPageParam: (lastPage, allPages) => {
      return lastPage.length === 100 ? allPages.length * 100 : undefined;
    },
    initialPageParam: 0,
    refetchInterval: 3000,
  });

  const logs = logData ? logData.pages.flat() : undefined;

  const [isOffline, setIsOffline] = useState(false);
  useEffect(() => {
    return onConnectionStatusChange((isOnline) => setIsOffline(!isOnline));
  }, []);

  // Live state store
  const [liveStore, dispatch] = useReducer(liveReducer, {});
  const [cancelToasts, setCancelToasts] = useState<CancelToast[]>([]);

  const handleSseEvent = (type: SseEventType, data: unknown) => {
    switch (type) {
      case 'snapshot': {
        const snap = data as SnapshotPayload;
        dispatch({
          type: 'SNAPSHOT',
          tasks: snap.running_tasks.map((t) => ({
            task_id: t.task_id,
            agent_id: t.agent_id,
            current_activity: t.current_activity,
          })),
        });
        break;
      }
      case 'agent_activity': {
        const ev = data as AgentActivityPayload;
        dispatch({ type: 'AGENT_ACTIVITY', task_id: ev.task_id, agent_id: ev.agent_id, text: ev.text });
        break;
      }
      case 'task_done': {
        const ev = data as TaskDonePayload;
        dispatch({ type: 'TASK_DONE', task_id: ev.task_id });
        if (ev.status === 'CANCELLED') {
          const toast: CancelToast = { id: ev.task_id, message: `Task cancelled` };
          setCancelToasts((prev) => [...prev, toast]);
          setTimeout(
            () => setCancelToasts((prev) => prev.filter((t) => t.id !== ev.task_id)),
            CANCEL_TOAST_TTL_MS,
          );
        }
        break;
      }
    }
  };

  useSseEvents('/api/dashboard/stream', handleSseEvent);

  // Reconcile: remove live state for tasks that polled data reports as terminal
  useEffect(() => {
    if (!tasks) return;
    const TERMINAL = new Set(['COMPLETED', 'FAILED', 'CANCELLED']);
    const terminalIds = tasks.filter((t) => TERMINAL.has(t.status)).map((t) => t.task_id);
    if (terminalIds.length > 0) {
      dispatch({ type: 'RECONCILE', terminal_task_ids: terminalIds });
    }
  }, [tasks]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      {/* Header */}
      <header className="bg-slate-800/80 backdrop-blur-sm border-b border-slate-700 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <img src={quaiaLogo} alt="QuAIA Logo" className="w-10" />
              <div>
                <h1 className="text-xl font-bold text-white">QuAIA™ Dashboard</h1>
                <p className="text-xs text-slate-400">Quality Assurance with Intelligent Agents</p>
              </div>
            </div>

            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 text-sm text-slate-400">
                <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
                <span>Live</span>
              </div>

              <div className="flex items-center gap-3 pl-3 border-l border-slate-600">
                <span className="text-sm text-slate-300">{username}</span>
                <button
                  onClick={logout}
                  className="p-2 rounded-lg bg-slate-700 hover:bg-red-600/80 transition-colors"
                  title="Sign out"
                >
                  <LogOut className="w-5 h-5 text-slate-300" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-6 py-6">
        <SummaryCards summary={summary} isLoading={summaryLoading} />
        <TaskSummaryCards summary={summary} />
        <AgentGrid agents={agents} isLoading={agentsLoading} liveTaskStates={liveStore} />
        <TaskList tasks={tasks} isLoading={tasksLoading} />
        <ErrorLog errors={errors} isLoading={errorsLoading} />
        <LogViewer
          logs={logs}
          isLoading={logsLoading}
          onLoadMore={fetchNextPage}
          hasMore={!!hasNextPage}
          isLoadingMore={isFetchingNextPage}
        />
      </main>

      {isOffline && (
        <Toast message="Connection to Orchestrator lost. Reconnecting..." />
      )}

      {/* Cancellation toasts */}
      {cancelToasts.length > 0 && (
        <div className="fixed bottom-6 left-6 z-50 flex flex-col gap-2">
          {cancelToasts.map((t) => (
            <div
              key={t.id}
              className="flex items-center gap-3 px-4 py-3 bg-amber-950/90 border border-amber-500/50 backdrop-blur-md text-amber-200 rounded-lg shadow-xl"
            >
              <XCircle className="w-5 h-5 text-amber-500 flex-shrink-0" />
              <span className="font-medium text-sm">{t.message}</span>
            </div>
          ))}
        </div>
      )}

      <footer className="py-6 text-center text-slate-500 text-sm">
        QuAIA™ • Quality Assurance with Intelligent Agents
      </footer>
    </div>
  );
}

function AuthenticatedApp() {
  const { isAuthenticated, isLoading, logout } = useAuth();
  const [authExpired, setAuthExpired] = useState(false);

  useEffect(() => {
    return onAuthStatusChange((isAuth) => {
      if (!isAuth) {
        setAuthExpired(true);
        logout();
      }
    });
  }, [logout]);

  useEffect(() => {
    if (isAuthenticated) {
      setAuthExpired(false);
    }
  }, [isAuthenticated]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-3 border-indigo-500/30 border-t-indigo-500 rounded-full animate-spin" />
          <p className="text-slate-400">Loading...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <>
        <LoginPage />
        {authExpired && (
          <Toast message="Your session has expired. Please sign in again." />
        )}
      </>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <Dashboard />
    </QueryClientProvider>
  );
}

function App() {
  return (
    <AuthProvider>
      <AuthenticatedApp />
    </AuthProvider>
  );
}

export default App;
