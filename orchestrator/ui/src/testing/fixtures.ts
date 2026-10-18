// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import type { AgentInfo, DashboardSummary, ErrorInfo, LogEntry, TaskInfo } from '../types/dashboard';

export function agent(overrides: Partial<AgentInfo> = {}): AgentInfo {
  return {
    id: 'requirements', name: 'Requirements review', version: '1.2.0', description: 'Reviews user stories', url: 'http://requirements:8001',
    status: 'AVAILABLE', capabilities: { streaming: true }, running_tasks: [], task_capacity: 2, broken_reason: null, stuck_task_id: null,
    ...overrides,
  };
}

export function task(overrides: Partial<TaskInfo> = {}): TaskInfo {
  return {
    task_id: 'task-1', agent_id: 'requirements', agent_name: 'Requirements review', description: 'Review story QA-7', status: 'COMPLETED',
    start_time: '2026-10-16T10:00:00Z', end_time: '2026-10-16T10:01:00Z', duration_ms: 60_000, error_message: null, current_activity: null,
    token_usage: null, ...overrides,
  };
}

export function summary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    agents_total: 1, agents_available: 1, agents_busy: 0, agents_broken: 0, tasks_running: 0, tasks_completed: 9, tasks_failed: 1,
    tasks_total: 10, errors_total: 1, tokens_total: 1_234_000, cost_usd_total: 3.41, orchestrator_start_time: '2026-10-14T10:00:00Z',
    uptime_seconds: 180_000, current_time: '2026-10-16T12:00:00Z', orchestrator_model: 'gemini-3-flash', orchestrator_version: '4.0.0',
    ...overrides,
  };
}

export function error(overrides: Partial<ErrorInfo> = {}): ErrorInfo {
  return {
    error_id: 'error-1', timestamp: '2026-10-16T10:01:00Z', message: 'Jira did not answer', task_id: 'task-1', agent_id: 'requirements',
    module: 'orchestrator.main', traceback_snippet: 'Traceback (most recent call last):\n  TimeoutError', ...overrides,
  };
}

export function logEntry(overrides: Partial<LogEntry> = {}): LogEntry {
  return {
    id: 'task-1:1', timestamp: '2026-10-16T10:00:01', level: 'INFO', logger: 'agent.requirements', message: 'Reading the story',
    task_id: 'task-1', agent_id: 'requirements', ...overrides,
  };
}
