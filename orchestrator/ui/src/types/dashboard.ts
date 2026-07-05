// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

/**
 * Type definitions for the Dashboard API responses.
 */

export interface DashboardSummary {
  agents_total: number;
  agents_available: number;
  agents_busy: number;
  agents_broken: number;
  tasks_running: number;
  tasks_completed: number;
  tasks_failed: number;
  tasks_total: number;
  errors_total: number;
  tokens_total: number;
  cost_usd_total: number | null;
  orchestrator_start_time: string;
  uptime_seconds: number;
  current_time: string;
  orchestrator_model: string;
}

export interface TokenUsage {
  model_name: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_read_tokens: number;
  requests: number;
  tool_calls: number;
  cost_usd: number | null;
}

export interface AgentCapabilities {
  streaming?: boolean;
  pushNotifications?: boolean;
  stateTransitionHistory?: boolean;
}

export interface CurrentTask {
  task_id: string;
  description: string;
  start_time: string;
}

export interface AgentInfo {
  id: string;
  name: string;
  description: string;
  url: string;
  status: 'AVAILABLE' | 'BUSY' | 'BROKEN';
  capabilities: AgentCapabilities | null;
  current_task: CurrentTask | null;
  broken_reason: 'OFFLINE' | 'TASK_STUCK' | null;
  stuck_task_id: string | null;
}

export interface TaskInfo {
  task_id: string;
  agent_id: string;
  agent_name: string;
  description: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  start_time: string;
  end_time: string | null;
  duration_ms: number | null;
  error_message: string | null;
  token_usage: TokenUsage | null;
}

export interface ErrorInfo {
  error_id: string;
  timestamp: string;
  message: string;
  task_id: string | null;
  agent_id: string | null;
  module: string | null;
  traceback_snippet: string | null;
}

export interface LogEntry {
  timestamp: string;
  level: string;
  logger: string;
  message: string;
  task_id?: string | null;
  agent_id?: string | null;
}

// SSE live-state overlay (keyed by task_id in App.tsx)
export interface TaskLiveState {
  task_id: string;
  agent_id: string;
  current_activity: string | null;
}

// SSE event payload shapes
export interface SnapshotPayload {
  version: number;
  running_tasks: Array<{
    task_id: string;
    agent_id: string;
    description: string;
    current_activity: string | null;
  }>;
}

export interface AgentActivityPayload {
  task_id: string;
  agent_id: string;
  text: string;
}

export interface TaskDonePayload {
  task_id: string;
  agent_id: string;
  status: string;
  error_message?: string | null;
}

export interface LogBatchPayload {
  task_id: string;
  lines: string[];
}
