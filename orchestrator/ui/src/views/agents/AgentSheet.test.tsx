// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearStreamToken } from '../../data/streamToken';
import { axeViolations, installDom } from '../../testing/dom';
import { agent, logEntry, task } from '../../testing/fixtures';
import { FakeEventSource, json, STREAM_TOKEN_PATH, streamToken, stubRoutes } from '../../testing/network';
import { renderView } from '../../testing/render';
import type { AgentInfo, LogEntry } from '../../types/dashboard';
import { AgentSheet } from './AgentSheet';

installDom();

let agents: AgentInfo[] | Promise<never> | Response = [];
let logs: LogEntry[] = [];

const TASKS = [
  task({ task_id: 'task-1', status: 'COMPLETED', duration_ms: 60_000, token_usage: null }),
  task({ task_id: 'task-2', description: 'Review story QA-8', status: 'FAILED', start_time: '2026-10-16T11:00:00Z', duration_ms: 20_000 }),
  task({ task_id: 'task-3', agent_id: 'ui', agent_name: 'UI test execution', description: 'Run TC-1' }),
  task({ task_id: 'task-4', description: 'Review story QA-9', status: 'RUNNING', start_time: '2026-10-16T12:00:00Z', end_time: null, duration_ms: null }),
];

describe('AgentSheet', () => {
  beforeEach(() => {
    logs = [logEntry({ id: 'task-1:1', task_id: 'task-1', message: 'Reading the story', timestamp: '' })];
    FakeEventSource.install();
    clearStreamToken();
    stubRoutes(({ path }) => {
      switch (path) {
        case STREAM_TOKEN_PATH:
          return streamToken('token');
        case '/api/dashboard/agents':
          return agents;
        case '/api/dashboard/tasks':
          return TASKS;
        case '/api/dashboard/logs':
          return logs;
        default:
          return [];
      }
    });
  });

  it('shows the running and recent tasks, the stats of the last 100 tasks and the capabilities, and streams the logs of its tasks', async () => {
    agents = [agent({ running_tasks: [{ task_id: 'task-4', description: 'Review story QA-9', start_time: new Date(Date.now() - 65_000).toISOString() }] })];
    const { navigation } = renderView(<AgentSheet agentId="requirements" onClose={vi.fn()} />);

    expect(await screen.findByRole('dialog', { name: 'Requirements review' })).toBeTruthy();
    expect(screen.getByText(/^running for 1\D+5/)).toBeTruthy();
    expect(await screen.findByText('From the last 100 tasks of all agents.')).toBeTruthy();
    expect(await screen.findByText(/^50 ?% \(1 of 2 finished\)$/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Review story QA-8' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Run TC-1' })).toBeNull();
    expect(screen.getByText('Streaming')).toBeTruthy();

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => FakeEventSource.latest().open());
    expect(await screen.findByText('[Review story QA-7]')).toBeTruthy();
    act(() => FakeEventSource.latest().emit('log_batch', { task_id: 'task-4', entries: [logEntry({ id: 'task-4:1', task_id: 'task-4', message: 'Next story' })] }));
    expect(screen.getByText('[Review story QA-9]')).toBeTruthy();
    expect(await axeViolations()).toEqual([]);

    fireEvent.click(screen.getByRole('button', { name: 'Open in Logs' }));
    expect(navigation.openLogs).toHaveBeenCalledWith({ kind: 'agent', agentId: 'requirements' });
    fireEvent.click(screen.getByRole('button', { name: 'Review story QA-8' }));
    expect(navigation.openTask).toHaveBeenCalledWith('task-2');
  });

  it('streams for an idle agent too, so a task that starts and ends between two polls reloads the tail', async () => {
    agents = [agent()];
    renderView(<AgentSheet agentId="requirements" onClose={vi.fn()} />);

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => FakeEventSource.latest().open());
    expect(await screen.findByText(/Reading the story/)).toBeTruthy();
    expect(screen.getByText('None.')).toBeTruthy();

    logs = [logEntry({ id: 'task-5:1', task_id: 'task-5', message: 'Quick review' }), ...logs];
    act(() => FakeEventSource.latest().emit('task_done', { task_id: 'task-5', agent_id: 'requirements', status: 'COMPLETED' }));
    expect(await screen.findByText(/Quick review/)).toBeTruthy();
  });

  it('shows the loading and the error state', async () => {
    agents = new Promise<never>(() => undefined);
    renderView(<AgentSheet agentId="requirements" onClose={vi.fn()} />);
    expect(screen.getByText('Loading the agent…')).toBeTruthy();

    agents = json({ detail: 'Bad request' }, { status: 400 });
    renderView(<AgentSheet agentId="requirements" onClose={vi.fn()} />);
    expect((await screen.findByRole('alert')).textContent).toContain('The orchestrator did not answer');
  });

  it('says that an agent no longer registered is gone', async () => {
    agents = [];
    renderView(<AgentSheet agentId="requirements" onClose={vi.fn()} />);

    expect(await screen.findByText('This agent is no longer registered.')).toBeTruthy();
    expect(await axeViolations()).toEqual([]);
  });
});
