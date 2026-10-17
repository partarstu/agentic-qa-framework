// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { Pause, Play } from 'lucide-react';
import { useState } from 'react';
import type { LogSource } from '../../data/dashboardApi';
import { useAgents, useTasks } from '../../data/queries';
import { useLive } from '../../live/useLiveDashboard';
import { LogTail } from '../../logs/LogTail';
import { useLogTail } from '../../logs/useLogTail';
import { useNavigation } from '../../navigation';
import { isTaskActive } from '../taskStats';
import './logs.css';

const LOG_LEVELS =['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];

const ORCHESTRATOR = 'orchestrator';

function sourceValue(source: LogSource): string {
  switch (source.kind) {
    case 'orchestrator':
      return ORCHESTRATOR;
    case 'agent':
      return `agent:${source.agentId}`;
    case 'task':
      return `task:${source.taskId}`;
  }
}

interface Props {
  source: LogSource;
  onSource: (source: LogSource) => void;
}

/** One log source at a time, as the API returns them: the orchestrator's own logs, or the execution logs of one agent or one task. */
export function LogsView({ source, onSource }: Props) {
  const agents = useAgents();
  // Only for the names of the tasks: the Logs view never loads the task list itself
  const tasks = useTasks(false);
  const live = useLive();
  const { sheetOpen } = useNavigation();
  const [level, setLevel] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  // A finished task's log is complete, and a stream for it would hold the tab's one per-agent connection for nothing
  const taskStatus = source.kind === 'task' ? tasks.data?.find(({ task_id }) => task_id === source.taskId)?.status : undefined;
  const ended = source.kind === 'task' && !isTaskActive(live.running, source.taskId, taskStatus);
  // An open sheet owns the one per-agent stream a tab may hold
  const tail = useLogTail(source, { follow: follow && !sheetOpen && !ended, level });
  const descriptions = new Map((tasks.data ?? []).map(({ task_id, description }) => [task_id, description]));

  const choose = (value: string) => {
    if (value === ORCHESTRATOR) {
      onSource({ kind: 'orchestrator' });
    } else if (value.startsWith('agent:')) {
      onSource({ kind: 'agent', agentId: value.slice('agent:'.length) });
    }
  };

  const tools = (
    <>
      <label className="logs-control">
        Source{' '}
        <select value={sourceValue(source)} onChange={(event) => choose(event.target.value)}>
          <option value={ORCHESTRATOR}>Orchestrator</option>
          {(agents.data ?? []).map(({ id, name }) => <option key={id} value={`agent:${id}`}>Agent: {name}</option>)}
          {source.kind === 'task' && <option value={sourceValue(source)}>Task: {descriptions.get(source.taskId) ?? source.taskId}</option>}
        </select>
      </label>
      <label className="logs-control">
        Level{' '}
        <select value={level ?? ''} onChange={(event) => setLevel(event.target.value || null)}>
          <option value="">All levels</option>
          {LOG_LEVELS.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <button type="button" className="small" onClick={() => setFollow(!follow)}>
        {follow ? <Pause size={16} /> : <Play size={16} />}
        {follow ? 'Pause' : 'Follow'}
      </button>
    </>
  );

  return (
    <div className="logs-view card">
      <LogTail title="Logs" headingLevel={2} tail={tail} tools={tools}
        taskLabel={source.kind === 'agent' ? (taskId) => descriptions.get(taskId) ?? taskId : undefined} />
      <p className="section-note logs-state" role="status">
        {!follow ? 'Paused.' : ended ? 'The task has ended, so its log is complete.' : sheetOpen ? 'Following pauses while a sheet is open.' : 'Following the newest lines.'}
      </p>
    </div>
  );
}
