// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryClient, useAgents, useErrors, useSummary, useTasks } from '../data/queries';
import { clearStreamToken } from '../data/streamToken';
import { useLogTail } from '../logs/useLogTail';
import { installDom } from '../testing/dom';
import { FakeEventSource, STREAM_TOKEN_PATH, streamToken, stubRoutes } from '../testing/network';
import type { AgentInfo } from '../types/dashboard';
import { ANNOUNCE_DELAY_MS, INVALIDATE_DELAY_MS } from './batching';
import { useLiveDashboard } from './useLiveDashboard';

installDom();

const PATHS = { agents: '/api/dashboard/agents', summary: '/api/dashboard/summary', tasks: '/api/dashboard/tasks', errors: '/api/dashboard/errors', logs: '/api/dashboard/logs' };

const agent = (runningTaskIds: string[]): AgentInfo => ({
  id: 'design', name: 'Design', version: '1.0.0', description: '', url: 'http://design', status: runningTaskIds.length > 0 ? 'BUSY' : 'AVAILABLE',
  capabilities: null, running_tasks: runningTaskIds.map((task_id) => ({ task_id, description: 'Design tests', start_time: '2026-10-16T10:00:00Z' })),
  task_capacity: 2, broken_reason: null, stuck_task_id: null,
});

let agents: AgentInfo[] = [];

/** The shell's live store beside the views' queries and an orchestrator log tail, as the dashboard mounts them. */
function renderDashboard() {
  const queryClient = createQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  return renderHook(() => {
    const { data } = useAgents();
    useSummary();
    useTasks();
    useErrors();
    useLogTail({ kind: 'orchestrator' }, { follow: false, level: null });
    return useLiveDashboard(data);
  }, { wrapper });
}

const settle = () => act(() => vi.advanceTimersByTimeAsync(0));

async function openStream() {
  await settle();
  const stream = FakeEventSource.latest();
  act(() => stream.open());
  act(() => stream.emit('snapshot', { version: 1, agents: [], running_tasks: [] }));
  return stream;
}

describe('useLiveDashboard', () => {
  let network: ReturnType<typeof stubRoutes>;

  beforeEach(() => {
    vi.useFakeTimers();
    FakeEventSource.install();
    clearStreamToken();
    agents = [agent([])];
    network = stubRoutes(({ path }) => {
      switch (path) {
        case STREAM_TOKEN_PATH:
          return streamToken('token');
        case PATHS.agents:
          return agents;
        case PATHS.summary:
          return {};
        case PATHS.logs:
          return [{ id: 'orch-1', timestamp: '2026-10-16T10:00:00', level: 'INFO', logger: 'orchestrator', message: 'Started' }];
        default:
          return [];
      }
    });
  });

  afterEach(() => vi.useRealTimers());

  const counts = () => Object.fromEntries(Object.entries(PATHS).map(([name, path]) => [name, network.count(path)]));

  it('refetches each query once for a burst of task ends and announces them in one sentence', async () => {
    const { result } = renderDashboard();
    const stream = await openStream();
    const before = counts();

    act(() => {
      for (let index = 0; index < 20; index += 1) {
        stream.emit('task_done', { task_id: `task-${index}`, agent_id: 'design', status: index < 15 ? 'COMPLETED' : 'FAILED' });
      }
    });
    await act(() => vi.advanceTimersByTimeAsync(INVALIDATE_DELAY_MS));

    expect(counts()).toEqual({ ...before, agents: before.agents + 1, summary: before.summary + 1, tasks: before.tasks + 1, errors: before.errors + 1 });
    await act(() => vi.advanceTimersByTimeAsync(ANNOUNCE_DELAY_MS));
    expect(result.current.announcement).toBe('15 tasks finished, 5 failed');
  });

  it('announces and refreshes a task start that the agents poll shows first', async () => {
    const { result } = renderDashboard();
    await openStream();
    await act(() => vi.advanceTimersByTimeAsync(INVALIDATE_DELAY_MS + ANNOUNCE_DELAY_MS));
    const before = counts();

    agents = [agent(['task-7'])];
    await act(() => vi.advanceTimersByTimeAsync(3_000));
    await act(() => vi.advanceTimersByTimeAsync(INVALIDATE_DELAY_MS));

    expect(result.current.live.running['task-7']).toBeDefined();
    expect(counts().tasks).toBe(before.tasks + 1);
    await act(() => vi.advanceTimersByTimeAsync(ANNOUNCE_DELAY_MS));
    expect(result.current.announcement).toBe('1 task started');
  });

  it('announces nothing for the tasks running when the page loads', async () => {
    agents = [agent(['task-1'])];
    const { result } = renderDashboard();
    await settle();
    const stream = FakeEventSource.latest();
    act(() => stream.emit('snapshot', { version: 1, agents: [], running_tasks: [{ task_id: 'task-1', agent_id: 'design', description: '', current_activity: null }] }));

    await act(() => vi.advanceTimersByTimeAsync(ANNOUNCE_DELAY_MS + INVALIDATE_DELAY_MS));

    expect(result.current.announcement).toBe('');
    expect(result.current.live.running['task-1']).toBeDefined();
  });

  it.each([
    ['a reconnect snapshot', (stream: FakeEventSource) => stream.emit('snapshot', { version: 1, agents: [], running_tasks: [] })],
    ['a gap', (stream: FakeEventSource) => stream.emit('gap', { reason: 'queue_overflow', since: 3, until: 3 })],
  ])('refetches every query on %s, but no loaded log page', async (_name, emit) => {
    renderDashboard();
    const stream = await openStream();
    await act(() => vi.advanceTimersByTimeAsync(INVALIDATE_DELAY_MS));
    const before = counts();

    act(() => emit(stream));
    await act(() => vi.advanceTimersByTimeAsync(INVALIDATE_DELAY_MS));

    expect(counts()).toEqual({ ...before, agents: before.agents + 1, summary: before.summary + 1, tasks: before.tasks + 1, errors: before.errors + 1 });
  });

  it('keeps the activity of a task with its receive time', async () => {
    vi.setSystemTime(new Date('2026-10-16T12:00:00Z'));
    const { result } = renderDashboard();
    const stream = await openStream();

    act(() => stream.emit('agent_activity', { task_id: 'task-2', agent_id: 'design', text: 'Classifying 4/9' }));

    expect(result.current.live.activity).toEqual([
      { key: 1, task_id: 'task-2', agent_id: 'design', text: 'Classifying 4/9', receivedAt: Date.parse('2026-10-16T12:00:00Z') },
    ]);
    expect(result.current.streamStatus).toBe('open');
  });
});
