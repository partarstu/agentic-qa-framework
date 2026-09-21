import type { RagSyncOutcome } from '../types/dashboard';

interface Props {
  outcomes?: RagSyncOutcome[];
  isLoading: boolean;
  isError: boolean;
}

export function RagSyncStatus({ outcomes, isLoading, isError }: Props) {
  if (isLoading) return <section className="p-4 text-slate-400">Loading RAG sync status…</section>;
  if (isError) return <section className="p-4 text-amber-300">RAG sync status is temporarily unavailable.</section>;
  if (!outcomes?.length) return <section className="p-4 text-slate-400">No RAG sync outcomes recorded.</section>;
  return <section className="p-4 bg-slate-800 rounded-lg mb-6"><h2 className="text-white font-semibold mb-2">RAG sync status</h2>{outcomes.map((outcome) => <div key={outcome.scope} className="text-sm text-slate-300 border-t border-slate-700 py-2"><span className="font-medium">{outcome.sync_type} · {outcome.scope}</span> — {outcome.status} ({outcome.processed_count}) {outcome.stale && <span className="text-amber-300">stale</span>}<br />{outcome.message}<br /><span className="text-slate-500">Updated {new Date(outcome.updated_at).toLocaleString()}</span></div>)}</section>;
}
