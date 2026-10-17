// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useState, useSyncExternalStore } from 'react';
import { getLogPage, LOG_PAGE_SIZE, type LogSource } from '../data/dashboardApi';
import { useEventStream, usePageVisible } from '../live/useEventStream';
import type { LogBatchPayload, LogEntry, TaskDonePayload } from '../types/dashboard';
import { appendOlder, entryCount, mergeNewest, overlaps, prependStreamed, type TailItem } from './tailItems';

export const FOLLOW_POLL_MS = 3_000;
/** How many pages past the newest a followed orchestrator log fetches to meet the loaded lines before it marks a skip. */
export const FOLLOW_BACKFILL_PAGES = 5;
/** How many older pages one "Load older" fetches at most while they bring no older line. */
export const OLDER_ATTEMPTS = 3;

export interface TailSnapshot {
  /** Newest first. */
  items: TailItem[];
  status: 'loading' | 'ready' | 'error';
  loadingOlder: boolean;
  olderFailed: boolean;
  /** The oldest line of the source is loaded. */
  exhausted: boolean;
  /** The followed task finished, so its tail no longer streams. */
  taskDone: boolean;
}

const INITIAL_SNAPSHOT: TailSnapshot = { items: [], status: 'loading', loadingOlder: false, olderFailed: false, exhausted: false, taskDone: false };

/** The lines of one source at one level; a new source or level starts a new tail. */
class Tail {
  private snapshot = INITIAL_SNAPSHOT;
  private readonly listeners = new Set<() => void>();
  private olderCursor: number | null = null;
  private markers = 0;
  private newestInFlight = false;
  /** How many items the stream has put on top so far. */
  private prepended = 0;

  constructor(readonly key: string, private readonly source: LogSource, private readonly level: string | null) {}

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = () => this.snapshot;

  private update(patch: Partial<TailSnapshot>) {
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach((listener) => listener());
  }

  private page(offset: number, limit: number, signal?: AbortSignal): Promise<LogEntry[]> {
    return getLogPage({ source: this.source, level: this.level, offset, limit }, signal);
  }

  /** Merges the newest page, fetching up to `backfillPages` further pages while they meet no loaded line, unless `poll` finds one running. */
  async loadNewest(backfillPages: number, { signal, poll = false }: { signal?: AbortSignal; poll?: boolean } = {}) {
    if (poll && this.newestInFlight) {
      return;
    }
    this.newestInFlight = true;
    const prependedBefore = this.prepended;
    try {
      // Lines written between two page requests shift the next page, which then repeats the end of the last one
      const fetched = new Map<string, LogEntry>();
      for (let page = 0; page <= backfillPages; page += 1) {
        const entries = await this.page(page * LOG_PAGE_SIZE, LOG_PAGE_SIZE, signal);
        entries.forEach((entry) => fetched.has(entry.id) || fetched.set(entry.id, entry));
        if (this.snapshot.items.length === 0 || overlaps(this.snapshot.items, entries) || entries.length < LOG_PAGE_SIZE) {
          break;
        }
      }
      const page = [...fetched.values()];
      const items = this.snapshot.items;
      const newer = items.slice(0, this.prepended - prependedBefore);
      const rest = items.slice(newer.length);
      const skipped = () => this.marker('skipped');
      let merged: TailItem[];
      if (!overlaps(newer, page)) {
        // A page sharing no line with what the stream prepended while it was in flight is older than those lines
        merged = [...newer, ...mergeNewest(rest, page, skipped)];
      } else if (entryCount(rest) > 0 && !overlaps(rest, page)) {
        merged = [...mergeNewest(newer, page, skipped), skipped(), ...rest];
      } else {
        merged = mergeNewest(items, page, skipped);
      }
      this.update({ items: merged, status: 'ready' });
    } catch {
      if (!signal?.aborted && this.snapshot.status === 'loading') {
        this.update({ status: 'error' });
      }
    } finally {
      this.newestInFlight = false;
    }
  }

  /** Appends the next older lines, fetching up to OLDER_ATTEMPTS pages while they bring none. */
  async loadOlder() {
    // The cursor starts at the number of loaded lines and advances a page per fetch: lines arriving at the top only push the older
    // ones further down, so it can overlap the tail but never skip past it
    if (this.snapshot.loadingOlder || this.snapshot.exhausted) {
      return;
    }
    this.update({ loadingOlder: true, olderFailed: false });
    try {
      for (let attempt = 0; attempt < OLDER_ATTEMPTS; attempt += 1) {
        const cursor = this.olderCursor ?? entryCount(this.snapshot.items);
        // One line into the tail, so a page right below it shows where it joins
        const offset = Math.max(cursor - 1, 0);
        const limit = LOG_PAGE_SIZE + (cursor - offset);
        const page = await this.page(offset, limit);
        this.olderCursor = cursor + LOG_PAGE_SIZE;
        const { items, added } = appendOlder(this.snapshot.items, page);
        const exhausted = page.length < limit;
        this.update({ items, exhausted });
        if (added > 0 || exhausted) {
          break;
        }
      }
    } catch {
      this.update({ olderFailed: true });
    } finally {
      this.update({ loadingOlder: false });
    }
  }

  applyBatch({ task_id, entries }: LogBatchPayload) {
    if (this.source.kind === 'task' && task_id !== this.source.taskId) {
      return;
    }
    // The same exact match the server applies to a page
    const shown = this.level === null ? entries : entries.filter((entry) => entry.level === this.level);
    this.prepend(prependStreamed(this.snapshot.items, shown));
  }

  markMissed() {
    this.prepend([this.marker('missed'), ...this.snapshot.items]);
  }

  private prepend(items: TailItem[]) {
    this.prepended += items.length - this.snapshot.items.length;
    this.update({ items });
  }

  /** A finished task ends the tail of a task source; an agent's tail reloads, as an agent that streams no logs hands them over only when the task ends. */
  onTaskDone({ task_id }: TaskDonePayload) {
    if (this.source.kind === 'task') {
      if (task_id === this.source.taskId) {
        this.update({ taskDone: true });
      }
    } else {
      void this.loadNewest(0);
    }
  }

  private marker(kind: 'skipped' | 'missed') {
    this.markers += 1;
    return { kind, key: `${kind}-${this.markers}` } as const;
  }
}

interface Options {
  /** Keeps the tail live: the orchestrator source polls, an agent or task source streams. */
  follow: boolean;
  /** An exact level, filtered on the server for pages and in the browser for streamed lines. */
  level: string | null;
}

/** The tail of one log source, which a followed orchestrator source keeps live by polling and an agent or task source by its stream. */
export function useLogTail(source: LogSource, { follow, level }: Options) {
  const key = JSON.stringify([source, level]);
  const [stored, setStored] = useState(() => new Tail(key, source, level));
  let tail = stored;
  if (stored.key !== key) {
    tail = new Tail(key, source, level);
    setStored(tail);
  }
  const snapshot = useSyncExternalStore(tail.subscribe, tail.getSnapshot);
  const visible = usePageVisible();
  const agentId = source.kind === 'orchestrator' ? null : source.agentId;
  const streamUrl = follow && agentId !== null && !snapshot.taskDone ? `/api/dashboard/agents/${encodeURIComponent(agentId)}/stream` : null;
  const streaming = streamUrl !== null;

  useEffect(() => {
    if (streaming) {
      return;
    }
    const controller = new AbortController();
    void tail.loadNewest(0, { signal: controller.signal });
    return () => controller.abort();
  }, [tail, streaming]);

  const polling = follow && agentId === null && visible;
  useEffect(() => {
    if (!polling) {
      return;
    }
    const timer = setInterval(() => void tail.loadNewest(FOLLOW_BACKFILL_PAGES, { poll: true }), FOLLOW_POLL_MS);
    return () => clearInterval(timer);
  }, [tail, polling]);

  useEventStream(streamUrl, {
    // On every open, the first and each reconnect, so no line falls between the stream and the page
    onOpen: () => void tail.loadNewest(0),
    onEvent: (name, data) => {
      if (name === 'log_batch') {
        tail.applyBatch(data as LogBatchPayload);
      } else if (name === 'gap') {
        tail.markMissed();
      } else if (name === 'task_done') {
        tail.onTaskDone(data as TaskDonePayload);
      }
    },
  });

  return { ...snapshot, loadOlder: () => void tail.loadOlder() };
}
