// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import type { AgentInfo, DashboardSummary, DiscoveryResult, ErrorInfo, LogEntry, RagSyncOutcome, TaskInfo } from '../types/dashboard';
import { DISCOVERY_TIMEOUT_MS, LOG_TIMEOUT_MS, request } from './client';

const BASE = '/api/dashboard';

/** The API's maximum, so the views see as much history as it gives. */
export const TASK_LIMIT = 100;
/** The size of the orchestrator's error buffer. */
export const ERROR_LIMIT = 50;
export const LOG_PAGE_SIZE = 100;

/** The API returns one log source per request: the orchestrator's own logs, or the execution logs of one agent or one task. */
export type LogSource = { kind: 'orchestrator' } | { kind: 'agent'; agentId: string } | { kind: 'task'; taskId: string; agentId: string };

export interface LogPageRequest {
  source: LogSource;
  level: string | null;
  offset: number;
  limit: number;
}

export const getSummary = (signal?: AbortSignal) => request<DashboardSummary>(`${BASE}/summary`, { signal });

export const getAgents = (signal?: AbortSignal) => request<AgentInfo[]>(`${BASE}/agents`, { signal });

export const getTasks = (signal?: AbortSignal) => request<TaskInfo[]>(`${BASE}/tasks`, { query: { limit: TASK_LIMIT }, signal });

export const getErrors = (signal?: AbortSignal) => request<ErrorInfo[]>(`${BASE}/errors`, { query: { limit: ERROR_LIMIT }, signal });

export const getRagSyncStatus = (signal?: AbortSignal) => request<RagSyncOutcome[]>(`${BASE}/rag-sync-status`, { signal });

/** A page of the source's log, newest first, `offset` entries below the newest. */
export function getLogPage({ source, level, offset, limit }: LogPageRequest, signal?: AbortSignal): Promise<LogEntry[]> {
  return request<LogEntry[]>(`${BASE}/logs`, {
    query: {
      limit,
      offset,
      level,
      agent_id: source.kind === 'agent' ? source.agentId : null,
      task_id: source.kind === 'task' ? source.taskId : null,
    },
    signal,
    timeoutMs: LOG_TIMEOUT_MS,
  });
}

export const triggerDiscovery = () => request<DiscoveryResult>(`${BASE}/discovery`, { method: 'POST', timeoutMs: DISCOVERY_TIMEOUT_MS });
