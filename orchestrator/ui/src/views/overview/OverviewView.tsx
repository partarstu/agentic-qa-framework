// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import type { UseQueryResult } from '@tanstack/react-query';
import { Activity, BookOpen, Network, OctagonX } from 'lucide-react';
import { SegmentedMeter } from '../../charts/SegmentedMeter';
import { Sparkline } from '../../charts/Sparkline';
import { Topology } from '../../charts/Topology';
import { TASK_LIMIT } from '../../data/dashboardApi';
import { useAgents, useRagSyncStatus, useSummary, useTasks } from '../../data/queries';
import { age, clockTime, compactCount, count, duration, localDateTime, percent, usd } from '../../format';
import { Aspect } from '../../kit/Aspect';
import { syncStatusAspect } from '../../labels';
import { useLive } from '../../live/useLiveDashboard';
import { useNavigation } from '../../navigation';
import type { AgentInfo, DashboardSummary, TaskInfo } from '../../types/dashboard';
import { useNow } from '../../useNow';
import { QueryStatus } from '../QueryStatus';
import { newestFirst, successRate } from '../taskStats';
import './overview.css';

const TREND_GROUP = 10;
const LATEST_FAILURES = 5;

/** The success rate of the finished tasks among the given ones, oldest first, in groups of ten. */
export function successTrend(tasks: TaskInfo[]): number[] {
  const finished = newestFirst(tasks).filter(({ status }) => status === 'COMPLETED' || status === 'FAILED').toReversed();
  const trend: number[] = [];
  for (let from = 0; from < finished.length; from += TREND_GROUP) {
    const group = finished.slice(from, from + TREND_GROUP);
    trend.push((successRate(group.filter(({ status }) => status === 'COMPLETED').length, group.filter(({ status }) => status === 'FAILED').length) ?? 0) * 100);
  }
  return trend;
}

/** Mission control: the key figures, the live topology and activity, the latest failures and the knowledge sync. */
export function OverviewView() {
  const agents = useAgents();
  const summary = useSummary();
  const tasks = useTasks();
  const live = useLive();
  const names = new Map((agents.data ?? []).map(({ id, name }) => [id, name]));

  return (
    <div className="overview">
      <h2 className="visually-hidden">Key figures</h2>
      <QueryStatus query={summary} what="the key figures" />
      <KeyFigures agents={agents.data} summary={summary.data} tasks={tasks.data} />
      <div className="overview-grid">
        <section className="card overview-topology">
          <div className="section-head"><h2><Network size={18} />Topology</h2></div>
          <QueryStatus query={agents} what="the agents" />
          {agents.data && <Topology agents={agents.data} running={live.running} />}
        </section>
        <section className="card">
          <div className="section-head">
            <h2 id="overview-activity"><Activity size={18} />Live activity</h2>
            <span className="section-note">Since this page opened</span>
          </div>
          {live.activity.length === 0
            ? <p className="empty">No activity since this page opened.</p>
            : (
              <div className="activity-feed" role="region" aria-labelledby="overview-activity" tabIndex={0}>
                <ol>
                  {live.activity.toReversed().map(({ key, agent_id, text, receivedAt }) => (
                    <li key={key}>
                      <time dateTime={new Date(receivedAt).toISOString()}>{clockTime(new Date(receivedAt))}</time>
                      <span className="activity-agent">{names.get(agent_id) ?? agent_id}</span>
                      <span className="activity-text">{text}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}
        </section>
        <LatestFailures tasks={tasks} />
        <KnowledgeSync />
      </div>
    </div>
  );
}

function KeyFigures({ agents, summary, tasks }: { agents?: AgentInfo[]; summary?: DashboardSummary; tasks?: TaskInfo[] }) {
  const byStatus = (status: AgentInfo['status']) => agents?.filter((agent) => agent.status === status).length ?? 0;
  const rate = summary ? successRate(summary.tasks_completed, summary.tasks_failed) : null;
  return (
    <ul className="kpi-strip">
      <li className="card kpi">
        <span className="kpi-label">Agents</span>
        <span className="kpi-value">{agents ? count(agents.length) : '…'}</span>
        <SegmentedMeter label="Agents by status" segments={[
          { label: 'available', value: byStatus('AVAILABLE'), tone: 'passed' },
          { label: 'busy', value: byStatus('BUSY'), tone: 'running' },
          { label: 'broken', value: byStatus('BROKEN'), tone: 'failed' },
        ]} />
      </li>
      <li className="card kpi">
        <span className="kpi-label">Succeeded</span>
        <span className="kpi-value">{summary ? (rate === null ? '—' : percent(rate)) : '…'}</span>
        <span className="kpi-note">
          {summary && (rate === null ? 'No finished task yet' : `${count(summary.tasks_completed)} of ${count(summary.tasks_completed + summary.tasks_failed)} finished tasks`)}
        </span>
        <Sparkline label={`Success rate of the last ${TASK_LIMIT} tasks, in groups of ten`} values={tasks ? successTrend(tasks) : []} max={100}
          format={(value) => percent(value / 100)} />
        <span className="kpi-note">Line: last {TASK_LIMIT} tasks</span>
      </li>
      <li className="card kpi">
        <span className="kpi-label">Cost</span>
        <span className="kpi-value">{summary ? (summary.cost_usd_total === null ? 'Not priced' : usd(summary.cost_usd_total)) : '…'}</span>
        <span className="kpi-note">{summary && `${compactCount(summary.tokens_total)} tokens over ${count(summary.tasks_total)} retained tasks`}</span>
      </li>
      <li className="card kpi">
        <span className="kpi-label">Up for</span>
        <span className="kpi-value">{summary ? duration(summary.uptime_seconds * 1_000) : '…'}</span>
        <span className="kpi-note">{summary && `Version ${summary.orchestrator_version}, model ${summary.orchestrator_model}`}</span>
      </li>
    </ul>
  );
}

function LatestFailures({ tasks }: { tasks: UseQueryResult<TaskInfo[]> }) {
  const { openTask } = useNavigation();
  const failures = newestFirst((tasks.data ?? []).filter(({ status }) => status === 'FAILED')).slice(0, LATEST_FAILURES);
  return (
    <section className="card">
      <div className="section-head"><h2><OctagonX size={18} />Latest failures</h2></div>
      <QueryStatus query={tasks} what="the tasks" />
      {tasks.data && failures.length === 0 && <p className="empty">No failed task among the last {TASK_LIMIT}.</p>}
      {failures.length > 0 && (
        <ul className="choice-list">
          {failures.map((task) => (
            <li key={task.task_id} className="choice failure">
              <div className="choice-text">
                <button type="button" className="link choice-title" onClick={() => openTask(task.task_id)}>{task.description}</button>
                <span className="muted">{task.agent_name} · {localDateTime(task.start_time)}</span>
                {task.error_message && <span className="failure-message">{task.error_message}</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function KnowledgeSync() {
  const syncs = useRagSyncStatus();
  const now = useNow(60_000);
  return (
    <section className="card">
      <div className="section-head"><h2><BookOpen size={18} />Knowledge sync</h2></div>
      <QueryStatus query={syncs} what="the knowledge sync" />
      {syncs.data?.length === 0 && <p className="empty">No knowledge sync has run.</p>}
      {syncs.data && syncs.data.length > 0 && (
        <ul className="choice-list">
          {syncs.data.map((sync) => {
            const status = syncStatusAspect(sync.status);
            return (
              <li key={`${sync.sync_type}:${sync.scope}`} className="choice">
                <div className="choice-text">
                  <span className="choice-title">{sync.scope} <span className="muted">· {sync.sync_type}</span></span>
                  <span className="muted">{sync.message}</span>
                  <span className="muted">{count(sync.processed_count)} processed · updated {age(sync.updated_at, now)}</span>
                </div>
                <Aspect tone={status.tone}>{status.label}</Aspect>
                {sync.stale && <Aspect tone="warning">Stale</Aspect>}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
