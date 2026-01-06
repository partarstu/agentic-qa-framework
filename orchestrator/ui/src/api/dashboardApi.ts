import axios from 'axios';
import type { DashboardSummary, AgentInfo, TaskInfo, ErrorInfo, LogEntry } from '../types/dashboard';

const API_BASE = '/api/dashboard';

/**
 * Dashboard API client for fetching orchestrator state.
 */
export const dashboardApi = {
  /**
   * Get high-level dashboard statistics.
   */
  async getSummary(): Promise<DashboardSummary> {
    const response = await axios.get<DashboardSummary>(`${API_BASE}/summary`);
    return response.data;
  },

  /**
   * Get detailed status of all registered agents.
   */
  async getAgents(): Promise<AgentInfo[]> {
    const response = await axios.get<AgentInfo[]>(`${API_BASE}/agents`);
    return response.data;
  },

  /**
   * Get recent tasks with their details.
   */
  async getTasks(limit: number = 50): Promise<TaskInfo[]> {
    const response = await axios.get<TaskInfo[]>(`${API_BASE}/tasks`, {
      params: { limit },
    });
    return response.data;
  },

  /**
   * Get recent errors with context.
   */
  async getErrors(limit: number = 20): Promise<ErrorInfo[]> {
    const response = await axios.get<ErrorInfo[]>(`${API_BASE}/errors`, {
      params: { limit },
    });
    return response.data;
  },

  /**
   * Get recent application logs.
   */
  async getLogs(limit: number = 100, level?: string): Promise<LogEntry[]> {
    const response = await axios.get<LogEntry[]>(`${API_BASE}/logs`, {
      params: { limit, level },
    });
    return response.data;
  },
};
