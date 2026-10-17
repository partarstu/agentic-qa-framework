// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { AGENT_STATUS_LABELS } from '../labels';
import type { LiveTask } from '../live/liveState';
import type { AgentInfo } from '../types/dashboard';
import './charts.css';

const RING_RADIUS = 120;
const HUB_RADIUS = 30;
const NODE_RADIUS = 13;
const NAME_LIMIT = 22;

type NodeState = 'available' | 'busy' | 'broken';

interface AgentNode {
  agent: AgentInfo;
  state: NodeState;
  running: number;
}

/** The running tasks of each agent, from its poll and from the live store, which learns of a start first. */
export function agentNodes(agents: AgentInfo[], running: Record<string, LiveTask>): AgentNode[] {
  return agents.map((agent) => {
    const taskIds = new Set([
      ...agent.running_tasks.map(({ task_id }) => task_id),
      ...Object.values(running).filter(({ agent_id }) => agent_id === agent.id).map(({ task_id }) => task_id),
    ]);
    const state: NodeState = agent.status === 'BROKEN' ? 'broken' : taskIds.size > 0 ? 'busy' : 'available';
    return { agent, state, running: taskIds.size };
  });
}

const STATE_WORDS: Record<NodeState, string> = { available: AGENT_STATUS_LABELS.AVAILABLE, busy: AGENT_STATUS_LABELS.BUSY, broken: AGENT_STATUS_LABELS.BROKEN };

const shortName = (name: string) => (name.length > NAME_LIMIT ? `${name.slice(0, NAME_LIMIT - 1)}…` : name);

/** The orchestrator with its agents around it, an edge lit while a task runs on it; a list says the same to a screen reader. */
export function Topology({ agents, running }: { agents: AgentInfo[]; running: Record<string, LiveTask> }) {
  if (agents.length === 0) {
    return <p className="empty">No agents registered.</p>;
  }
  const nodes = agentNodes(agents, running);
  return (
    <div className="topology">
      <svg viewBox="-280 -175 560 350" aria-hidden="true">
        {nodes.map(({ agent, state }, index) => {
          const { x, y } = position(index, nodes.length);
          return <line key={agent.id} className={`topology-edge topology-edge-${state}`} x1={0} y1={0} x2={x} y2={y} />;
        })}
        <circle className="topology-hub" r={HUB_RADIUS} />
        <text className="topology-hub-label" y={HUB_RADIUS + 18} textAnchor="middle">Orchestrator</text>
        {nodes.map(({ agent, state }, index) => {
          const { x, y } = position(index, nodes.length);
          const below = y >= 0;
          return (
            <g key={agent.id} className={`topology-node topology-node-${state}`} transform={`translate(${x} ${y})`}>
              {state === 'broken'
                ? <rect x={-NODE_RADIUS} y={-NODE_RADIUS} width={NODE_RADIUS * 2} height={NODE_RADIUS * 2} rx={3} />
                : <circle r={NODE_RADIUS} />}
              {state === 'busy' && <circle className="topology-node-ring" r={NODE_RADIUS + 5} />}
              <text className="topology-name" y={below ? NODE_RADIUS + 18 : -NODE_RADIUS - 22} textAnchor="middle">{shortName(agent.name)}</text>
              <text className="topology-state" y={below ? NODE_RADIUS + 34 : -NODE_RADIUS - 7} textAnchor="middle">{STATE_WORDS[state]}</text>
            </g>
          );
        })}
      </svg>
      <ul className="visually-hidden">
        {nodes.map(({ agent, state, running: count }) => (
          <li key={agent.id}>
            {agent.name}: {STATE_WORDS[state]}{count > 0 && `, ${count === 1 ? '1 task' : `${count} tasks`} running`}
          </li>
        ))}
      </ul>
    </div>
  );
}

function position(index: number, count: number) {
  const angle = (2 * Math.PI * index) / count - Math.PI / 2;
  return { x: Math.round(RING_RADIUS * 1.45 * Math.cos(angle)), y: Math.round(RING_RADIUS * Math.sin(angle)) };
}
