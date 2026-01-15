import { Activity, CheckCircle, XCircle } from 'lucide-react';
import type { DashboardSummary } from '../types/dashboard';

interface SummaryCardsProps {
  summary: DashboardSummary | undefined;
  isLoading: boolean;
}

export function SummaryCards({ summary, isLoading }: SummaryCardsProps) {
  if (isLoading || !summary) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="bg-slate-800 rounded-xl p-6 animate-pulse">
            <div className="h-4 bg-slate-700 rounded w-1/2 mb-4"></div>
            <div className="h-8 bg-slate-700 rounded w-1/3"></div>
          </div>
        ))}
      </div>
    );
  }

  const cards = [
    {
      title: 'Total Agents',
      value: summary.agents_total,
      icon: Activity,
      color: 'text-indigo-400',
      bgColor: 'bg-indigo-500/10',
      borderColor: 'border-indigo-500/20',
    },
    {
      title: 'Available',
      value: summary.agents_available,
      icon: CheckCircle,
      color: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
      borderColor: 'border-emerald-500/20',
    },
    {
      title: 'Busy',
      value: summary.agents_busy,
      icon: Activity,
      color: 'text-amber-400',
      bgColor: 'bg-amber-500/10',
      borderColor: 'border-amber-500/20',
    },
    {
      title: 'Broken',
      value: summary.agents_broken,
      icon: XCircle,
      color: 'text-red-400',
      bgColor: 'bg-red-500/10',
      borderColor: 'border-red-500/20',
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {cards.map((card) => (
        <div
          key={card.title}
          className={`${card.bgColor} ${card.borderColor} border rounded-xl p-6 transition-all hover:scale-[1.02]`}
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="text-slate-400 text-sm font-medium">{card.title}</p>
              <p className={`text-3xl font-bold mt-1 ${card.color}`}>{card.value}</p>
            </div>
            <card.icon className={`w-10 h-10 ${card.color} opacity-80`} />
          </div>
        </div>
      ))}
    </div>
  );
}

interface TaskSummaryCardsProps {
  summary: DashboardSummary | undefined;
}

export function TaskSummaryCards({ summary }: TaskSummaryCardsProps) {
  if (!summary) return null;

  const formatUptime = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${minutes}m`;
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4 mb-6">
      <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
        <p className="text-slate-400 text-xs uppercase tracking-wider">Running Tasks</p>
        <p className="text-2xl font-bold text-amber-400 mt-1">{summary.tasks_running}</p>
      </div>
      <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
        <p className="text-slate-400 text-xs uppercase tracking-wider">Completed</p>
        <p className="text-2xl font-bold text-emerald-400 mt-1">{summary.tasks_completed}</p>
      </div>
      <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
        <p className="text-slate-400 text-xs uppercase tracking-wider">Failed</p>
        <p className="text-2xl font-bold text-red-400 mt-1">{summary.tasks_failed}</p>
      </div>
      <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
        <p className="text-slate-400 text-xs uppercase tracking-wider">Total Errors</p>
        <p className="text-2xl font-bold text-orange-400 mt-1">{summary.errors_total}</p>
      </div>
      <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
        <p className="text-slate-400 text-xs uppercase tracking-wider">Uptime</p>
        <p className="text-2xl font-bold text-indigo-400 mt-1">{formatUptime(summary.uptime_seconds)}</p>
      </div>
    </div>
  );
}
