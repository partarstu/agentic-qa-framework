// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { Activity, ScrollText } from 'lucide-react';
import { StackedBar } from '../../charts/StackedBar';
import { TASK_LIMIT } from '../../data/dashboardApi';
import { useTasks } from '../../data/queries';
import { count, localDateTime, usd } from '../../format';
import { Aspect } from '../../kit/Aspect';
import { ClampedError } from '../../kit/ClampedError';
import { TASK_STATUS_LABELS, TASK_STATUS_TONES } from '../../labels';
import { useLive } from '../../live/useLiveDashboard';
import { LogTail } from '../../logs/LogTail';
import { useLogTail } from '../../logs/useLogTail';
import { useNavigation } from '../../navigation';
import type { OperationUsage, TaskInfo, TokenUsage } from '../../types/dashboard';
import { useNow } from '../../useNow';
import { QueryStatus } from '../QueryStatus';
import { Sheet } from '../Sheet';
import { isTaskActive } from '../taskStats';
import { taskCost, taskDuration, TaskTitleMorph } from './TasksView';

const operationTokens = (operation: OperationUsage) =>
  operation.uncached_input_tokens + operation.cache_read_tokens + operation.cache_write_tokens + operation.output_tokens;

/** The task sheet: timing, error, token usage per operation and the task's log tail; a task outside the last {@link TASK_LIMIT} says so. */
export function TaskSheet({ taskId, onClose }: { taskId: string | null; onClose: () => void }) {
  const tasks = useTasks(taskId !== null);
  const task = tasks.data?.find(({ task_id }) => task_id === taskId);
  return (
    <Sheet open={taskId !== null} title={task ? <TaskTitleMorph taskId={task.task_id}>{task.description}</TaskTitleMorph> : 'Task'} onClose={onClose}>
      {taskId !== null && (task ? <TaskDetails task={task} /> : (
        <>
          <QueryStatus query={tasks} what="the task" />
          {tasks.data && <p className="note">Not among the last {TASK_LIMIT} tasks, the most the orchestrator returns.</p>}
        </>
      ))}
    </Sheet>
  );
}

function TaskDetails({ task }: { task: TaskInfo }) {
  const live = useLive();
  const { openAgent, openLogs } = useNavigation();
  const now = useNow(1_000);
  const liveTask = live.running[task.task_id];
  const running = isTaskActive(live.running, task.task_id, task.status);
  const source = { kind: 'task', taskId: task.task_id, agentId: task.agent_id } as const;
  const tail = useLogTail(source, { follow: running, level: null });
  const activity = liveTask?.current_activity ?? task.current_activity;

  return (
    <>
      <p className="sheet-status">
        <Aspect tone={TASK_STATUS_TONES[task.status]}>{TASK_STATUS_LABELS[task.status]}</Aspect>
      </p>
      {running && activity && <p className="activity-line"><Activity size={16} aria-hidden="true" /><span className="visually-hidden">Now: </span>{activity}</p>}
      <dl className="facts">
        <dt>Agent</dt>
        <dd><button type="button" className="link" onClick={() => openAgent(task.agent_id)}>{task.agent_name}</button></dd>
        <dt>Task ID</dt>
        <dd>{task.task_id}</dd>
        <dt>Started</dt>
        <dd>{localDateTime(task.start_time)}</dd>
        <dt>Ended</dt>
        <dd>{task.end_time ? localDateTime(task.end_time) : '—'}</dd>
        <dt>Duration</dt>
        <dd>{taskDuration(task, now)}</dd>
      </dl>
      {task.error_message && (
        <section className="sheet-section">
          <h3>Error</h3>
          <ClampedError text={task.error_message} />
        </section>
      )}
      <section className="sheet-section">
        <h3>Token usage</h3>
        {task.token_usage ? <TokenUsageDetails usage={task.token_usage} cost={taskCost(task)} /> : <p className="empty">None recorded.</p>}
      </section>
      <LogTail title="Task logs" tail={tail} />
      <div className="sheet-actions">
        <button type="button" onClick={() => openLogs(source)}><ScrollText size={18} />Open in Logs</button>
      </div>
    </>
  );
}

function TokenUsageDetails({ usage, cost }: { usage: TokenUsage; cost: string }) {
  const operations = usage.operations ?? [];
  return (
    <>
      <dl className="facts">
        <dt>Model</dt>
        <dd>{usage.model_name}</dd>
        <dt>Tokens</dt>
        <dd>{count(usage.total_tokens)} ({count(usage.input_tokens)} in, {count(usage.output_tokens)} out, {count(usage.cache_read_tokens)} from cache)</dd>
        <dt>Requests</dt>
        <dd>{count(usage.requests)}, {count(usage.tool_calls)} tool calls</dd>
        <dt>Cost</dt>
        <dd>{cost}</dd>
      </dl>
      {operations.length > 0 && (
        <>
          <StackedBar label="Tokens by operation" format={(value) => `${count(value)} tokens`}
            parts={operations.map((operation) => ({ label: operation.operation, value: operationTokens(operation) }))} />
          <div className="table-scroll" role="region" aria-label="Usage by operation" tabIndex={0}>
            <table className="data-table">
              <caption className="visually-hidden">Usage by operation</caption>
              <thead>
                <tr>
                  <th scope="col">Operation</th>
                  <th scope="col">Model</th>
                  <th scope="col" className="numeric">Requests</th>
                  <th scope="col" className="numeric">Input</th>
                  <th scope="col" className="numeric">From cache</th>
                  <th scope="col" className="numeric">Output</th>
                  <th scope="col" className="numeric">Tool calls</th>
                  <th scope="col" className="numeric">Cost</th>
                </tr>
              </thead>
              <tbody>
                {operations.map((operation) => (
                  <tr key={operation.operation}>
                    <th scope="row">{operation.operation}</th>
                    <td>{operation.model_name}</td>
                    <td className="numeric">{count(operation.requests)}</td>
                    <td className="numeric">{count(operation.uncached_input_tokens + operation.cache_write_tokens)}</td>
                    <td className="numeric">{count(operation.cache_read_tokens)}</td>
                    <td className="numeric">{count(operation.output_tokens)}</td>
                    <td className="numeric">{count(operation.tool_calls)}</td>
                    <td className="numeric">{operation.cost_usd === null ? 'Not priced' : usd(operation.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
