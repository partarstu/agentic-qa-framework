// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { Activity, Bot, LoaderCircle, Radar } from 'lucide-react';
import { agentNodes } from '../../charts/Topology';
import { useAgents } from '../../data/queries';
import { Aspect } from '../../kit/Aspect';
import { Meter } from '../../kit/Meter';
import { AGENT_STATUS_LABELS, AGENT_STATUS_TONES, BROKEN_REASON_LABELS, BROKEN_REASON_TONES } from '../../labels';
import { useLive } from '../../live/useLiveDashboard';
import { useNavigation } from '../../navigation';
import type { AgentInfo } from '../../types/dashboard';
import { QueryStatus } from '../QueryStatus';
import { AgentDescription } from './AgentDescription';
import './agents.css';

/** Every registered agent as a card that opens its sheet, and the agent discovery. */
export function AgentsView() {
  const agents = useAgents();
  const live = useLive();
  const { discover } = useNavigation();
  const nodes = agentNodes(agents.data ?? [], live.running);

  return (
    <section className="agents-view">
      <div className="section-head">
        <h2><Bot size={20} />Agents</h2>
        {agents.data && <span className="section-note">{agents.data.length === 1 ? '1 agent registered' : `${agents.data.length} agents registered`}</span>}
        <div className="section-tools">
          <button type="button" aria-busy={discover === null} disabled={discover === null} onClick={() => discover?.()}>
            {discover === null ? <LoaderCircle size={18} className="spin" /> : <Radar size={18} />}
            Discover agents
          </button>
        </div>
      </div>
      <QueryStatus query={agents} what="the agents" />
      {agents.data?.length === 0 && (
        <div className="empty-state card">
          <Bot size={32} />
          <strong>No agents registered</strong>
          <p>Agents register when they start; Discover agents probes the configured ones again.</p>
        </div>
      )}
      {nodes.length > 0 && (
        <ul className="agent-grid">
          {nodes.map(({ agent, running }) => (
            <AgentCard key={agent.id} agent={agent} running={running}
              activity={Object.values(live.running).find(({ agent_id, current_activity }) => agent_id === agent.id && current_activity)?.current_activity ?? null} />
          ))}
        </ul>
      )}
    </section>
  );
}

function AgentCard({ agent, running, activity }: { agent: AgentInfo; running: number; activity: string | null }) {
  const { openAgent } = useNavigation();
  const capacity = `${running} of ${agent.task_capacity} ${agent.task_capacity === 1 ? 'slot' : 'slots'} busy`;
  return (
    <li className="agent-card card">
      <div className="agent-card-head">
        <h3><button type="button" className="link" onClick={() => openAgent(agent.id)}>{agent.name}</button></h3>
        <Aspect tone={AGENT_STATUS_TONES[agent.status]}>{AGENT_STATUS_LABELS[agent.status]}</Aspect>
      </div>
      <BrokenReason agent={agent} />
      <div className="agent-capacity">
        <span>{capacity}</span>
        <Meter label="Capacity" value={running} max={agent.task_capacity} valueText={capacity} neutral />
      </div>
      {activity && <p className="activity-line"><Activity size={16} aria-hidden="true" /><span className="visually-hidden">Now: </span>{activity}</p>}
      <AgentDescription html={agent.description} clamped />
      <dl className="facts agent-facts">
        <dt>Version</dt>
        <dd>{agent.version}</dd>
        <dt>URL</dt>
        <dd>{agent.url}</dd>
      </dl>
    </li>
  );
}

/** Why an agent is broken; a stuck task opens its sheet. */
export function BrokenReason({ agent }: { agent: AgentInfo }) {
  const { openTask } = useNavigation();
  if (agent.status !== 'BROKEN' || agent.broken_reason === null) {
    return null;
  }
  const stuckTaskId = agent.stuck_task_id;
  return (
    <p className="agent-broken">
      <Aspect tone={BROKEN_REASON_TONES[agent.broken_reason]} quiet>{BROKEN_REASON_LABELS[agent.broken_reason]}</Aspect>
      {agent.broken_reason === 'TASK_STUCK' && stuckTaskId !== null && (
        <button type="button" className="link" onClick={() => openTask(stuckTaskId)}>Open the stuck task</button>
      )}
    </p>
  );
}
