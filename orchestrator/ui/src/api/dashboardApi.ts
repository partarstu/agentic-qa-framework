// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { apiClient } from './client';
import type { DashboardSummary, AgentInfo, TaskInfo, ErrorInfo, LogEntry, RagSyncOutcome } from '../types/dashboard';

// Above the orchestrator's agent discovery timeout (AGENT_DISCOVERY_TIMEOUT_SECONDS, 120 s).
const DISCOVERY_TIMEOUT_MS = 130_000;

/**
 * Dashboard API client for fetching orchestrator state.
 */
export const dashboardApi = {
  /**
   * Get high-level dashboard statistics.
   */
  async getSummary(): Promise<DashboardSummary> {
    const response = await apiClient.get<DashboardSummary>('/summary');
    return response.data;
  },

  /**
   * Get detailed status of all registered agents.
   */
  async getAgents(): Promise<AgentInfo[]> {
    const response = await apiClient.get<AgentInfo[]>('/agents');
    return response.data;
  },

  /**
   * Get recent tasks with their details.
   */
  async getTasks(limit: number = 50): Promise<TaskInfo[]> {
    const response = await apiClient.get<TaskInfo[]>('/tasks', {
      params: { limit },
    });
    return response.data;
  },

  /**
   * Get recent errors with context.
   */
  async getErrors(limit: number = 20): Promise<ErrorInfo[]> {
    const response = await apiClient.get<ErrorInfo[]>('/errors', {
      params: { limit },
    });
    return response.data;
  },

  /**
   * Get recent application logs.
   */
  async getLogs(limit: number = 100, offset: number = 0, level?: string, taskId?: string, agentId?: string): Promise<LogEntry[]> {
    const response = await apiClient.get<LogEntry[]>('/logs', {
      params: { limit, offset, level, task_id: taskId, agent_id: agentId },
    });
    return response.data;
  },

  async getRagSyncStatus(): Promise<RagSyncOutcome[]> {
    const response = await apiClient.get<RagSyncOutcome[]>('/rag-sync-status');
    return response.data;
  },

  /**
   * Manually trigger agent discovery and return the server's summary of the run.
   * Probing every candidate takes far longer than the default request timeout.
   */
  async triggerDiscovery(): Promise<{ message: string }> {
    const response = await apiClient.post<{ message: string }>('/discovery', undefined, {
      timeout: DISCOVERY_TIMEOUT_MS,
    });
    return response.data;
  },
};
