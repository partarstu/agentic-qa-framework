// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import type { Tone } from './kit/Aspect';
import type { AgentInfo, TaskInfo } from './types/dashboard';

type AgentStatus = AgentInfo['status'];
type BrokenReason = NonNullable<AgentInfo['broken_reason']>;
type TaskStatus = TaskInfo['status'];

export const AGENT_STATUS_LABELS: Record<AgentStatus, string> = {
  AVAILABLE: 'Available',
  BUSY: 'Busy',
  BROKEN: 'Broken',
};

export const AGENT_STATUS_TONES: Record<AgentStatus, Tone> = {
  AVAILABLE: 'passed',
  BUSY: 'running',
  BROKEN: 'failed',
};

export const BROKEN_REASON_LABELS: Record<BrokenReason, string> = {
  OFFLINE: 'Offline',
  TASK_STUCK: 'Task stuck',
};

export const BROKEN_REASON_TONES: Record<BrokenReason, Tone> = {
  OFFLINE: 'failed',
  TASK_STUCK: 'warning',
};

export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  PENDING: 'Pending',
  RUNNING: 'Running',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
  CANCELLED: 'Cancelled',
};

export const TASK_STATUS_TONES: Record<TaskStatus, Tone> = {
  PENDING: 'neutral',
  RUNNING: 'running',
  COMPLETED: 'passed',
  FAILED: 'failed',
  CANCELLED: 'neutral',
};
