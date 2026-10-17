// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import type { LiveTask } from '../live/liveState';
import type { TaskInfo } from '../types/dashboard';

export interface TaskStats {
  total: number;
  completed: number;
  failed: number;
  /** Completed ÷ (completed + failed), or null before a task finished either way. */
  successRate: number | null;
  averageDurationMs: number | null;
  tokens: number;
  /** Null while no task has a price. */
  costUsd: number | null;
}

export function successRate(completed: number, failed: number): number | null {
  return completed + failed === 0 ? null : completed / (completed + failed);
}

export function taskStats(tasks: TaskInfo[]): TaskStats {
  const completed = tasks.filter(({ status }) => status === 'COMPLETED').length;
  const failed = tasks.filter(({ status }) => status === 'FAILED').length;
  const durations = tasks.flatMap(({ duration_ms }) => (duration_ms === null ? [] : [duration_ms]));
  const costs = tasks.flatMap(({ token_usage }) => (token_usage?.cost_usd == null ? [] : [token_usage.cost_usd]));
  return {
    total: tasks.length,
    completed,
    failed,
    successRate: successRate(completed, failed),
    averageDurationMs: durations.length === 0 ? null : durations.reduce((sum, value) => sum + value, 0) / durations.length,
    tokens: tasks.reduce((sum, { token_usage }) => sum + (token_usage?.total_tokens ?? 0), 0),
    costUsd: costs.length === 0 ? null : costs.reduce((sum, value) => sum + value, 0),
  };
}

/** Whether a task may still write log lines: the live store runs it, or its last known status is pending or running. */
export function isTaskActive(running: Record<string, LiveTask>, taskId: string, status: TaskInfo['status'] | undefined): boolean {
  return running[taskId] !== undefined || status === 'RUNNING' || status === 'PENDING';
}

/** Newest first, whatever order the list came in. */
export function newestFirst(tasks: TaskInfo[]): TaskInfo[] {
  return tasks.toSorted((first, second) => second.start_time.localeCompare(first.start_time));
}
