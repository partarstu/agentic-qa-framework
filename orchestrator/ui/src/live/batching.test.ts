// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { QueryClient } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ANNOUNCE_DELAY_MS, createAnnouncer, createInvalidator, INVALIDATE_DELAY_MS, INVALIDATE_MAX_WAIT_MS, taskAnnouncement } from './batching';

describe('taskAnnouncement', () => {
  it.each([
    [{ started: 3, finished: 2, failed: 1, cancelled: 0 }, '3 tasks started, 2 finished, 1 failed'],
    [{ started: 1, finished: 0, failed: 0, cancelled: 0 }, '1 task started'],
    [{ started: 0, finished: 1, failed: 0, cancelled: 2 }, '1 task finished, 2 cancelled'],
    [{ started: 0, finished: 0, failed: 0, cancelled: 0 }, null],
  ])('words %o as %s', (counts, text) => {
    expect(taskAnnouncement(counts)).toBe(text);
  });
});

describe('createAnnouncer', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('announces a burst of task events as one sentence after the delay', () => {
    const announce = vi.fn();
    const announcer = createAnnouncer(announce);

    announcer.queue(2, []);
    vi.advanceTimersByTime(1_000);
    announcer.queue(1, ['COMPLETED', 'FAILED']);
    announcer.queue(0, ['COMPLETED']);
    vi.advanceTimersByTime(ANNOUNCE_DELAY_MS - 1_001);
    expect(announce).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);

    expect(announce).toHaveBeenCalledExactlyOnceWith('3 tasks started, 2 finished, 1 failed');
  });

  it('stays silent for events that neither start nor end a task', () => {
    const announce = vi.fn();
    createAnnouncer(announce).queue(0, []);

    vi.runAllTimers();

    expect(announce).not.toHaveBeenCalled();
  });
});

describe('createInvalidator', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function invalidator() {
    const queryClient = new QueryClient();
    const invalidateQueries = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue();
    return { invalidator: createInvalidator(queryClient), invalidateQueries };
  }

  it('invalidates each named query once, after the last request of a burst', () => {
    const { invalidator: queries, invalidateQueries } = invalidator();

    queries.invalidate(['tasks', 'summary']);
    vi.advanceTimersByTime(INVALIDATE_DELAY_MS - 1);
    queries.invalidate(['tasks', 'errors']);
    vi.advanceTimersByTime(INVALIDATE_DELAY_MS - 1);
    expect(invalidateQueries).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);

    expect(invalidateQueries.mock.calls).toEqual([
      [{ queryKey: ['tasks'] }, { cancelRefetch: false }],
      [{ queryKey: ['summary'] }, { cancelRefetch: false }],
      [{ queryKey: ['errors'] }, { cancelRefetch: false }],
    ]);
  });

  it('invalidates every query at once when asked for all', () => {
    const { invalidator: queries, invalidateQueries } = invalidator();

    queries.invalidate(['tasks']);
    queries.invalidate('all');
    vi.advanceTimersByTime(INVALIDATE_DELAY_MS);

    expect(invalidateQueries.mock.calls).toEqual([[undefined, { cancelRefetch: false }]]);
  });

  it('refreshes during a steady stream of requests at the latest after the maximum wait', () => {
    const { invalidator: queries, invalidateQueries } = invalidator();

    for (let elapsed = 0; elapsed < INVALIDATE_MAX_WAIT_MS; elapsed += INVALIDATE_DELAY_MS / 2) {
      queries.invalidate(['tasks']);
      vi.advanceTimersByTime(INVALIDATE_DELAY_MS / 2);
    }

    expect(invalidateQueries).toHaveBeenCalledOnce();
  });
});
