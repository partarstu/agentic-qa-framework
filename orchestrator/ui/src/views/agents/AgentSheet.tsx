// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { ScrollText } from 'lucide-react';
import { agentNodes } from '../../charts/Topology';
import { TASK_LIMIT } from '../../data/dashboardApi';
import { useAgents, useTasks } from '../../data/queries';
import { count, duration, localDateTime, percent, usd } from '../../format';
import { Aspect } from '../../kit/Aspect';
import { AGENT_STATUS_LABELS, AGENT_STATUS_TONES, TASK_STATUS_LABELS, TASK_STATUS_TONES } from '../../labels';
import { useLive } from '../../live/useLiveDashboard';
import { LogTail } from '../../logs/LogTail';
import { useLogTail } from '../../logs/useLogTail';
import { useNavigation } from '../../navigation';
import type { AgentCapabilities, AgentInfo } from '../../types/dashboard';
import { useNow } from '../../useNow';
import { QueryStatus } from '../QueryStatus';
import { Sheet } from '../Sheet';
import { newestFirst, taskStats } from '../taskStats';
import { AgentDescription } from './AgentDescription';
import { BrokenReason } from './AgentsView';

const RECENT_TASKS = 5;

const CAPABILITY_LABELS: Record<keyof AgentCapabilities, string> = {
  streaming: 'Streaming',
  pushNotifications: 'Push notifications',
  stateTransitionHistory: 'State transition history',
};

/** The agent sheet: running and recent tasks, stats over the last 100 tasks, capabilities and the log tail of all its tasks. */
export function AgentSheet({ agentId, onClose }: { agentId: string | null; onClose: () => void }) {
  const agents = useAgents();
  const agent = agents.data?.find(({ id }) => id === agentId);
  return (
    <Sheet open={agentId !== null} title={agent?.name ?? 'Agent'} onClose={onClose}>
      {agentId !== null && (agent ? <AgentDetails agent={agent} /> : (
        <>
          <QueryStatus query={agents} what="the agent" />
          {agents.data && <p className="note">This agent is no longer registered.</p>}
        </>
      ))}
    </Sheet>
  );
}

function AgentDetails({ agent }: { agent: AgentInfo }) {
  const tasks = useTasks();
  const live = useLive();
  const { openTask, openLogs } = useNavigation();
  const now = useNow(1_000);
  const [{ running }] = agentNodes([agent], live.running);
  const tail = useLogTail({ kind: 'agent', agentId: agent.id }, { follow: running > 0, level: null });
  const own = newestFirst((tasks.data ?? []).filter(({ agent_id }) => agent_id === agent.id));
  const stats = taskStats(own);
  const descriptions = new Map((tasks.data ?? []).map(({ task_id, description }) => [task_id, description]));
  const capabilities = (Object.keys(CAPABILITY_LABELS) as (keyof AgentCapabilities)[]).filter((name) => agent.capabilities?.[name]);

  return (
    <>
      <p className="sheet-status">
        <Aspect tone={AGENT_STATUS_TONES[agent.status]}>{AGENT_STATUS_LABELS[agent.status]}</Aspect>
        <span className="muted">{running} of {agent.task_capacity} {agent.task_capacity === 1 ? 'slot' : 'slots'} busy</span>
      </p>
      <BrokenReason agent={agent} />
      <section className="sheet-section">
        <h3>Running tasks</h3>
        {agent.running_tasks.length === 0
          ? <p className="empty">None.</p>
          : (
            <ul className="plain-list">
              {agent.running_tasks.map(({ task_id, description, start_time }) => (
                <li key={task_id}>
                  <button type="button" className="link" onClick={() => openTask(task_id)}>{description}</button>{' '}
                  <span className="muted">running for {duration(now - Date.parse(start_time))}</span>
                </li>
              ))}
            </ul>
          )}
      </section>
      <section className="sheet-section">
        <h3>Recent tasks</h3>
        <p className="section-note">From the last {TASK_LIMIT} tasks of all agents.</p>
        <QueryStatus query={tasks} what="the tasks" />
        {tasks.data && (
          <>
            <dl className="facts">
              <dt>Tasks</dt>
              <dd>{count(stats.total)}</dd>
              <dt>Succeeded</dt>
              <dd>{stats.successRate === null ? 'No finished task' : `${percent(stats.successRate)} (${stats.completed} of ${stats.completed + stats.failed} finished)`}</dd>
              <dt>Average duration</dt>
              <dd>{stats.averageDurationMs === null ? '—' : duration(stats.averageDurationMs)}</dd>
              <dt>Tokens</dt>
              <dd>{count(stats.tokens)}</dd>
              <dt>Cost</dt>
              <dd>{stats.costUsd === null ? 'Not priced' : usd(stats.costUsd)}</dd>
            </dl>
            {own.length === 0
              ? <p className="empty">No task of this agent among them.</p>
              : (
                <ul className="choice-list">
                  {own.slice(0, RECENT_TASKS).map((task) => (
                    <li key={task.task_id} className="choice">
                      <button type="button" className="link choice-title" onClick={() => openTask(task.task_id)}>{task.description}</button>
                      <Aspect tone={TASK_STATUS_TONES[task.status]} quiet>{TASK_STATUS_LABELS[task.status]}</Aspect>
                      <span className="muted">{localDateTime(task.start_time)}</span>
                    </li>
                  ))}
                </ul>
              )}
          </>
        )}
      </section>
      <section className="sheet-section">
        <h3>About</h3>
        <AgentDescription html={agent.description} />
        <dl className="facts">
          <dt>Version</dt>
          <dd>{agent.version}</dd>
          <dt>URL</dt>
          <dd>{agent.url}</dd>
          <dt>Capabilities</dt>
          <dd>
            {capabilities.length === 0 ? 'None reported' : (
              <span className="tags">{capabilities.map((name) => <span key={name} className="tag">{CAPABILITY_LABELS[name]}</span>)}</span>
            )}
          </dd>
        </dl>
      </section>
      <LogTail title="Logs of its tasks" tail={tail} taskLabel={(taskId) => descriptions.get(taskId) ?? taskId} />
      <div className="sheet-actions">
        <button type="button" onClick={() => openLogs({ kind: 'agent', agentId: agent.id })}><ScrollText size={18} />Open in Logs</button>
      </div>
    </>
  );
}
