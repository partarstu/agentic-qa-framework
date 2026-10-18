// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import type { LogEntry } from '../types/dashboard';

/** A line of a log tail, or a marker where lines are missing: `skipped` between pages that did not meet, `missed` where the stream lost events. */
export type TailItem = { kind: 'entry'; entry: LogEntry } | { kind: 'skipped' | 'missed'; key: string };

type Marker = Extract<TailItem, { key: string }>;

const asItem = (entry: LogEntry): TailItem => ({ kind: 'entry', entry });

function loadedIds(items: TailItem[]): Set<string> {
  return new Set(items.flatMap((item) => (item.kind === 'entry' ? [item.entry.id] : [])));
}

export function entryCount(items: TailItem[]): number {
  return items.filter((item) => item.kind === 'entry').length;
}

export function overlaps(items: TailItem[], page: LogEntry[]): boolean {
  const ids = loadedIds(items);
  return page.some((entry) => ids.has(entry.id));
}

/** Merges a page of the newest lines (newest first) into the tail, in the order of the page, or on top of it after a `skipped` marker when they share no line. */
export function mergeNewest(items: TailItem[], page: LogEntry[], skipped: () => Marker): TailItem[] {
  if (page.length === 0) {
    return items;
  }
  if (items.length === 0) {
    return page.map(asItem);
  }
  const ids = loadedIds(items);
  if (!page.some((entry) => ids.has(entry.id))) {
    return [...page.map(asItem), skipped(), ...items];
  }
  // The page orders the lines it shares with the tail, so lines that arrived while the stream was away land between those it delivered
  const merged: TailItem[] = [];
  let next = 0;
  for (const entry of page) {
    if (!ids.has(entry.id)) {
      merged.push(asItem(entry));
      continue;
    }
    while (next < items.length) {
      const item = items[next++];
      merged.push(item);
      if (item.kind === 'entry' && item.entry.id === entry.id) {
        break;
      }
    }
  }
  return [...merged, ...items.slice(next)];
}

/** Puts streamed lines (oldest first) on top of the tail, leaving out those a page already brought. */
export function prependStreamed(items: TailItem[], entries: LogEntry[]): TailItem[] {
  const ids = loadedIds(items);
  const fresh = entries.filter((entry) => !ids.has(entry.id));
  return fresh.length === 0 ? items : [...fresh.toReversed().map(asItem), ...items];
}

/** Appends the lines of an older page that lie below the tail's last line. */
export function appendOlder(items: TailItem[], page: LogEntry[]): { items: TailItem[]; added: number } {
  const last = items.findLast((item): item is Extract<TailItem, { kind: 'entry' }> => item.kind === 'entry');
  if (last === undefined) {
    return { items: page.map(asItem), added: page.length };
  }
  // Only the tail's last line tells which lines of a page are older, so the caller requests each older page one line into the tail;
  // a page without it lies above the tail's end, also when the tail holds a gap
  const joint = page.findIndex((entry) => entry.id === last.entry.id);
  const ids = loadedIds(items);
  const older = joint < 0 ? [] : page.slice(joint + 1).filter((entry) => !ids.has(entry.id));
  return { items: [...items, ...older.map(asItem)], added: older.length };
}
