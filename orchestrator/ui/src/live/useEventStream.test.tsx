// SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
//
// SPDX-License-Identifier: AGPL-3.0-only

// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearStreamToken } from '../data/streamToken';
import { installDom } from '../testing/dom';
import { FakeEventSource, STREAM_TOKEN_PATH, streamToken, stubRoutes } from '../testing/network';
import { RETRY_DELAYS_MS, useEventStream } from './useEventStream';

installDom();

let tokens = 0;

function renderStream(url: string | null = '/api/dashboard/stream') {
  const onEvent = vi.fn();
  const onOpen = vi.fn();
  const view = renderHook(({ streamUrl }) => useEventStream(streamUrl, { onEvent, onOpen }), { initialProps: { streamUrl: url } });
  return { ...view, onEvent, onOpen };
}

/** Lets the token request and the connect that awaits it finish. */
const settle = () => act(() => vi.advanceTimersByTimeAsync(0));

function setHidden(hidden: boolean) {
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(hidden);
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'));
  });
}

describe('useEventStream', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeEventSource.install();
    clearStreamToken();
    tokens = 0;
    stubRoutes(({ path }) => (path === STREAM_TOKEN_PATH ? streamToken(`token-${++tokens}`) : undefined));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('connects with a stream token and hands on the parsed events', async () => {
    const { result, onEvent, onOpen } = renderStream();
    await settle();

    const stream = FakeEventSource.latest();
    expect(stream.url).toBe('/api/dashboard/stream?stream_token=token-1');
    act(() => stream.open());
    act(() => stream.emit('task_done', { task_id: 'task-1' }));

    expect(result.current).toBe('open');
    expect(onOpen).toHaveBeenCalledOnce();
    expect(onEvent).toHaveBeenCalledWith('task_done', { task_id: 'task-1' });
  });

  it('reconnects after a failure with a growing delay, and starts over once a stream opens', async () => {
    const { result } = renderStream();
    await settle();

    for (const delay of RETRY_DELAYS_MS.slice(0, 3)) {
      act(() => FakeEventSource.latest().fail());
      expect(result.current).toBe('reconnecting');
      const failed = FakeEventSource.instances.length;
      await act(() => vi.advanceTimersByTimeAsync(delay - 1));
      expect(FakeEventSource.instances).toHaveLength(failed);
      await act(() => vi.advanceTimersByTimeAsync(1));
      expect(FakeEventSource.instances).toHaveLength(failed + 1);
    }
    expect(FakeEventSource.instances.slice(0, -1).every((stream) => stream.closed)).toBe(true);

    act(() => FakeEventSource.latest().open());
    act(() => FakeEventSource.latest().fail());
    await act(() => vi.advanceTimersByTimeAsync(RETRY_DELAYS_MS[0]));

    expect(FakeEventSource.instances).toHaveLength(5);
  });

  it('reconnects at once with a new stream token after auth_error', async () => {
    const { onOpen } = renderStream();
    await settle();
    const first = FakeEventSource.latest();
    act(() => first.open());

    act(() => first.emit('auth_error', {}));
    await settle();

    expect(first.closed).toBe(true);
    expect(FakeEventSource.latest().url).toBe('/api/dashboard/stream?stream_token=token-2');
    act(() => FakeEventSource.latest().open());
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it('closes the stream in a hidden tab and opens it again when the tab is shown', async () => {
    renderStream();
    await settle();
    const first = FakeEventSource.latest();

    setHidden(true);
    expect(first.closed).toBe(true);
    await settle();
    expect(FakeEventSource.instances).toHaveLength(1);

    setHidden(false);
    await settle();

    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.latest().closed).toBe(false);
  });

  it('opens no stream without a URL and closes it when the URL goes', async () => {
    const { rerender } = renderStream(null);
    await settle();
    expect(FakeEventSource.instances).toHaveLength(0);

    rerender({ streamUrl: '/api/dashboard/agents/ui/stream' });
    await settle();
    rerender({ streamUrl: null });

    expect(FakeEventSource.latest().closed).toBe(true);
  });
});
