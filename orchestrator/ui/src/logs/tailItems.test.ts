// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it } from 'vitest';
import type { LogEntry } from '../types/dashboard';
import { appendOlder, mergeNewest, prependStreamed, type TailItem } from './tailItems';

const entry = (id: string): LogEntry => ({ id, timestamp: '', level: 'INFO', logger: 'agent.ui', message: id });
const entries = (...ids: string[]) => ids.map(entry);
const items = (...ids: string[]): TailItem[] => ids.map((id) => (id === '~' ? { kind: 'skipped', key: 'skipped-1' } : { kind: 'entry', entry: entry(id) }));
const ids = (tail: TailItem[]) => tail.map((item) => (item.kind === 'entry' ? item.entry.id : `<${item.kind}>`));
const skipped = () => ({ kind: 'skipped', key: 'skipped-9' }) as const;

describe('mergeNewest', () => {
  it('takes the page as the tail when nothing is loaded', () => {
    expect(ids(mergeNewest([], entries('t:3', 't:2'), skipped))).toEqual(['t:3', 't:2']);
  });

  it('puts the lines that arrived while the stream was away between the streamed ones, in the order of the page', () => {
    const tail = items('t:9', 't:4', 't:3', 't:2');

    const merged = mergeNewest(tail, entries('t:9', 't:8', 't:7', 't:6', 't:5', 't:4', 't:3'), skipped);

    expect(ids(merged)).toEqual(['t:9', 't:8', 't:7', 't:6', 't:5', 't:4', 't:3', 't:2']);
  });

  it('marks the lines skipped between a page that meets no loaded line and the tail', () => {
    expect(ids(mergeNewest(items('t:2', 't:1'), entries('t:9', 't:8'), skipped))).toEqual(['t:9', 't:8', '<skipped>', 't:2', 't:1']);
  });

  it('keeps the markers of the tail where they are', () => {
    expect(ids(mergeNewest(items('t:5', '~', 't:2'), entries('t:6', 't:5'), skipped))).toEqual(['t:6', 't:5', '<skipped>', 't:2']);
  });
});

describe('prependStreamed', () => {
  it('puts streamed lines on top, newest first, without the ones a page brought', () => {
    expect(ids(prependStreamed(items('t:2', 't:1'), entries('t:2', 't:3', 't:4')))).toEqual(['t:4', 't:3', 't:2', 't:1']);
  });
});

describe('appendOlder', () => {
  it('appends the lines below the last loaded line of the page', () => {
    const { items: tail, added } = appendOlder(items('t:9', 't:8'), entries('t:8', 't:7', 't:6'));

    expect(ids(tail)).toEqual(['t:9', 't:8', 't:7', 't:6']);
    expect(added).toBe(2);
  });

  it('adds nothing from a page above the tail, which holds no loaded line', () => {
    expect(appendOlder(items('t:2', 't:1'), entries('t:9', 't:8')).added).toBe(0);
  });

  it('joins a page only at the last line of a tail with a gap', () => {
    const tail = items('t:9', 't:8', '~', 't:3', 't:2');

    expect(appendOlder(tail, entries('t:8', 't:7', 't:6')).added).toBe(0);
    expect(ids(appendOlder(tail, entries('t:3', 't:2', 't:1')).items)).toEqual(['t:9', 't:8', '<skipped>', 't:3', 't:2', 't:1']);
  });

  it('adds nothing from a page that ends at the tail', () => {
    expect(appendOlder(items('t:3', 't:2'), entries('t:4', 't:3', 't:2')).added).toBe(0);
  });
});
