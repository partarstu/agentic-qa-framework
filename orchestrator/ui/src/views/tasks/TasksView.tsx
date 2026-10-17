// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { ArrowDown, ArrowUp, ListChecks } from 'lucide-react';
import { useState } from 'react';
import { TASK_LIMIT } from '../../data/dashboardApi';
import { useTasks } from '../../data/queries';
import { count, duration, localDateTime, usd } from '../../format';
import { Aspect } from '../../kit/Aspect';
import { TASK_STATUS_LABELS, TASK_STATUS_TONES } from '../../labels';
import { useNavigation } from '../../navigation';
import type { TaskInfo } from '../../types/dashboard';
import { useNow } from '../../useNow';
import { QueryStatus } from '../QueryStatus';
import './tasks.css';

type SortKey = 'description' | 'agent' | 'status' | 'start' | 'duration' | 'tokens' | 'cost';

interface Sort {
  key: SortKey;
  descending: boolean;
}

const COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: 'description', label: 'Task' },
  { key: 'agent', label: 'Agent' },
  { key: 'status', label: 'Status' },
  { key: 'start', label: 'Started' },
  { key: 'duration', label: 'Duration', numeric: true },
  { key: 'tokens', label: 'Tokens', numeric: true },
  { key: 'cost', label: 'Cost', numeric: true },
];

const STATUSES = Object.keys(TASK_STATUS_LABELS) as TaskInfo['status'][];

/** A missing figure sorts below every present one, in either direction. */
const SORT_VALUES: Record<SortKey, (task: TaskInfo, now: number) => string | number | null> = {
  description: (task) => task.description.toLowerCase(),
  agent: (task) => task.agent_name.toLowerCase(),
  status: (task) => TASK_STATUS_LABELS[task.status],
  start: (task) => task.start_time,
  duration: (task, now) => task.duration_ms ?? (task.status === 'RUNNING' ? now - Date.parse(task.start_time) : null),
  tokens: (task) => task.token_usage?.total_tokens ?? null,
  cost: (task) => task.token_usage?.cost_usd ?? null,
};

export function sortTasks(tasks: TaskInfo[], { key, descending }: Sort, now: number): TaskInfo[] {
  const value = SORT_VALUES[key];
  return tasks.toSorted((first, second) => {
    const [a, b] = [value(first, now), value(second, now)];
    if (a === null || b === null) {
      return a === b ? 0 : a === null ? 1 : -1;
    }
    const order = a < b ? -1 : a > b ? 1 : 0;
    return descending ? -order : order;
  });
}

/** The last 100 tasks as a sortable, filterable table; a task's button opens its sheet. */
export function TasksView() {
  const tasks = useTasks();
  const { openTask } = useNavigation();
  const now = useNow(1_000);
  const [sort, setSort] = useState<Sort>({ key: 'start', descending: true });
  const [status, setStatus] = useState('');
  const [agent, setAgent] = useState('');
  const [query, setQuery] = useState('');

  const all = tasks.data ?? [];
  const agents = [...new Map(all.map(({ agent_id, agent_name }) => [agent_id, agent_name])).entries()].toSorted(([, a], [, b]) => a.localeCompare(b));
  const needle = query.trim().toLowerCase();
  const shown = sortTasks(all.filter((task) => (status === '' || task.status === status) && (agent === '' || task.agent_id === agent)
    && (needle === '' || `${task.description} ${task.task_id} ${task.agent_name}`.toLowerCase().includes(needle))), sort, now);

  const sortBy = (key: SortKey) => setSort((current) => (current.key === key ? { key, descending: !current.descending } : { key, descending: key === 'start' }));

  return (
    <section className="tasks-view">
      <div className="section-head">
        <h2><ListChecks size={20} />Tasks</h2>
        {tasks.data && <span className="section-note">{shown.length === all.length ? (all.length === 1 ? '1 task' : `${all.length} tasks`) : `${shown.length} of ${all.length} tasks`}</span>}
      </div>
      <div className="toolbar tasks-filters">
        <label>
          Status{' '}
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">All</option>
            {STATUSES.map((value) => <option key={value} value={value}>{TASK_STATUS_LABELS[value]}</option>)}
          </select>
        </label>
        <label>
          Agent{' '}
          <select value={agent} onChange={(event) => setAgent(event.target.value)}>
            <option value="">All</option>
            {agents.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <input type="search" className="tasks-search" aria-label="Search the tasks" placeholder="Search the tasks" maxLength={200} value={query}
          onChange={(event) => setQuery(event.target.value)} />
      </div>
      <QueryStatus query={tasks} what="the tasks" />
      {tasks.data && (all.length === 0
        ? <p className="empty-state card"><strong>No tasks yet</strong>Tasks appear here as the orchestrator hands work to its agents.</p>
        : (
          <div className="table-scroll card" role="region" aria-labelledby="tasks-caption" tabIndex={0}>
            <table className="data-table">
              <caption id="tasks-caption">The last {TASK_LIMIT} tasks, the most the orchestrator returns</caption>
              <thead>
                <tr>
                  {COLUMNS.map(({ key, label, numeric }) => (
                    <th key={key} scope="col" className={numeric ? 'numeric' : undefined}
                      aria-sort={sort.key === key ? (sort.descending ? 'descending' : 'ascending') : undefined}>
                      <button type="button" className="sort-button" onClick={() => sortBy(key)}>
                        {label}
                        {sort.key === key && (sort.descending ? <ArrowDown size={14} /> : <ArrowUp size={14} />)}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.length === 0 && (
                  <tr><td colSpan={COLUMNS.length} className="empty">No task matches the filters.</td></tr>
                )}
                {shown.map((task) => (
                  <tr key={task.task_id}>
                    <th scope="row">
                      <button type="button" className="link" onClick={() => openTask(task.task_id)}>{task.description}</button>
                    </th>
                    <td>{task.agent_name}</td>
                    <td><Aspect tone={TASK_STATUS_TONES[task.status]} quiet>{TASK_STATUS_LABELS[task.status]}</Aspect></td>
                    <td>{localDateTime(task.start_time)}</td>
                    <td className="numeric">{taskDuration(task, now)}</td>
                    <td className="numeric">{task.token_usage ? count(task.token_usage.total_tokens) : '—'}</td>
                    <td className="numeric">{taskCost(task)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </section>
  );
}

/** The duration of a finished task, or the time a running one has been running for. */
export function taskDuration(task: TaskInfo, now: number): string {
  if (task.duration_ms !== null) {
    return duration(task.duration_ms);
  }
  return task.status === 'RUNNING' ? duration(now - Date.parse(task.start_time)) : '—';
}

export function taskCost(task: TaskInfo): string {
  if (!task.token_usage) {
    return '—';
  }
  return task.token_usage.cost_usd === null ? 'Not priced' : usd(task.token_usage.cost_usd);
}
