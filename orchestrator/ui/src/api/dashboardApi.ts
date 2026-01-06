import { apiClient } from './client';
import type { DashboardSummary, AgentInfo, TaskInfo, ErrorInfo, LogEntry } from '../types/dashboard';

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
  async getLogs(limit: number = 100, level?: string): Promise<LogEntry[]> {
    const response = await apiClient.get<LogEntry[]>('/logs', {
      params: { limit, level },
    });
    return response.data;
  },
};
