// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearStreamToken } from '../../data/streamToken';
import { axeViolations, installDom } from '../../testing/dom';
import { logEntry, task } from '../../testing/fixtures';
import { FakeEventSource, json, STREAM_TOKEN_PATH, streamToken, stubRoutes } from '../../testing/network';
import { renderView } from '../../testing/render';
import type { LogEntry, TaskInfo } from '../../types/dashboard';
import { TaskSheet } from './TaskSheet';

installDom();

const line = (n: number): LogEntry => logEntry({ id: `task-1:${n}`, message: `line ${n}`, timestamp: '' });

let tasks: TaskInfo[] | Promise<never> | Response = [];
/** Newest first. */
let logPage: LogEntry[] = [];

const lines = () => [...screen.getByRole('region', { name: 'Task logs' }).querySelectorAll('.log-line')].map((element) => element.textContent?.split(' - ')[1]);

describe('TaskSheet', () => {
  beforeEach(() => {
    FakeEventSource.install();
    clearStreamToken();
    logPage = [line(2), line(1)];
    stubRoutes(({ path }) => {
      switch (path) {
        case STREAM_TOKEN_PATH:
          return streamToken('token');
        case '/api/dashboard/tasks':
          return tasks;
        case '/api/dashboard/logs':
          return logPage;
        default:
          return [];
      }
    });
  });

  it('tails a running task: the newest page on the stream open, then the streamed lines without duplicates, until it ends', async () => {
    tasks = [task({ status: 'RUNNING', end_time: null, duration_ms: null, current_activity: 'Reading the story' })];
    renderView(<TaskSheet taskId="task-1" onClose={vi.fn()} />);

    expect(await screen.findByRole('dialog', { name: 'Review story QA-7' })).toBeTruthy();
    expect(screen.getByText('Reading the story')).toBeTruthy();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const stream = FakeEventSource.latest();
    expect(stream.url).toBe('/api/dashboard/agents/requirements/stream?stream_token=token');

    act(() => stream.open());
    await waitFor(() => expect(lines()).toEqual(['line 2', 'line 1']));
    act(() => stream.emit('log_batch', { task_id: 'task-1', entries: [line(2), line(3)] }));
    act(() => stream.emit('log_batch', { task_id: 'task-2', entries: [logEntry({ id: 'task-2:1', task_id: 'task-2', message: 'other task' })] }));
    expect(lines()).toEqual(['line 3', 'line 2', 'line 1']);

    logPage = [line(4), line(3), line(2), line(1)];
    act(() => stream.emit('task_done', { task_id: 'task-1', agent_id: 'requirements', status: 'COMPLETED' }));

    await waitFor(() => expect(lines()).toEqual(['line 4', 'line 3', 'line 2', 'line 1']));
    expect(stream.closed).toBe(true);
  });

  it('shows a finished task with its timing, error, usage per operation and log page, and opens it in Logs', async () => {
    tasks = [task({
      status: 'FAILED', error_message: 'Jira did not answer',
      token_usage: {
        model_name: 'gemini-3-flash', input_tokens: 900, output_tokens: 100, total_tokens: 1_000, cache_read_tokens: 0, requests: 2, tool_calls: 1, cost_usd: null,
        operations: [
          { operation: 'main', model_name: 'gemini-3-flash', requests: 1, uncached_input_tokens: 600, cache_read_tokens: 0, cache_write_tokens: 0, output_tokens: 150, tool_calls: 1, cost_usd: null },
          { operation: 'classifier', model_name: 'gemini-3-flash', requests: 1, uncached_input_tokens: 200, cache_read_tokens: 0, cache_write_tokens: 0, output_tokens: 50, tool_calls: 0, cost_usd: 0.0012 },
        ],
      },
    })];
    const { navigation } = renderView(<TaskSheet taskId="task-1" onClose={vi.fn()} />);

    await waitFor(() => expect(lines()).toEqual(['line 2', 'line 1']));
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(screen.getByText('Jira did not answer')).toBeTruthy();
    expect(within(screen.getByRole('list', { name: 'Tokens by operation' })).getAllByRole('listitem').map((item) => item.textContent))
      .toEqual([expect.stringMatching(/^main: 750 tokens/), expect.stringMatching(/^classifier: 250 tokens/)]);
    expect(screen.getByRole('rowheader', { name: 'classifier' })).toBeTruthy();
    expect(screen.getAllByText('Not priced').length).toBeGreaterThan(0);
    expect(await axeViolations()).toEqual([]);

    fireEvent.click(screen.getByRole('button', { name: 'Open in Logs' }));
    expect(navigation.openLogs).toHaveBeenCalledWith({ kind: 'task', taskId: 'task-1', agentId: 'requirements' });
  });

  it('opens the agent of the task and closes with its button', async () => {
    tasks = [task()];
    const onClose = vi.fn();
    const { navigation } = renderView(<TaskSheet taskId="task-1" onClose={onClose} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Requirements review' }));
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));

    expect(navigation.openAgent).toHaveBeenCalledWith('requirements');
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('says that a task outside the loaded list is not among the last 100', async () => {
    tasks = [];
    renderView(<TaskSheet taskId="task-7" onClose={vi.fn()} />);

    expect(await screen.findByText(/Not among the last 100 tasks/)).toBeTruthy();
    expect(screen.getByRole('dialog', { name: 'Task' })).toBeTruthy();
  });

  it('shows the loading and the error state', async () => {
    tasks = new Promise<never>(() => undefined);
    renderView(<TaskSheet taskId="task-1" onClose={vi.fn()} />);
    expect(screen.getByText('Loading the task…')).toBeTruthy();

    tasks = json({ detail: 'Bad request' }, { status: 400 });
    renderView(<TaskSheet taskId="task-1" onClose={vi.fn()} />);
    expect((await screen.findByRole('alert')).textContent).toContain('The orchestrator did not answer');
  });

  it('stays closed and loads nothing without a task', () => {
    const network = stubRoutes(() => []);
    renderView(<TaskSheet taskId={null} onClose={vi.fn()} />);

    expect((document.querySelector('dialog') as HTMLDialogElement).open).toBe(false);
    expect(network.calls).toHaveLength(0);
  });
});
