import { useState, useEffect } from 'react';
import { useQuery, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LogOut } from 'lucide-react';
import quaiaLogo from './assets/quaia_logo.png';
import { dashboardApi } from './api/dashboardApi';
import { onConnectionStatusChange, onAuthStatusChange } from './api/client';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LoginPage } from './components/LoginPage';
import { Toast } from './components/Toast';
import { SummaryCards, TaskSummaryCards } from './components/SummaryCards';
import { AgentGrid } from './components/AgentGrid';
import { TaskList } from './components/TaskList';
import { ErrorLog } from './components/ErrorLog';
import { LogViewer } from './components/LogViewer';
import './App.css';

const POLLING_INTERVAL = 3000; // 3 seconds

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: POLLING_INTERVAL,
      staleTime: POLLING_INTERVAL - 500,
      retry: 2,
    },
  },
});

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

  const { data: logs, isLoading: logsLoading } = useQuery({
    queryKey: ['logs'],
    queryFn: () => dashboardApi.getLogs(100),
  });


  const [isOffline, setIsOffline] = useState(false);

  useEffect(() => {
    const unsubscribe = onConnectionStatusChange((isOnline) => {
      setIsOffline(!isOnline);
    });
    return unsubscribe;
  }, []);

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

              {/* User info and logout */}
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
        {/* Summary Cards */}
        <SummaryCards summary={summary} isLoading={summaryLoading} />
        <TaskSummaryCards summary={summary} />

        {/* Agent Grid */}
        <AgentGrid agents={agents} isLoading={agentsLoading} />

        {/* Task List */}
        <TaskList tasks={tasks} isLoading={tasksLoading} />

        {/* Error Log */}
        <ErrorLog errors={errors} isLoading={errorsLoading} />

        {/* Log Viewer */}
        <LogViewer logs={logs} isLoading={logsLoading} />
      </main>

      {isOffline && (
        <Toast message="Connection to Orchestrator lost. Reconnecting..." />
      )}

      {/* Footer */}
      <footer className="py-6 text-center text-slate-500 text-sm">
        QuAIA™ • Quality Assurance with Intelligent Agents
      </footer>
    </div>
  );
}

function AuthenticatedApp() {
  const { isAuthenticated, isLoading, logout } = useAuth();
  const [authExpired, setAuthExpired] = useState(false);

  // Listen for auth status changes (e.g., 401 errors)
  useEffect(() => {
    const unsubscribe = onAuthStatusChange((isAuth) => {
      if (!isAuth) {
        setAuthExpired(true);
        logout();
      }
    });
    return unsubscribe;
  }, [logout]);

  // Clear auth expired flag when user logs in again
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

