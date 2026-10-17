// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { LogSource } from '../../data/dashboardApi';
import { clearStreamToken } from '../../data/streamToken';
import { INITIAL_LIVE_STATE } from '../../live/liveState';
import { axeViolations, installDom } from '../../testing/dom';
import { agent, logEntry, task } from '../../testing/fixtures';
import { FakeEventSource, json, STREAM_TOKEN_PATH, streamToken, stubRoutes, type FetchCall } from '../../testing/network';
import { renderView } from '../../testing/render';
import type { LogEntry, TaskInfo } from '../../types/dashboard';
import { LogsView } from './LogsView';

installDom();

const ORCHESTRATOR: LogSource = { kind: 'orchestrator' };
const AGENT: LogSource = { kind: 'agent', agentId: 'requirements' };

let logs: LogEntry[] | Promise<never> | Response = [];
let tasks: TaskInfo[] = [];
let network: { calls: FetchCall[] };

const logRequests = () => network.calls.filter(({ path }) => path === '/api/dashboard/logs').map(({ params }) => Object.fromEntries(params));
const taskRequests = () => network.calls.filter(({ path }) => path === '/api/dashboard/tasks');
const shownLines = () => [...document.querySelectorAll('.log-line')].map((line) => line.textContent?.split(' - ')[1]);

describe('LogsView', () => {
  beforeEach(() => {
    FakeEventSource.install();
    clearStreamToken();
    logs = [logEntry({ id: 'orchestrator-1', task_id: null, logger: 'orchestrator.main', message: 'Started', timestamp: '2026-10-16T10:00:00' })];
    tasks = [task()];
    network = stubRoutes(({ path }) => {
      switch (path) {
        case STREAM_TOKEN_PATH:
          return streamToken('token');
        case '/api/dashboard/agents':
          return [agent()];
        case '/api/dashboard/tasks':
          return tasks;
        case '/api/dashboard/logs':
          return logs;
        default:
          return [];
      }
    });
  });

  it('loads the orchestrator log first and offers every agent as a source', async () => {
    const onSource = vi.fn();
    renderView(<LogsView source={ORCHESTRATOR} onSource={onSource} />);

    expect(await screen.findByText(/Started/)).toBeTruthy();
    expect(logRequests()[0]).toEqual({ limit: '100', offset: '0' });
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(screen.getByText('Following the newest lines.').getAttribute('role')).toBe('status');
    expect(taskRequests()).toEqual([]);

    fireEvent.change(await screen.findByRole('combobox', { name: 'Source' }), { target: { value: 'agent:requirements' } });
    expect(onSource).toHaveBeenCalledWith(AGENT);
    expect(await axeViolations()).toEqual([]);
  });

  it('asks the server for one level', async () => {
    renderView(<LogsView source={ORCHESTRATOR} onSource={vi.fn()} />);
    await screen.findByText(/Started/);

    fireEvent.change(screen.getByRole('combobox', { name: 'Level' }), { target: { value: 'ERROR' } });

    await waitFor(() => expect(logRequests().at(-1)).toEqual({ limit: '100', offset: '0', level: 'ERROR' }));
  });

  it('follows an agent source over its stream, labelling each line with its task, and pauses while a sheet owns the stream', async () => {
    logs = [];
    const { rerender } = renderView(<LogsView source={AGENT} onSource={vi.fn()} />);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const stream = FakeEventSource.latest();
    expect(stream.url).toBe('/api/dashboard/agents/requirements/stream?stream_token=token');

    act(() => stream.open());
    await waitFor(() => expect(logRequests()).toEqual([{ limit: '100', offset: '0', agent_id: 'requirements' }]));
    act(() => stream.emit('log_batch', { task_id: 'task-1', entries: [logEntry({ message: 'Reading the story' })] }));
    expect(shownLines()).toEqual(['Reading the story']);
    expect(await screen.findByText('[Review story QA-7]')).toBeTruthy();

    rerender(<LogsView source={AGENT} onSource={vi.fn()} />, { sheetOpen: true });
    expect(stream.closed).toBe(true);
    expect(screen.getByText('Following pauses while a sheet is open.')).toBeTruthy();

    rerender(<LogsView source={AGENT} onSource={vi.fn()} />, { sheetOpen: false });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
  });

  it('stops following on Pause', async () => {
    renderView(<LogsView source={AGENT} onSource={vi.fn()} />);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));

    expect(FakeEventSource.latest().closed).toBe(true);
    expect(screen.getByRole('button', { name: 'Follow' })).toBeTruthy();
    expect(screen.getByText('Paused.')).toBeTruthy();
  });

  it('loads a finished task source once and opens no stream for it', async () => {
    renderView(<LogsView source={{ kind: 'task', taskId: 'task-7', agentId: 'requirements' }} onSource={vi.fn()} />);

    expect(await screen.findByText(/Started/)).toBeTruthy();
    expect(logRequests()).toEqual([{ limit: '100', offset: '0', task_id: 'task-7' }]);
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(screen.getByText('The task has ended, so its log is complete.')).toBeTruthy();
  });

  it('follows a running task source over its agent stream', async () => {
    renderView(<LogsView source={{ kind: 'task', taskId: 'task-7', agentId: 'requirements' }} onSource={vi.fn()} />, {
      live: { ...INITIAL_LIVE_STATE, running: { 'task-7': { task_id: 'task-7', agent_id: 'requirements', current_activity: null } } },
    });

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(screen.getByText('Following the newest lines.')).toBeTruthy();
  });

  it('names a task source after the task and keeps it among the choices', async () => {
    tasks = [task({ task_id: 'task-7', description: 'Run TC-7' })];
    renderView(<LogsView source={{ kind: 'task', taskId: 'task-7', agentId: 'requirements' }} onSource={vi.fn()} />);

    const select = await screen.findByRole<HTMLSelectElement>('combobox', { name: 'Source' });
    await waitFor(() => expect(select.selectedOptions[0].textContent).toBe('Task: Run TC-7'));
  });

  it('says when the source has no lines yet', async () => {
    logs = [];
    renderView(<LogsView source={ORCHESTRATOR} onSource={vi.fn()} />);
    expect(await screen.findByText('No log lines yet.')).toBeTruthy();
  });

  it('shows the loading and error states', async () => {
    logs = new Promise<never>(() => undefined);
    renderView(<LogsView source={ORCHESTRATOR} onSource={vi.fn()} />);
    expect(screen.getByText('Loading the log…')).toBeTruthy();

    logs = json({ detail: 'Bad request' }, { status: 400 });
    renderView(<LogsView source={ORCHESTRATOR} onSource={vi.fn()} />);
    expect((await screen.findByRole('alert')).textContent).toContain('The log could not be loaded');
  });
});
