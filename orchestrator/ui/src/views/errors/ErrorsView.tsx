// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { ChevronRight, TriangleAlert } from 'lucide-react';
import { ERROR_LIMIT, TASK_LIMIT } from '../../data/dashboardApi';
import { useAgents, useErrors, useTasks } from '../../data/queries';
import { localDateTime } from '../../format';
import { useNavigation } from '../../navigation';
import type { ErrorInfo } from '../../types/dashboard';
import { QueryStatus } from '../QueryStatus';
import './errors.css';

interface ErrorGroup {
  key: string;
  module: string;
  agent: string;
  errors: ErrorInfo[];
}

/** The errors grouped by module and agent, the group of the newest error first, keeping the order of the list within a group. */
export function groupErrors(errors: ErrorInfo[], agentName: (agentId: string) => string): ErrorGroup[] {
  const groups = new Map<string, ErrorGroup>();
  for (const error of errors.toSorted((first, second) => second.timestamp.localeCompare(first.timestamp))) {
    const module = error.module ?? 'Unknown module';
    const agent = error.agent_id === null ? 'Orchestrator' : agentName(error.agent_id);
    const key = JSON.stringify([module, error.agent_id]);
    const group = groups.get(key) ?? { key, module, agent, errors: [] };
    group.errors.push(error);
    groups.set(key, group);
  }
  return [...groups.values()];
}

/** The latest errors, the buffer's size, grouped by module and agent, each with its traceback and its task where that is loaded. */
export function ErrorsView() {
  const errors = useErrors();
  const tasks = useTasks();
  const agents = useAgents();
  const names = new Map((agents.data ?? []).map(({ id, name }) => [id, name]));
  const groups = groupErrors(errors.data ?? [], (agentId) => names.get(agentId) ?? agentId);

  return (
    <section className="errors-view">
      <div className="section-head">
        <h2><TriangleAlert size={20} />Errors</h2>
        <span className="section-note">The latest {ERROR_LIMIT} errors, the most the orchestrator keeps</span>
      </div>
      <QueryStatus query={errors} what="the errors" />
      {errors.data?.length === 0 && <p className="empty-state card"><strong>No errors recorded</strong>Errors of the orchestrator and its agents appear here.</p>}
      {groups.map((group) => (
        <section key={group.key} className="card error-group">
          <h3>
            {group.module} <span className="muted">· {group.agent}</span>
            <span className="tag">{group.errors.length === 1 ? '1 error' : `${group.errors.length} errors`}</span>
          </h3>
          <ul className="error-list">
            {group.errors.map((error) => (
              <ErrorItem key={error.error_id} error={error} taskLoaded={tasks.data ? tasks.data.some(({ task_id }) => task_id === error.task_id) : null} />
            ))}
          </ul>
        </section>
      ))}
    </section>
  );
}

/** `taskLoaded` is null while the task list loads. */
function ErrorItem({ error, taskLoaded }: { error: ErrorInfo; taskLoaded: boolean | null }) {
  const { openTask } = useNavigation();
  const taskId = error.task_id;
  return (
    <li className="error-item">
      <p className="error-meta">
        <time dateTime={error.timestamp}>{localDateTime(error.timestamp)}</time>
        {taskId !== null && taskLoaded === true && <button type="button" className="link" onClick={() => openTask(taskId)}>Open the task</button>}
        {taskId !== null && taskLoaded === false && <span>Not among the last {TASK_LIMIT} tasks</span>}
      </p>
      <p className="error-message">{error.message}</p>
      {error.traceback_snippet && (
        <details>
          <summary><ChevronRight size={16} className="disclosure" />Traceback</summary>
          <pre className="error-traceback">{error.traceback_snippet}</pre>
        </details>
      )}
    </li>
  );
}
