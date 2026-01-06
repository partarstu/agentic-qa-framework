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
  orchestrator_start_time: string;
  uptime_seconds: number;
  current_time: string;
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
