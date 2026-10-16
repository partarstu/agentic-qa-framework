// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import type { QueryClient } from '@tanstack/react-query';
import { QUERY_KEYS, type QueryName } from '../data/queries';
import type { TaskInfo } from '../types/dashboard';

export const ANNOUNCE_DELAY_MS = 3_000;
export const INVALIDATE_DELAY_MS = 1_000;
export const INVALIDATE_MAX_WAIT_MS = 5_000;

interface TaskCounts {
  started: number;
  finished: number;
  failed: number;
  cancelled: number;
}

const END_COUNTS: Partial<Record<TaskInfo['status'], keyof TaskCounts>> = { COMPLETED: 'finished', FAILED: 'failed', CANCELLED: 'cancelled' };

/** One sentence for a batch of task starts and ends, such as "3 tasks started, 2 finished, 1 failed", or null for none. */
export function taskAnnouncement(counts: TaskCounts): string | null {
  const parts = (Object.entries(counts) as [keyof TaskCounts, number][]).filter(([, count]) => count > 0);
  if (parts.length === 0) {
    return null;
  }
  return parts
    .map(([word, count], index) => (index === 0 ? `${count} ${count === 1 ? 'task' : 'tasks'} ${word}` : `${count} ${word}`))
    .join(', ');
}

/**
 * Collects task starts and ends and announces them together once ANNOUNCE_DELAY_MS have passed since the first, so a burst of
 * task events makes one announcement rather than dozens.
 */
export function createAnnouncer(announce: (text: string) => void) {
  let counts: TaskCounts = { started: 0, finished: 0, failed: 0, cancelled: 0 };
  let timer: ReturnType<typeof setTimeout> | undefined;
  const flush = () => {
    timer = undefined;
    const text = taskAnnouncement(counts);
    counts = { started: 0, finished: 0, failed: 0, cancelled: 0 };
    if (text !== null) {
      announce(text);
    }
  };
  return {
    queue(started: number, ended: TaskInfo['status'][]) {
      counts.started += started;
      for (const status of ended) {
        const key = END_COUNTS[status];
        if (key) {
          counts[key] += 1;
        }
      }
      if (timer === undefined && taskAnnouncement(counts) !== null) {
        timer = setTimeout(flush, ANNOUNCE_DELAY_MS);
      }
    },
    dispose() {
      clearTimeout(timer);
    },
  };
}

/**
 * Invalidates the named queries, or all, INVALIDATE_DELAY_MS after the last request (trailing), so a burst of task ends refetches each
 * query once; a refetch in flight runs on. A steady stream of events still refreshes the views every INVALIDATE_MAX_WAIT_MS.
 */
export function createInvalidator(queryClient: QueryClient) {
  let pending = new Set<QueryName>();
  let all = false;
  let firstRequestAt: number | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const flush = () => {
    if (all) {
      void queryClient.invalidateQueries(undefined, { cancelRefetch: false });
    } else {
      pending.forEach((name) => void queryClient.invalidateQueries({ queryKey: QUERY_KEYS[name] }, { cancelRefetch: false }));
    }
    pending = new Set();
    all = false;
    firstRequestAt = null;
  };
  return {
    invalidate(names: QueryName[] | 'all') {
      if (names === 'all') {
        all = true;
      } else {
        names.forEach((name) => pending.add(name));
      }
      firstRequestAt ??= Date.now();
      clearTimeout(timer);
      timer = setTimeout(flush, Math.min(INVALIDATE_DELAY_MS, firstRequestAt + INVALIDATE_MAX_WAIT_MS - Date.now()));
    },
    dispose() {
      clearTimeout(timer);
    },
  };
}
