import { useQuery, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Cpu, RefreshCw } from 'lucide-react';
import { dashboardApi } from './api/dashboardApi';
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

  const handleRefresh = () => {
    queryClient.invalidateQueries();
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      {/* Header */}
      <header className="bg-slate-800/80 backdrop-blur-sm border-b border-slate-700 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
                <Cpu className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-white">Orchestrator Dashboard</h1>
                <p className="text-xs text-slate-400">Real-time monitoring</p>
              </div>
            </div>
            
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 text-sm text-slate-400">
                <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
                <span>Live</span>
              </div>
              <button
                onClick={handleRefresh}
                className="p-2 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors"
                title="Refresh all data"
              >
                <RefreshCw className="w-5 h-5 text-slate-300" />
              </button>
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

      {/* Footer */}
      <footer className="py-6 text-center text-slate-500 text-sm">
        Agentic QA Framework • Orchestrator Dashboard
      </footer>
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Dashboard />
    </QueryClientProvider>
  );
}

export default App;
