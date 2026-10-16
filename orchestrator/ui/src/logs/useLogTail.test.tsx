// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LOG_PAGE_SIZE, type LogSource } from '../data/dashboardApi';
import { clearStreamToken } from '../data/streamToken';
import { installDom } from '../testing/dom';
import { FakeEventSource, STREAM_TOKEN_PATH, streamToken, stubRoutes } from '../testing/network';
import type { LogEntry } from '../types/dashboard';
import type { TailItem } from './tailItems';
import { FOLLOW_BACKFILL_PAGES, FOLLOW_POLL_MS, useLogTail } from './useLogTail';

installDom();

const LOGS_PATH = '/api/dashboard/logs';

/** The orchestrator's log, newest first, as the log endpoint pages it. */
let server: LogEntry[] = [];
let written = 0;
/** Runs as a page request reaches the server, before it reads the page. */
let beforePage: ((offset: number) => void) | null = null;
/** Holds every page response, read already, until it settles. */
let pageHeld: Promise<void> | null = null;

function write(count: number, { task = 'task-1', level = 'INFO' } = {}) {
  const lines = Array.from({ length: count }, () => {
    written += 1;
    return { id: `${task}:${written}`, timestamp: '', level, logger: 'agent.ui', message: `line ${written}`, task_id: task, agent_id: 'ui' };
  });
  server = [...lines.toReversed(), ...server];
  return lines;
}

const ids = (items: TailItem[]) => items.map((item) => (item.kind === 'entry' ? item.entry.id : `<${item.kind}>`));
const newest = (count: number, from = 0) => server.slice(from, from + count).map(({ id }) => id);
const settle = () => act(() => vi.advanceTimersByTimeAsync(0));

function renderTail(source: LogSource, follow: boolean, level: string | null = null) {
  return renderHook(({ followed }) => useLogTail(source, { follow: followed, level }), { initialProps: { followed: follow } });
}

describe('useLogTail', () => {
  let network: ReturnType<typeof stubRoutes>;

  beforeEach(() => {
    vi.useFakeTimers();
    FakeEventSource.install();
    clearStreamToken();
    server = [];
    written = 0;
    beforePage = null;
    pageHeld = null;
    network = stubRoutes(async ({ path, params }) => {
      if (path === STREAM_TOKEN_PATH) {
        return streamToken('token');
      }
      const offset = Number(params.get('offset'));
      beforePage?.(offset);
      const taskId = params.get('task_id');
      const level = params.get('level');
      const lines = server.filter((line) => (taskId === null || line.task_id === taskId) && (level === null || line.level === level));
      const page = lines.slice(offset, offset + Number(params.get('limit')));
      await pageHeld;
      return page;
    });
  });

  afterEach(() => vi.useRealTimers());

  const pageRequests = () => network.calls.filter(({ path }) => path === LOGS_PATH).map(({ params }) => [Number(params.get('offset')), Number(params.get('limit'))]);

  it('loads the newest page of a source it does not follow', async () => {
    write(150);

    const { result } = renderTail({ kind: 'orchestrator' }, false);
    await settle();

    expect(result.current.status).toBe('ready');
    expect(ids(result.current.items)).toEqual(newest(LOG_PAGE_SIZE));
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it('reloads and merges the newest page on every open of the agent stream, so no line falls between stream and page', async () => {
    write(5);
    const { result } = renderTail({ kind: 'agent', agentId: 'ui' }, true);
    await settle();
    expect(pageRequests()).toEqual([]);

    act(() => FakeEventSource.latest().open());
    await settle();
    expect(ids(result.current.items)).toEqual(newest(5));

    act(() => FakeEventSource.latest().emit('log_batch', { task_id: 'task-1', entries: write(2) }));
    act(() => FakeEventSource.latest().fail());
    write(3);
    await act(() => vi.advanceTimersByTimeAsync(1_000));
    const streamed = write(1);
    act(() => FakeEventSource.latest().emit('log_batch', { task_id: 'task-1', entries: streamed }));
    act(() => FakeEventSource.latest().open());
    await settle();

    expect(pageRequests()).toHaveLength(2);
    expect(ids(result.current.items)).toEqual(newest(11));
  });

  it('keeps only the lines of its own task and level from the stream', async () => {
    const { result } = renderTail({ kind: 'task', taskId: 'task-1', agentId: 'ui' }, true, 'ERROR');
    await settle();
    act(() => FakeEventSource.latest().open());
    await settle();

    act(() => FakeEventSource.latest().emit('log_batch', { task_id: 'task-2', entries: write(1, { task: 'task-2', level: 'ERROR' }) }));
    const errors = write(1, { level: 'ERROR' });
    act(() => FakeEventSource.latest().emit('log_batch', { task_id: 'task-1', entries: [...write(1), ...errors] }));

    expect(ids(result.current.items)).toEqual(errors.map(({ id }) => id));
  });

  it('marks the events the stream missed, and the lines skipped when a reopened stream\'s page meets no loaded line', async () => {
    write(3);
    const { result } = renderTail({ kind: 'agent', agentId: 'ui' }, true);
    await settle();
    act(() => FakeEventSource.latest().open());
    await settle();

    act(() => FakeEventSource.latest().emit('gap', { reason: 'queue_overflow', since: 4, until: 4 }));
    expect(ids(result.current.items)).toEqual(['<missed>', ...newest(3)]);

    const loaded = ids(result.current.items);
    write(LOG_PAGE_SIZE + 20);
    act(() => FakeEventSource.latest().fail());
    await act(() => vi.advanceTimersByTimeAsync(1_000));
    act(() => FakeEventSource.latest().open());
    await settle();

    expect(ids(result.current.items)).toEqual([...newest(LOG_PAGE_SIZE), '<skipped>', ...loaded]);
  });

  it('back-fills a followed orchestrator log page by page until it meets the loaded lines', async () => {
    write(LOG_PAGE_SIZE);
    const { result } = renderTail({ kind: 'orchestrator' }, true);
    await settle();

    write(2 * LOG_PAGE_SIZE + 50);
    await act(() => vi.advanceTimersByTimeAsync(FOLLOW_POLL_MS));

    expect(pageRequests().slice(1)).toEqual([[0, 100], [100, 100], [200, 100]]);
    expect(ids(result.current.items)).toEqual(newest(3 * LOG_PAGE_SIZE + 50).slice(0, 2 * LOG_PAGE_SIZE + 50 + LOG_PAGE_SIZE));
  });

  it('keeps each line once when lines arrive between the back-fill pages', async () => {
    write(LOG_PAGE_SIZE);
    const { result } = renderTail({ kind: 'orchestrator' }, true);
    await settle();

    write(2 * LOG_PAGE_SIZE + 50);
    beforePage = (offset) => {
      if (offset > 0) {
        write(30);
      }
    };
    await act(() => vi.advanceTimersByTimeAsync(FOLLOW_POLL_MS));

    const tail = ids(result.current.items);
    expect(new Set(tail).size).toBe(tail.length);
    // Every line up to the newest page; those written during the back-fill come with the next poll
    expect(tail).toEqual(Array.from({ length: 3 * LOG_PAGE_SIZE + 50 }, (_, index) => `task-1:${3 * LOG_PAGE_SIZE + 50 - index}`));
  });

  it('puts the page of a stream open below the lines streamed while it was on its way, without a skip', async () => {
    write(3);
    const { result } = renderTail({ kind: 'agent', agentId: 'ui' }, true);
    await settle();
    let release: () => void = () => undefined;
    pageHeld = new Promise((resolve) => {
      release = resolve;
    });
    act(() => FakeEventSource.latest().open());
    await settle();

    act(() => FakeEventSource.latest().emit('log_batch', { task_id: 'task-1', entries: write(1) }));
    await act(async () => release());
    await settle();

    expect(ids(result.current.items)).toEqual(newest(4));
  });

  it('orders a stream-open page that holds a streamed line and a newer one not streamed yet', async () => {
    write(3);
    const { result } = renderTail({ kind: 'agent', agentId: 'ui' }, true);
    await settle();
    const streamed = write(1);
    write(1);
    let release: () => void = () => undefined;
    pageHeld = new Promise((resolve) => {
      release = resolve;
    });
    act(() => FakeEventSource.latest().open());
    await settle();

    act(() => FakeEventSource.latest().emit('log_batch', { task_id: 'task-1', entries: streamed }));
    await act(async () => release());
    await settle();

    expect(ids(result.current.items)).toEqual(newest(5));
  });

  it('marks the lines skipped below a stream-open page that meets only the lines streamed while it was on its way', async () => {
    write(1);
    const { result } = renderTail({ kind: 'agent', agentId: 'ui' }, true);
    await settle();
    act(() => FakeEventSource.latest().open());
    await settle();
    act(() => FakeEventSource.latest().fail());
    const lines = write(LOG_PAGE_SIZE + 50);
    let release: () => void = () => undefined;
    pageHeld = new Promise((resolve) => {
      release = resolve;
    });
    await act(() => vi.advanceTimersByTimeAsync(1_000));
    act(() => FakeEventSource.latest().open());
    await settle();

    act(() => FakeEventSource.latest().emit('log_batch', { task_id: 'task-1', entries: lines.slice(-1) }));
    await act(async () => release());
    await settle();

    expect(ids(result.current.items)).toEqual([...newest(LOG_PAGE_SIZE), '<skipped>', 'task-1:1']);
  });

  it(`marks the lines skipped when ${FOLLOW_BACKFILL_PAGES} more pages do not reach the loaded lines`, async () => {
    write(10);
    const { result } = renderTail({ kind: 'orchestrator' }, true);
    await settle();
    const loaded = ids(result.current.items);

    write(10 * LOG_PAGE_SIZE);
    await act(() => vi.advanceTimersByTimeAsync(FOLLOW_POLL_MS));

    expect(pageRequests().slice(1)).toHaveLength(FOLLOW_BACKFILL_PAGES + 1);
    expect(ids(result.current.items)).toEqual([...newest((FOLLOW_BACKFILL_PAGES + 1) * LOG_PAGE_SIZE), '<skipped>', ...loaded]);
  });

  it('stops polling when paused', async () => {
    write(1);
    const { rerender } = renderTail({ kind: 'orchestrator' }, true);
    await settle();
    rerender({ followed: false });
    await settle();
    const requests = pageRequests().length;

    await act(() => vi.advanceTimersByTimeAsync(5 * FOLLOW_POLL_MS));

    expect(pageRequests()).toHaveLength(requests);
  });

  it('loads older lines below the tail even after more than a page of lines arrived while paused', async () => {
    write(3 * LOG_PAGE_SIZE);
    const { result } = renderTail({ kind: 'orchestrator' }, false);
    await settle();
    const loaded = ids(result.current.items);

    write(LOG_PAGE_SIZE + 50);
    act(() => result.current.loadOlder());
    await settle();

    // The 150 new lines pushed the loaded ones to positions 150-249, so the first page holds no older line and the second 50
    const belowTail = 2 * LOG_PAGE_SIZE + 50;
    expect(pageRequests().slice(1)).toEqual([[99, 101], [199, 101]]);
    expect(ids(result.current.items)).toEqual([...loaded, ...newest(50, belowTail)]);

    act(() => result.current.loadOlder());
    await settle();
    expect(ids(result.current.items)).toEqual([...loaded, ...newest(150, belowTail)]);
    expect(result.current.exhausted).toBe(false);

    act(() => result.current.loadOlder());
    await settle();
    expect(ids(result.current.items)).toEqual([...loaded, ...newest(200, belowTail)]);
    expect(result.current.exhausted).toBe(true);
  });

  it('ends the live tail of a finished task and reloads its page', async () => {
    const { result } = renderTail({ kind: 'task', taskId: 'task-1', agentId: 'ui' }, true);
    await settle();
    const stream = FakeEventSource.latest();
    act(() => stream.open());
    await settle();
    expect(result.current.items).toEqual([]);

    write(4);
    act(() => stream.emit('task_done', { task_id: 'task-1', agent_id: 'ui', status: 'COMPLETED' }));
    await settle();

    expect(result.current.taskDone).toBe(true);
    expect(stream.closed).toBe(true);
    expect(ids(result.current.items)).toEqual(newest(4));
  });

  it('starts a new tail for a new source', async () => {
    write(2);
    write(1, { task: 'task-2' });
    const { result, rerender } = renderHook(({ source }) => useLogTail(source, { follow: false, level: null }), {
      initialProps: { source: { kind: 'task', taskId: 'task-1', agentId: 'ui' } as LogSource },
    });
    await settle();
    expect(result.current.items).toHaveLength(2);

    rerender({ source: { kind: 'task', taskId: 'task-2', agentId: 'ui' } });
    await settle();

    expect(ids(result.current.items)).toEqual(['task-2:3']);
  });
});
